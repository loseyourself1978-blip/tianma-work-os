"""Private, bounded invocation diagnostics and a strict CLI final-channel contract.

Only hashes/statuses leave this module. Response bytes stay in a 0700 directory,
0600 files, at most 32 receipts for 7 days. No stderr, prompt or credentials are
copied. A missing/withheld payload is never described as a replayable response.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import re
import fcntl
import time
import uuid

MAX_FINAL = 1_000_000
MAX_EVENTS = 200
MAX_RECEIPTS = 32
RETENTION_SECONDS = 7 * 86400


class ExecutionFailure(Exception):
    def __init__(self, code, evidence=None):
        self.code = code
        self.evidence = evidence or {}
        super().__init__(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_final(path, *, started_ns=None):
    """No links/devices/old files; open nonblocking so a FIFO cannot hang us."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or not 0 < info.st_size <= MAX_FINAL
                    or (started_ns is not None and info.st_mtime_ns < started_ns)):
                raise ExecutionFailure('RESULT_FILE_INVALID')
            raw = stream.read(MAX_FINAL + 1)
            if len(raw) != info.st_size or len(raw) > MAX_FINAL:
                raise ExecutionFailure('RESULT_FILE_INVALID')
            return raw
    except OSError:
        raise ExecutionFailure('RESULT_FILE_UNAVAILABLE') from None


class EventStream:
    """One exec turn. IDs come from the CLI; absent phases remain absent."""
    def __init__(self):
        self.events = []
        self.items = {}
        self.messages = []
        self.diagnostics = []
        self.raw_lines = []
        self.tail = b''
        self.thread_id = None
        self.started = False
        self.terminal = False
        self.usage = None

    def accept_metadata_warning(self, event, requested_model):
        """One known CLI pre-turn advisory, never a failed turn or provider error.

        The CLI emits this local catalog fallback as an error item even when
        the requested model completes normally. Bind the exact wording/model
        and position; final-file, terminal, exit and schema checks still apply.
        """
        item = event.get('item') if isinstance(event, dict) else None
        if (not isinstance(event, dict) or not isinstance(requested_model, str)
                or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', requested_model)
                or set(event) != {'type', 'item'} or event['type'] != 'item.completed'
                or not isinstance(item, dict) or set(item) != {'id', 'type', 'message'}
                or item['type'] != 'error'
                or item['message'] != f'Model metadata for `{requested_model}` not found. Defaulting to fallback metadata; this can degrade performance and cause issues.'
                or not isinstance(item['id'], str)
                or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', item['id'])
                or not self.thread_id or self.started or self.terminal or self.items):
            return False
        self.items[item['id']] = item
        self.events.append({'sequence': len(self.events), 'type': event['type'],
                            'item_id': item['id'], 'item_type': item['type'],
                            'warning_code': 'CLI_MODEL_METADATA_FALLBACK'})
        self.diagnostics.append({'warning_code': 'CLI_MODEL_METADATA_FALLBACK', 'event': event})
        return True

    def accept(self, event):
        if not isinstance(event, dict) or not isinstance(event.get('item', {}), dict):
            raise ExecutionFailure('RESULT_EVENT_STREAM_INCOMPLETE')
        kind = event.get('type')
        item = event.get('item', {})
        for value in (kind, item.get('id', 'item'), item.get('type', 'item'), item.get('phase', 'absent'), event.get('thread_id', 'absent')):
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value)):
                raise ExecutionFailure('RESULT_EVENT_STREAM_INCOMPLETE')
        metadata = {'sequence': len(self.events), 'type': kind}
        for key in ('id', 'type', 'phase'):
            if key in item:
                metadata['item_' + key] = item[key]
        self.events.append(metadata)
        if len(self.events) > MAX_EVENTS:
            raise ExecutionFailure('EXECUTION_OUTPUT_LIMIT')
        if kind in ('error', 'turn.failed'):
            # Provider text is classified by the adapter, never copied here.
            raise ExecutionFailure('EXECUTION_INCOMPLETE')
        if kind == 'item.completed' and item.get('type') == 'refusal':
            raise ExecutionFailure('PROVIDER_REFUSED')
        if self.terminal:
            raise ExecutionFailure('RESULT_TERMINAL_CONFLICT')
        if kind == 'thread.started':
            if self.thread_id or self.started or not isinstance(event.get('thread_id'), str):
                raise ExecutionFailure('RESULT_EVENT_STREAM_INCOMPLETE')
            self.thread_id = event['thread_id']
        elif kind == 'turn.started':
            if not self.thread_id or self.started:
                raise ExecutionFailure('RESULT_EVENT_STREAM_INCOMPLETE')
            self.started = True
        elif kind == 'item.completed':
            if not self.started or not isinstance(item.get('id'), str):
                raise ExecutionFailure('RESULT_EVENT_STREAM_INCOMPLETE')
            identity = item['id']
            if identity in self.items:
                if self.items[identity] != item:
                    raise ExecutionFailure('RESULT_ITEM_CONFLICT')
                metadata['duplicate_of_item'] = identity
                return
            self.items[identity] = item
            if item.get('type') == 'agent_message':
                if not isinstance(item.get('text'), str):
                    raise ExecutionFailure('RESULT_EVENT_STREAM_INCOMPLETE')
                self.messages.append(dict(item, event_sequence=metadata['sequence']))
        elif kind == 'turn.completed':
            if not self.started:
                raise ExecutionFailure('RESULT_EVENT_STREAM_INCOMPLETE')
            self.terminal = True
            self.usage = event.get('usage')
        elif not self.started:
            raise ExecutionFailure('RESULT_EVENT_STREAM_INCOMPLETE')

    def extract(self, path, *, started_ns=None):
        if not self.terminal:
            raise ExecutionFailure('EXECUTION_INCOMPLETE')
        raw = safe_final(path, started_ns=started_ns)
        try:
            output = raw.decode('utf-8', errors='strict')
        except UnicodeError:
            raise ExecutionFailure('RESULT_FILE_UNAVAILABLE') from None
        # CLI 0.156.1's output-last-message contains the final emitted message.
        # It may append one LF. Preserve all other whitespace and raw hash.
        if not self.messages:
            raise ExecutionFailure('RESULT_FINAL_AMBIGUOUS')
        explicit = [m for m in self.messages if m.get('phase') == 'final_answer']
        if len(explicit) > 1 or (explicit and explicit[0] is not self.messages[-1]):
            raise ExecutionFailure('RESULT_FINAL_AMBIGUOUS')
        message = self.messages[-1]
        expected = message['text']
        if message.get('phase') not in (None, 'final_answer') or not expected:
            raise ExecutionFailure('RESULT_FINAL_AMBIGUOUS')
        if output != expected and output != expected + '\n':
            raise ExecutionFailure('RESULT_FINAL_AMBIGUOUS')
        return expected, {'final_result_sha256': sha(raw), 'final_result_bytes': len(raw),
                          'final_message_id': message['id'],
                          'final_message_sequence': message['event_sequence'],
                          'normalization': 'NONE' if output == expected else 'ONE_TRAILING_LF',
                          'final_text_sha256': sha(expected.encode())}


