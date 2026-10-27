"""Release ordering and Apple's acceptance gate; no credentials or network."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location(
    "joint_release_signing", Path(__file__).parents[1] / "scripts/sign_macos.py")
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


def test_nested_nyra_and_framework_sealed_before_outer(tmp_path):
    app = tmp_path / "TWOS.app"
    helper = app / "Contents/Helpers/Nyra.app"
    framework = helper / "Contents/Frameworks/Example.framework"
    library = framework / "Versions/A/Example"
    binary = helper / "Contents/MacOS/Nyra"
    for path in [library, binary]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xcf\xfa\xed\xfe" + b"TEST FIXTURE")
    (framework / "Example").symlink_to("Versions/A/Example")
    targets = signing.signing_targets(app)
    assert targets.index(library) < targets.index(framework) < targets.index(helper) < targets.index(app)
    assert targets.index(binary) < targets.index(helper)
    assert framework / "Example" not in targets
    assert len(targets) == len(set(targets))


@pytest.mark.parametrize("status", ["Invalid", "Rejected", "In Progress"])
def test_nonaccepted_notary_response_is_preserved_and_stops(monkeypatch, tmp_path, status):
    response = {"id": "TEST-SUBMISSION", "status": status}
    monkeypatch.setattr(signing.subprocess, "run", lambda *a, **kw:
        SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr=""))
    receipt = tmp_path / "notarization.json"
    with pytest.raises(RuntimeError, match="not Accepted"):
        signing.notarize(tmp_path / "fixture.zip", "TEST-PROFILE", receipt)
    assert json.loads(receipt.read_text()) == response


def test_accepted_notary_response_returns_actual_submission(monkeypatch, tmp_path):
    response = {"id": "TEST-ACCEPTED-ID", "status": "Accepted"}
    monkeypatch.setattr(signing.subprocess, "run", lambda *a, **kw:
        SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr=""))
    assert signing.notarize(tmp_path / "fixture.zip", "TEST-PROFILE", tmp_path / "receipt.json") == response
