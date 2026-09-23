from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

import pytest

from scripts import build_release as release

ROOT = Path(__file__).resolve().parents[1]


def command(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True,
                            env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')})
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture(scope='module')
def candidate_repo(tmp_path_factory):
    """Commit the prospective source in a disposable fixture; never change real HEAD."""
    repo = tmp_path_factory.mktemp('release-candidate-source')
    names = command(ROOT, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split('\0')
    for name in names:
        if not name:
            continue
        source = ROOT / name
        if not source.is_file():
            continue
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    command(repo, 'init', '--initial-branch=main')
    command(repo, 'config', 'user.name', 'Release fixture')
    command(repo, 'config', 'user.email', 'release@example.invalid')
    command(repo, 'add', '.')
    command(repo, 'commit', '-m', 'prospective source fixture')
    return repo


@pytest.fixture(scope='module')
def artifact(candidate_repo, tmp_path_factory):
    return release.build(candidate_repo, tmp_path_factory.mktemp('release-output'))


def test_exact_head_manifest_hash_required_docs_and_deterministic_bytes(candidate_repo, artifact, tmp_path):
    archive, manifest_path = artifact
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest['source_git_sha'] == command(candidate_repo, 'rev-parse', 'HEAD')
    assert manifest['application_version'] == '1.0.0'
    assert manifest['schema_version'] == 'vol20.001'
    assert archive.name == f"twos-1.0.0-{manifest['source_git_sha'][:12]}.tar.gz"
    assert manifest_path.name == archive.name.removesuffix('.tar.gz') + '.manifest.json'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['sha256']
    assert release.inspect(archive, manifest_path)['verified']
    second, second_manifest = release.build(candidate_repo, tmp_path / 'repeat')
    assert second.read_bytes() == archive.read_bytes()
    assert second_manifest.read_bytes() == manifest_path.read_bytes()
    names = set(manifest['files'])
    assert release.REQUIRED <= names
    assert not any(n.startswith(('tests/', 'records/', 'reports/')) for n in names)
    assert not any('acceptance_app' in n for n in names)
    for name in names:
        release.validate_path(name)


@pytest.mark.parametrize('name', ['.git/config', '.venv/bin/python', 'a/.env', 'twos.sqlite3',
    'a.twos-backup/manifest.json', 'x/auth.json', 'logs/private.log', 'runtime.pid',
    'a/__pycache__/x.pyc', '../escape', '/absolute', 'a/../escape', 'a/../../b'])
def test_package_forbidden_paths(name):
    with pytest.raises(release.ReleaseError):
        release.validate_path(name)


def test_unknown_secret_in_test_fixture_is_not_exempted():
    with pytest.raises(release.ReleaseError, match='Secret scan'):
        release.scan('tests/new_fixture.py', ('sk-' + 'Q' * 40).encode(), strict=False)
    with pytest.raises(release.ReleaseError, match='Database content'):
        release.scan('twos_runtime/innocent.txt', b'SQLite format 3\0more')


def test_builder_fails_dirty_and_prohibited_committed_content(candidate_repo, tmp_path):
    repo = tmp_path / 'repo'
    subprocess.run(['git', 'clone', '--no-hardlinks', str(candidate_repo), str(repo)], check=True, capture_output=True)
    command(repo, 'config', 'user.name', 'Fixture')
    command(repo, 'config', 'user.email', 'fixture@example.invalid')
    (repo / 'README.md').write_text('dirty')
    with pytest.raises(release.ReleaseError, match='clean'):
        release.build(repo, tmp_path / 'dirty')
    command(repo, 'add', 'README.md')
    command(repo, 'commit', '-m', 'fixture docs')
    (repo / 'accidental.sqlite3').write_bytes(b'not actually sqlite')
    command(repo, 'add', 'accidental.sqlite3')
    command(repo, 'commit', '-m', 'prohibited fixture')
    with pytest.raises(release.ReleaseError, match='Prohibited'):
        release.build(repo, tmp_path / 'prohibited')


def test_untracked_private_state_never_enters_archive(candidate_repo, tmp_path):
    private = candidate_repo / 'not-tracked.sqlite3'
    private.write_bytes(b'SQLite format 3\0not real data')
    try:
        archive, manifest = release.build(candidate_repo, tmp_path / 'build')
        assert 'not-tracked.sqlite3' not in json.loads(manifest.read_bytes())['files']
        assert release.inspect(archive, manifest)['verified']
    finally:
        private.unlink()


def test_archive_tamper_and_member_traversal_rejected(artifact, tmp_path):
    archive, manifest = artifact
    altered = tmp_path / archive.name
    altered.write_bytes(archive.read_bytes() + b'x')
    with pytest.raises(release.ReleaseError, match='hash'):
        release.inspect(altered, manifest)
    metadata = json.loads(manifest.read_bytes())
    with tarfile.open(altered, 'w:gz') as bundle:
        member = tarfile.TarInfo(metadata['artifact_identity'] + '/../escape')
        member.size = 1
        bundle.addfile(member, io.BytesIO(b'x'))
    metadata['sha256'] = hashlib.sha256(altered.read_bytes()).hexdigest()
    modified_manifest = tmp_path / 'manifest.json'
    modified_manifest.write_text(json.dumps(metadata))
    with pytest.raises(release.ReleaseError, match='Prohibited'):
        release.inspect(altered, modified_manifest)


def test_owner_guide_sections_and_packaged_links(artifact):
    archive, manifest = artifact
    metadata = json.loads(manifest.read_bytes())
    with tarfile.open(archive, 'r:gz') as bundle:
        files = {m.name.split('/', 1)[1]: bundle.extractfile(m).read().decode()
                 for m in bundle if m.isfile() and m.name.endswith('.md')}
    guide = files['docs/OWNER_GUIDE.md']
    for number in range(1, 29):
        assert re.search(r'^## ' + str(number) + r'\.', guide, re.M)
    assert 'Owner Guide' in files['README.md']
    for name, text in files.items():
        for link in re.findall(r'\]\(([^)]+)\)', text):
            if '://' in link or link.startswith('#'):
                continue
            resolved = os.path.normpath(str(Path(name).parent / link.split('#')[0]))
            assert resolved in metadata['files'], (name, link)
    assert '/Users/' not in guide
    assert 'releases/tag/v1.0.0' in guide
    assert 'NOT RELEASED' not in guide


def test_artifact_canonical_bootstrap_first_owner_task_restart(artifact, tmp_path, monkeypatch):
    # Exercise the existing real HTTP, zero-Owner, isolated HOME/runtime/data/
    # workspace, Task/login/restart and zero provider/run/delivery evidence gate
    # using the independently inspected archive, never a worktree copy.
    from tests import test_vol19_fresh_install_bootstrap as fresh
    archive, manifest = artifact
    release.inspect(archive, manifest)
    def extract(destination):
        destination.mkdir()
        with tarfile.open(archive, 'r:gz') as bundle:
            for member in bundle:
                relative = member.name.split('/', 1)[1]
                release.validate_path(relative)
                assert member.isfile()
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.extractfile(member).read())
                target.chmod(member.mode)
        assert not (destination / '.venv').exists()
        assert not (destination / '.git').exists()
        assert (destination / 'docs/OWNER_GUIDE.md').is_file()
    monkeypatch.setattr(fresh, 'clean_source_copy', extract)
    fresh.test_canonical_bootstrap_real_http_first_run_and_restart(tmp_path)


@pytest.mark.parametrize('identity', ['../escape', '/outside', 'nested/name'])
def test_full_archive_identity_is_validated(artifact, tmp_path, identity):
    archive, manifest = artifact
    data = json.loads(manifest.read_text())
    data['artifact_identity'] = identity
    forged = tmp_path / 'manifest.json'
    forged.write_text(json.dumps(data))
    with pytest.raises(release.ReleaseError, match='identity'):
        release.inspect(archive, forged)


@pytest.mark.parametrize('key', ['application_version', 'schema_version', 'build_time', 'supported_platform', 'known_release_limitations'])
def test_embedded_and_external_metadata_must_match(artifact, tmp_path, key):
    archive, manifest = artifact
    data = json.loads(manifest.read_text())
    data[key] = 'false-metadata'
    forged = tmp_path / 'manifest.json'
    forged.write_text(json.dumps(data))
    with pytest.raises(release.ReleaseError):
        release.inspect(archive, forged)


@pytest.mark.parametrize('key', ['access_token', 'refresh_token', 'password', 'client_secret', 'api_key'])
def test_json_credentials_rejected_without_logging_value(key):
    secret = 'synthetic-' + 'q' * 25
    with pytest.raises(release.ReleaseError) as rejected:
        release.scan('static_cockpit/example.json', json.dumps({key: secret}).encode())
    assert secret not in str(rejected.value)


def test_git_replacements_and_fsmonitor_cannot_change_provenance(candidate_repo, tmp_path):
    repo = tmp_path / 'repo'
    subprocess.run(['git', 'clone', '--no-hardlinks', str(candidate_repo), str(repo)], check=True, capture_output=True)
    original = (repo / 'README.md').read_bytes()
    blob = command(repo, 'rev-parse', 'HEAD:README.md')
    altered = subprocess.run(['git', '-C', str(repo), 'hash-object', '-w', '--stdin'],
        input=b'replacement contents', capture_output=True, check=True).stdout.decode().strip()
    command(repo, 'replace', blob, altered)
    marker = tmp_path / 'fsmonitor-called'
    hook = tmp_path / 'fsmonitor'
    hook.write_text('#!/bin/sh\ntouch ' + str(marker) + '\n')
    hook.chmod(0o700)
    command(repo, 'config', 'core.fsmonitor', str(hook))
    archive, manifest = release.build(repo, tmp_path / 'release')
    data = json.loads(manifest.read_text())
    assert data['files']['README.md']['sha256'] == hashlib.sha256(original).hexdigest()
    assert not marker.exists()
    assert release.inspect(archive, manifest)['verified']


def test_export_ignore_cannot_hide_tracked_secret(candidate_repo, tmp_path):
    repo = tmp_path / 'repo'
    subprocess.run(['git', 'clone', '--no-hardlinks', str(candidate_repo), str(repo)], check=True, capture_output=True)
    command(repo, 'config', 'user.name', 'Fixture')
    command(repo, 'config', 'user.email', 'fixture@example.invalid')
    (repo / '.gitattributes').write_text('excluded.txt export-ignore\n')
    (repo / 'excluded.txt').write_text('sk-' + 'Q' * 40)
    command(repo, 'add', '.')
    command(repo, 'commit', '-m', 'excluded sensitive fixture')
    with pytest.raises(release.ReleaseError, match='Secret scan'):
        release.build(repo, tmp_path / 'release')


def test_assume_unchanged_cannot_hide_dirty_tracked_source(candidate_repo, tmp_path):
    repo = tmp_path / 'repo'
    subprocess.run(['git', 'clone', '--no-hardlinks', str(candidate_repo), str(repo)], check=True, capture_output=True)
    command(repo, 'update-index', '--assume-unchanged', 'README.md')
    (repo / 'README.md').write_text('dirty content hidden from ordinary status')
    assert command(repo, 'status', '--porcelain') == ''
    with pytest.raises(release.ReleaseError, match='match exact HEAD'):
        release.build(repo, tmp_path / 'release')


def test_release_git_projects_minimal_environment(candidate_repo, monkeypatch):
    for key in ('OPENAI_API_KEY', 'OWNER_PRIVATE_VALUE', 'PYTHONPATH', 'NODE_OPTIONS',
                'GIT_DIR', 'GIT_CONFIG_PARAMETERS', 'DYLD_INSERT_LIBRARIES'):
        monkeypatch.setenv(key, 'inherited-sentinel')
    observed = []
    original = release.subprocess.run
    def capture(argv, **kwargs):
        observed.append(kwargs['env'])
        return original(argv, **kwargs)
    monkeypatch.setattr(release.subprocess, 'run', capture)
    assert release.git(candidate_repo, 'rev-parse', 'HEAD').strip()
    assert observed
    assert not any(value == 'inherited-sentinel' for value in observed[0].values())
    assert observed[0]['GIT_NO_REPLACE_OBJECTS'] == '1'
    assert observed[0]['GIT_CONFIG_GLOBAL'] == os.devnull


def test_current_version_surfaces_agree():
    import ast
    from scripts import twos_bootstrap
    from twos_runtime import __version__, codex_adapter, codex_connectivity
    assert __version__ == twos_bootstrap.APP_VERSION == '1.0.0'
    for module in (codex_adapter, codex_connectivity):
        assert module.__version__ == __version__
        tree = ast.parse(Path(module.__file__).read_text())
        clients = [value for node in ast.walk(tree) if isinstance(node, ast.Dict)
                   for key, value in zip(node.keys, node.values)
                   if isinstance(key, ast.Constant) and key.value == 'clientInfo']
        assert len(clients) == 1
        version = next(value for key, value in zip(clients[0].keys, clients[0].values)
                       if isinstance(key, ast.Constant) and key.value == 'version')
        assert isinstance(version, ast.Name) and version.id == '__version__'
    html = (ROOT / 'static_cockpit/vol12_static_mvp/twos_command_center.html').read_text()
    assert '<meta name="twos-version" content="1.0.0">' in html
    assert html.count('?v=1.0.0') == 2
    script = (ROOT / 'static_cockpit/vol12_static_mvp/twos_command_center.js').read_text()
    assert 'const UI_VERSION = "1.0.0";' in script


def test_historical_rc_still_builds_and_inspects(candidate_repo, tmp_path):
    repo = tmp_path / 'historical-source'
    subprocess.run(['git', 'clone', '--no-hardlinks', str(candidate_repo), str(repo)], check=True, capture_output=True)
    command(repo, 'config', 'user.name', 'Historical fixture')
    command(repo, 'config', 'user.email', 'fixture@example.invalid')
    version = repo / 'twos_runtime/__init__.py'
    version.write_text(version.read_text().replace('1.0.0', '0.17.0'))
    command(repo, 'add', 'twos_runtime/__init__.py')
    command(repo, 'commit', '-m', 'historical naming fixture')
    archive, manifest = release.build(repo, tmp_path / 'historical-output')
    assert archive.name == f"twos-0.17.0-rc19.4-{command(repo, 'rev-parse', 'HEAD')[:12]}.tar.gz"
    assert release.inspect(archive, manifest)['verified']


def test_archive_filename_must_match_internal_identity(artifact, tmp_path):
    archive, manifest = artifact
    renamed = tmp_path / 'unbound.tar.gz'
    renamed.write_bytes(archive.read_bytes())
    data = json.loads(manifest.read_text())
    data['artifact'] = renamed.name
    forged = tmp_path / 'manifest.json'
    forged.write_text(json.dumps(data))
    with pytest.raises(release.ReleaseError, match='identity'):
        release.inspect(renamed, forged)


def test_formal_release_receipt_requires_annotated_exact_commit(candidate_repo, tmp_path):
    repo = tmp_path / 'tagged'
    subprocess.run(['git', 'clone', '--no-hardlinks', str(candidate_repo), str(repo)], check=True, capture_output=True)
    command(repo, 'config', 'user.name', 'Release fixture')
    command(repo, 'config', 'user.email', 'release@example.invalid')
    archive, manifest = release.build(repo, tmp_path / 'formal')
    command(repo, 'tag', 'v1.0.0')
    with pytest.raises(release.ReleaseError, match='annotated'):
        release.release_receipt(repo, archive, manifest, tag='v1.0.0', release_date='2026-09-23')
    # This is a disposable unpublished test repository, not a product tag.
    command(repo, 'tag', '-d', 'v1.0.0')
    command(repo, 'tag', '-a', 'v1.0.0', '-m', 'Fixture release')
    receipt = release.release_receipt(repo, archive, manifest, tag='v1.0.0', release_date='2026-09-23')
    data = json.loads(receipt.read_bytes())['release']
    assert data['commit'] == command(repo, 'rev-parse', 'HEAD')
    assert data['sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert data['tag'] == 'v1.0.0'
    for line in (archive.parent/'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ')
        assert hashlib.sha256((archive.parent/name).read_bytes()).hexdigest() == digest
    with pytest.raises(release.ReleaseError, match='never overwrite'):
        release.release_receipt(repo, archive, manifest, tag='v1.0.0', release_date='2026-09-23')
    command(repo, 'commit', '--allow-empty', '-m', 'later fixture state')
    with pytest.raises(release.ReleaseError, match='same commit'):
        release.release_receipt(repo, archive, manifest, tag='v1.0.0', release_date='2026-09-23')