def private_directory(path):
    path = Path(path).absolute()
    # Resolve system temp aliases before calling; reject symlink ancestors.
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise OSError('unsafe evidence path')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError('evidence directory is not private')
    return path


def atomic(path, raw):
    scratch = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(scratch, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        scratch.unlink(missing_ok=True)


class EvidenceReceipt:
    def __init__(self, root, binding):
        self.root = private_directory(root)
        lock = os.open(self.root / '.retention.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.prune()
            if len(list(self.root.glob('invocation_*'))) >= MAX_RECEIPTS:
                raise OSError('evidence retention capacity reached')
            self.id = 'invocation_' + uuid.uuid4().hex
            self.path = private_directory(self.root / self.id)
        finally:
            os.close(lock)
        self.binding = binding
        self.status = {}
        self.capture(None, None, exit_code=None, failure=None, state='PREPARED')
        if self.status['persistence'] != 'SAVED':
            raise OSError('cannot prepare invocation evidence')

    def prune(self):
        # Touch only this product's complete private receipts, never arbitrary
        # files or active invocations. File-count and TTL are independent caps.
        candidates = []
        for path in self.root.glob('invocation_*'):
            if path.is_symlink() or not path.is_dir():
                continue
            try:
                value = json.loads((path / 'receipt.json').read_bytes())
                if value['state'] in ('PREPARED', 'RUNNING'):
                    continue
                candidates.append((path.stat().st_mtime, path))
            except (OSError, ValueError, KeyError):
                continue
        candidates.sort(reverse=True)
        active_count = len(list(self.root.glob('invocation_*'))) - len(candidates)
        retain = max(0, MAX_RECEIPTS - 1 - active_count)
        for index, (modified, path) in enumerate(candidates):
            if index < retain and time.time() - modified < RETENTION_SECONDS:
                continue
            if set(p.name for p in path.iterdir()) <= {'receipt.json', 'final.bin', 'messages.json', 'diagnostics.json', 'events.jsonl'}:
                for p in path.iterdir():
                    p.unlink()
                path.rmdir()

    def capture(self, final_path, stream, *, exit_code, failure, state):
        from .project_sources import SECRET_VALUES
        raw = None
        file_state = 'NOT_CREATED'
        if final_path is not None:
            try:
                raw = safe_final(final_path)
                file_state = 'READ'
            except ExecutionFailure as exc:
                file_state = exc.code
        messages = json.dumps(stream.messages if stream else [], ensure_ascii=False).encode()
        event_bytes = (b''.join(stream.raw_lines) + stream.tail) if stream else b''
        diagnostics = json.dumps(stream.diagnostics if stream else [], ensure_ascii=False).encode()
        withheld = bool(SECRET_VALUES.search(event_bytes.decode('utf-8','replace')) or SECRET_VALUES.search(diagnostics.decode()) or SECRET_VALUES.search(messages.decode()) or
                        (raw is not None and SECRET_VALUES.search(raw.decode('utf-8', 'replace'))))
        value = {'receipt_id': self.id, 'binding': self.binding, 'state': state,
                 'recorded_at': datetime.now(timezone.utc).isoformat(),
                 'exit_code': exit_code if exit_code is not None else 'UNKNOWN',
                 'failure_point': failure, 'events': stream.events if stream else [],
                 'final_file_state': file_state, 'final_sha256': sha(raw) if raw is not None else None,
                 'final_bytes': len(raw) if raw is not None else None,
                 'event_stream_sha256': sha(event_bytes), 'event_stream_bytes': len(event_bytes),
                 'payload_state': 'WITHHELD_SECRET' if withheld else 'REPLAYABLE' if raw else 'FINAL_UNAVAILABLE',
                 'retention_days': 7, 'receipt_limit': MAX_RECEIPTS,
                 'evidence_complete': bool(raw is not None and not withheld and stream and stream.terminal and state in ('CAPTURED','FAILED'))}
        try:
            if not withheld:
                if raw is not None:
                    atomic(self.path / 'final.bin', raw)
                atomic(self.path / 'messages.json', messages)
                atomic(self.path / 'diagnostics.json', diagnostics)
                atomic(self.path / 'events.jsonl', event_bytes)
            else:
                for name in ('final.bin', 'messages.json', 'diagnostics.json', 'events.jsonl'):
                    (self.path / name).unlink(missing_ok=True)
            atomic(self.path / 'receipt.json', json.dumps(value, ensure_ascii=False, indent=2).encode())
            self.status = {k: value[k] for k in ('receipt_id', 'final_file_state', 'final_sha256', 'final_bytes', 'payload_state')}
            self.status['persistence'] = 'SAVED'
        except OSError:
            # Try a small independent status receipt without claiming the raw
            # payload was retained. If the volume itself fails, the execution's
            # database evidence still receives the explicit failure below.
            try:
                atomic(self.path / 'receipt.json', json.dumps({**value, 'state':'EVIDENCE_WRITE_FAILED',
                    'payload_state':'NOT_CONFIRMED','evidence_complete':False}).encode())
            except OSError:
                pass
            self.status = {'receipt_id': self.id, 'persistence': 'FAILED',
                           'payload_state': 'NOT_CONFIRMED', 'error': 'EVIDENCE_WRITE_FAILED'}
        return self.status


def recover(root, execution_id):
    """Expose only diagnostic availability after an interrupted process, no resume."""
    found = []
    root = Path(root)
    if not root.exists():
        return {'persistence': 'MISSING', 'payload_state': 'NOT_RECORDED'}
    try:
        private_directory(root)
        for path in root.glob('invocation_*'):
            if path.is_symlink() or not path.is_dir():
                continue
            value = json.loads((path / 'receipt.json').read_bytes())
            if value['binding'].get('execution_id') != execution_id:
                continue
            if value['state'] in ('PREPARED', 'RUNNING'):
                value['state'] = 'INTERRUPTED'
                value['failure_point'] = 'APPLICATION_INTERRUPTED'
                value['evidence_complete'] = False
                atomic(path / 'receipt.json', json.dumps(value, indent=2).encode())
            found.append({'receipt_id': value['receipt_id'], 'persistence': 'SAVED',
                          'payload_state': value['payload_state'], 'state': value['state'],
                          'evidence_complete': value.get('evidence_complete', False)})
    except (OSError, ValueError, KeyError):
        return {'persistence': 'FAILED', 'payload_state': 'NOT_CONFIRMED'}
    return found[-1] if found else {'persistence': 'MISSING', 'payload_state': 'NOT_RECORDED'}
