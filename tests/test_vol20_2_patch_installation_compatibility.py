"""Synthetic retained installation: a schema-identical patch must not reset it."""
import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from scripts import twos_bootstrap as bootstrap
from twos_runtime import INSTALLATION_COMPATIBLE_VERSIONS, desktop
from twos_runtime.app import create_app
from twos_runtime.models import Installation
from tests.test_vol19_fresh_install_first_run import fresh_settings


@pytest.mark.parametrize("version", ["1.0.1", "1.0.2"])
def test_source_launcher_retains_compatible_binding_without_writes(tmp_path, version):
    data, runtime, logs = [tmp_path / x for x in ("data", "runtime", "logs")]
    data.mkdir()
    config, _ = bootstrap.initial_installation(data, runtime, logs, None)
    config["source_version"] = version
    bootstrap.atomic_private_json(data / "installation.json", config)
    before = (data / "installation.json").read_bytes()
    (data / "twos.sqlite3").write_bytes(b"TEST/FIXTURE existing data, not opened by this check")
    restored, fresh = bootstrap.initial_installation(data, runtime, logs, None)
    assert not fresh and restored == config
    assert (data / "installation.json").read_bytes() == before
    assert (data / "twos.sqlite3").read_bytes().startswith(b"TEST/FIXTURE")
    assert INSTALLATION_COMPATIBLE_VERSIONS == bootstrap.INSTALLATION_COMPATIBLE_VERSIONS


def test_desktop_patch_retains_identity_and_rejects_invalid_version(tmp_path):
    data, runtime, logs = [tmp_path / x for x in ("data", "runtime", "logs")]
    data.mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        config = desktop.installation(data, runtime, logs, sock)
        config["source_version"] = "1.0.1"
        bootstrap.atomic_private_json(data / "installation.json", config)
        before = (data / "installation.json").read_bytes()
        assert desktop.installation(data, runtime, logs, sock) == config
        assert (data / "installation.json").read_bytes() == before
        for invalid in ("0.17.0", "99.0.0", [], None):
            config["source_version"] = invalid
            bootstrap.atomic_private_json(data / "installation.json", config)
            unchanged = (data / "installation.json").read_bytes()
            with pytest.raises(bootstrap.BootstrapError, match="DESKTOP_INSTALLATION_MISMATCH"):
                desktop.installation(data, runtime, logs, sock)
            assert (data / "installation.json").read_bytes() == unchanged


def test_retained_database_version_and_identity_are_not_rewritten(tmp_path):
    settings = fresh_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app):
        with app.state.session_factory() as session:
            installation = session.scalar(select(Installation))
            installation.source_version = "1.0.1"
            public_id = installation.public_id
            state = installation.first_run_state
            session.commit()
    config_path = settings.installation_config_path
    config = json.loads(config_path.read_text())
    config["source_version"] = "1.0.1"
    bootstrap.atomic_private_json(config_path, config)
    restarted = create_app(settings)
    with TestClient(restarted) as client:
        assert client.get("/api/health").json()["version"] == "1.0.2"
        with restarted.state.session_factory() as session:
            rows = session.scalars(select(Installation)).all()
            assert len(rows) == 1
            assert (rows[0].public_id, rows[0].source_version, rows[0].first_run_state) == (public_id, "1.0.1", state)
    assert json.loads(config_path.read_text())["source_version"] == "1.0.1"
