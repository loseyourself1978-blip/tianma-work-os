#!/usr/bin/env python3
"""Stage exact product resources; never replace missing capabilities with a shell.

Run by the native Xcode target. An existing direct build is an input, not Store
approval. Never copies browser profiles or installed Owner application data.
"""
from pathlib import Path
import hashlib
import json
import os
import plistlib
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def verify_input(app):
    receipt = json.loads((app / 'Contents/Resources/source-provenance.json').read_text())
    hashes = receipt['input_hashes']
    if not hashes or receipt['bundle_identifier'] != 'com.tianma.workos':
        raise ValueError('Not a TWOS prepared product')
    # Verify the complete current input set, not only entries listed by an old receipt.
    from build_macos import source_inputs
    if set(hashes) != set(source_inputs(ROOT)):
        raise ValueError('Prepared product input set does not match current source')
    for name, expected in hashes.items():
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Input escapes repository: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Prepared product is stale for ' + name)
    if hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest() != receipt['source_input_sha256']:
        raise ValueError('Source receipt does not match its input hashes')
    if not (app / 'Contents/Resources/engine/twos-service').is_file() or not (app / 'Contents/Helpers/TWOS Nyra.app/Contents/MacOS/TWOSNyra').is_file():
        raise ValueError('Both the local runtime and embedded Nyra are required')
    return receipt


def main():
    source = os.environ.get('TWOS_PREPARED_APP', '')
    if not source:
        raise ValueError('TWOS_PREPARED_APP is missing. Prepare the matching complete product; do not archive a native-only shell.')
    app = Path(source).resolve(strict=True)
    receipt = verify_input(app)
    if os.environ.get('TWOS_DISTRIBUTION') == 'store':
        # The current implementation has unresolved selected-directory,
        # external-executor and helper sandbox requirements. A signing team is
        # not evidence that these core capabilities work under App Sandbox.
        raise ValueError('STORE_NOT_READY: sandboxed directory/executor/helper integration and third-party service permissions require verified closure. No Store archive or upload is claimed.')
    contents = Path(os.environ['TARGET_BUILD_DIR']) / os.environ['CONTENTS_FOLDER_PATH']
    for name in ('Resources', 'Helpers'):
        target = contents / name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(app / 'Contents' / name, target, symlinks=True, dirs_exist_ok=True)
    info_path = contents / 'Info.plist'
    if info_path.exists():
        info = plistlib.loads(info_path.read_bytes())
        info.update(CFBundleShortVersionString=receipt['version'], CFBundleVersion=receipt['build_version'],
                    TWOSSourceCommit=receipt['source_commit'], TWOSSourceInputSHA256=receipt['source_input_sha256'])
        info_path.write_bytes(plistlib.dumps(info))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print('error: ' + str(error), file=sys.stderr)
        sys.exit(1)
