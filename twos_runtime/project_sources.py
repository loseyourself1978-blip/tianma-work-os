"""Bounded, preview-only source parsing. Imported documents are inert data."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import PurePosixPath
import re
import stat
import unicodedata
import zipfile

MAX_UPLOAD = 32 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
MAX_ENTRIES = 1500
TEXT_TYPES = {'.md', '.txt', '.json', '.yaml', '.yml', '.csv'}
SECRET_NAMES = re.compile(r'(^|/)(\.env(?:\..*)?|auth\.json|cookies?(?:\..*)?|credentials?(?:\..*)?|id_(?:rsa|ed25519)|.*\.(?:pem|p12|key))$', re.I)
SECRET_VALUES = re.compile(r'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----|\b(?:sk-[A-Za-z0-9_-]{18,}|gh[pousr]_[A-Za-z0-9]{20,})\b|(?:authorization\s*:\s*bearer\s+\S+)|(?:["\']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret|app[_-]?secret)["\']?\s*[:=]\s*["\']?)(?!NONE\b|null\b|false\b|REDACTED\b|<|\$\{|\[)[A-Za-z0-9_+/.-]{12,}', re.I)


class SourceError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def safe_name(name):
    if not isinstance(name, str) or not name or len(name) > 512 or any(ord(c)<32 for c in name) or '\\' in name or '\x00' in name:
        raise SourceError('IMPORT_PATH_UNSAFE')
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ('', '..', '.') for x in name.split('/')) or ':' in name or name.startswith('/'):
        raise SourceError('IMPORT_PATH_UNSAFE')
    return name


def scan_text(name, data):
    if SECRET_NAMES.search(name):
        return 'DO_NOT_IMPORT', 'CREDENTIAL_FILENAME', None
    if len(data) > MAX_FILE:
        return 'REFERENCE_ONLY', 'FILE_TOO_LARGE', None
    if PurePosixPath(name).suffix.lower() not in TEXT_TYPES:
        return 'REFERENCE_ONLY', 'UNSUPPORTED_FORMAT', None
    try:
        body = data.decode('utf-8-sig')
    except UnicodeError:
        return 'REFERENCE_ONLY', 'UTF8_REQUIRED', None
    if '\x00' in body or SECRET_VALUES.search(body):
        return 'DO_NOT_IMPORT', 'POSSIBLE_CREDENTIAL', None
    if name.lower().endswith('.json'):
        try:
            json.loads(body)
        except (ValueError, RecursionError):
            return 'REFERENCE_ONLY', 'JSON_INVALID', None
    return 'SAFE_IMPORT', 'TEXT_DATA_ONLY', body


def preview(name, data):
    safe_name(name)
    if len(data) > MAX_UPLOAD:
        raise SourceError('IMPORT_TOO_LARGE')
    entries = []
    manifests = []
    if name.lower().endswith('.zip'):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_EXPANDED:
                    raise SourceError('IMPORT_TOO_LARGE')
                seen = set()
                for i in infos:
                    key = unicodedata.normalize('NFC', safe_name(i.filename.rstrip('/'))).casefold()
                    if key in seen:
                        raise SourceError('IMPORT_DUPLICATE_PATH')
                    seen.add(key)
                    mode = i.external_attr >> 16
                    if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)) or i.flag_bits & 1:
                        raise SourceError('IMPORT_LINK_OR_ENCRYPTION')
                    if i.is_dir():
                        continue
                    if PurePosixPath(i.filename).suffix.lower() in {'.zip','.tar','.gz','.7z','.rar'}:
                        raise SourceError('IMPORT_NESTING_UNSUPPORTED')
                    # Bounded total includes files retained only as references; CRC checked for all.
                    payload = archive.read(i)
                    entries.append((i.filename, payload))
                    if PurePosixPath(i.filename).name.lower() in {'manifest.sha256','sha256sums','sha256sums.txt'}:
                        manifests.append((i.filename, payload))
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError):
            raise SourceError('IMPORT_ZIP_INVALID') from None
    else:
        entries = [(name, data)]
    hashes = {n: hashlib.sha256(b).hexdigest() for n,b in entries}
    verified = 0
    json_manifest = next(((n,b) for n,b in entries if n == 'ZIP_MANIFEST.json'), None)
    if json_manifest:
        try:
            records = json.loads(json_manifest[1])['files']
            if not isinstance(records,list) or not records:
                raise ValueError()
            declared=set()
            sizes={n:len(b) for n,b in entries}
            for item in records:
                target=safe_name(item['path'])
                expected=item['export_sha256'];size=item['export_bytes']
                if target in declared or target==json_manifest[0] or not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected):
                    raise ValueError()
                declared.add(target)
                if hashes.get(target)!=expected or sizes.get(target)!=size:
                    raise SourceError('IMPORT_MANIFEST_MISMATCH')
            if declared != set(hashes)-{json_manifest[0]}:
                raise SourceError('IMPORT_MANIFEST_MISMATCH')
            verified=len(records)
        except (ValueError,KeyError,TypeError,RecursionError):
            raise SourceError('IMPORT_MANIFEST_INVALID') from None
    for manifest_name, content in manifests:
        try:
            lines = content.decode('utf-8').splitlines()
        except UnicodeError:
            raise SourceError('IMPORT_MANIFEST_INVALID') from None
        manifest_seen = set()
        for line in lines:
            if not line.strip():
                continue
            match = re.fullmatch(r'([a-fA-F0-9]{64})\s+\*?(.+)', line)
            if not match:
                raise SourceError('IMPORT_MANIFEST_INVALID')
            expected, target = match.groups()
            safe_name(target)
            if target in manifest_seen:
                raise SourceError('IMPORT_MANIFEST_INVALID')
            manifest_seen.add(target)
            relative = str(PurePosixPath(manifest_name).parent / target)
            matches = {key for key in (target, relative) if key in hashes}
            if len(matches) != 1 or hashes[next(iter(matches))] != expected.lower():
                raise SourceError('IMPORT_MANIFEST_MISMATCH')
            verified += 1
    result = []
    for filename, payload in entries:
        category, reason, body = scan_text(filename, payload)
        result.append({'name':filename,'sha256':hashes[filename],'size':len(payload),
                       'classification':category,'reason':reason,'content':body,
                       'language':'zh-CN' if body and re.search(r'[\u3400-\u9fff]',body) else 'en-US'})
    return {'name':name,'sha256':hashlib.sha256(data).hexdigest(),'entries':result,
            'manifest_entries_verified':verified,'manifest_count':len(manifests)+int(bool(json_manifest)),
            'crc':'PASS' if name.lower().endswith('.zip') else 'NOT_APPLICABLE',
            'full_historical_restoration':False,'credentials_imported':False}
