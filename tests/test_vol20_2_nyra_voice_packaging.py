"""The frozen source must include every pinned resource, including legal notices."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_source_preserves_all_pinned_nyra_resources():
    spec = importlib.util.spec_from_file_location('nyra_voice_builder', ROOT / 'scripts/build_macos.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    frozen = set(builder.source_inputs(ROOT))
    base = Path('packaging/macos/nyra/Resources')
    manifest = json.loads((ROOT / base / 'component-manifest.json').read_text())
    required = {(base / name).as_posix() for name in manifest['bundle_files']}
    assert required <= frozen, sorted(required - frozen)
    for name in ['LICENSE', 'LICENSE.cmudict', 'LICENSE.homograph-data']:
        assert (base / 'audio/tiny-voca-f2-en' / name).as_posix() in frozen
