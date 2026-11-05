"""Prepared input integrity, not evidence of App Sandbox or Store acceptance."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_macos
import stage_xcode_resources as stage


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    (root / 'packaging/macos').mkdir(parents=True)
    (root / 'packaging/macos/App.swift').write_text('production fixture')
    monkeypatch.setattr(stage, 'ROOT', root)
    monkeypatch.setattr(build_macos, 'source_inputs', lambda _: ['packaging/macos/App.swift'])
    app = tmp_path / 'Test.app'
    for name in ('Resources/engine/twos-service', 'Helpers/TWOS Nyra.app/Contents/MacOS/TWOSNyra'):
        path = app / 'Contents' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('TEST ONLY')
    hashes = {'packaging/macos/App.swift': hashlib.sha256(b'production fixture').hexdigest()}
    receipt = {'bundle_identifier': 'com.tianma.workos', 'input_hashes': hashes,
               'source_input_sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}
    record = app / 'Contents/Resources/source-provenance.json'
    record.write_text(json.dumps(receipt))
    return root, app, record, receipt


def test_matching_complete_input(prepared):
    _, app, _, receipt = prepared
    assert stage.verify_input(app) == receipt


def test_omitted_new_source_rejected(prepared, monkeypatch):
    _, app, _, _ = prepared
    monkeypatch.setattr(build_macos, 'source_inputs', lambda _: ['packaging/macos/App.swift', 'packaging/macos/New.swift'])
    with pytest.raises(ValueError, match='input set'):
        stage.verify_input(app)


def test_stale_source_rejected(prepared):
    root, app, _, _ = prepared
    (root / 'packaging/macos/App.swift').write_text('changed')
    with pytest.raises(ValueError, match='stale'):
        stage.verify_input(app)


def test_incomplete_product_rejected(prepared):
    _, app, _, _ = prepared
    (app / 'Contents/Helpers/TWOS Nyra.app/Contents/MacOS/TWOSNyra').unlink()
    with pytest.raises(ValueError, match='Both'):
        stage.verify_input(app)


def test_store_does_not_archive_unverified_runtime(prepared, monkeypatch):
    _, app, _, _ = prepared
    monkeypatch.setenv('TWOS_PREPARED_APP', str(app))
    monkeypatch.setenv('TWOS_DISTRIBUTION', 'store')
    with pytest.raises(ValueError, match='STORE_NOT_READY'):
        stage.main()
