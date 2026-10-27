#!/usr/bin/env python3
"""Build the pinned Nyra component inside TWOS; never fetch external assets."""
import argparse, hashlib, json, plistlib, shutil, subprocess
from pathlib import Path

def build(source, destination, cache):
    source, destination, cache = map(Path, (source, destination, cache))
    manifest = json.loads((source/'Resources/component-manifest.json').read_text())
    if manifest.get('product') != 'Nyra' or manifest.get('event_schema') != 'twos.nyra.status.v1':
        raise ValueError('Unrecognized Nyra component manifest')
    for name, expected in manifest['bundle_files'].items():
        path = source/'Resources'/name
        if path.is_symlink() or not path.resolve().is_relative_to((source/'Resources').resolve()):
            raise ValueError('Nyra resource escapes the component: '+name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Nyra resource hash mismatch: '+name)
    listed_sources = {name for name in manifest['files'] if name.startswith('Sources/')}
    actual_sources = {p.relative_to(source).as_posix() for p in (source/'Sources').glob('*.swift')}
    if listed_sources != actual_sources:
        raise ValueError('Nyra source membership differs from the pinned manifest')
    for name in listed_sources:
        path = source/name
        if path.is_symlink() or not path.resolve().is_relative_to((source/'Sources').resolve()):
            raise ValueError('Nyra source escapes component: '+name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['files'][name]:
            raise ValueError('Nyra source hash mismatch: '+name)
    contents = destination / 'Contents'; (contents/'MacOS').mkdir(parents=True,exist_ok=True)
    for name in [*manifest['bundle_files'], 'component-manifest.json']:
        target = contents/'Resources'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/'Resources'/name,target)
    (contents/'Info.plist').write_bytes(plistlib.dumps(dict(CFBundleName='TWOS · 夜璃 Nyra',CFBundleDisplayName='TWOS · 夜璃 Nyra',CFBundleIdentifier='com.tianma.workos.nyra',CFBundleExecutable='TWOSNyra',CFBundlePackageType='APPL',CFBundleShortVersionString=manifest['version'],CFBundleVersion=manifest['build'],LSMinimumSystemVersion='13.0',LSUIElement=True,NSHighResolutionCapable=True,NSPrincipalClass='NSApplication',LSMultipleInstancesProhibited=True,NyraVisibilityProtocol=1,CFBundleURLTypes=[dict(CFBundleURLName='TWOS Nyra visibility',CFBundleURLSchemes=['nyra','twos-nyra'])])))
    cache.mkdir(parents=True,exist_ok=True)
    subprocess.run(['xcrun','swiftc','-swift-version','5','-O','-target','arm64-apple-macos13.0','-module-cache-path',str(cache),'-framework','AppKit','-framework','AVFoundation',*[str(p) for p in sorted((source/'Sources').glob('*.swift'))],'-o',str(contents/'MacOS/TWOSNyra')],check=True)
    subprocess.run(['codesign','--force','--sign','-',str(destination)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(destination)],check=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--destination',required=True);p.add_argument('--cache',required=True);a=p.parse_args();build(a.source,a.destination,a.cache)
