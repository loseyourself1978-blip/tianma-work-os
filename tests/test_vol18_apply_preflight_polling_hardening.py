from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import twos_runtime.codex_adapter as codex_adapter_module
import twos_runtime.self_hosting as self_hosting_module
import twos_runtime.apply_sessions as apply_session_service
from tests.test_vol18_apply_revert import _apply, phase18b_fixture
from twos_runtime.codex_adapter import CodexAdapter


def test_codex_status_source_state_uses_hardened_read_only_git(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, dict[str, Any]]] = []

    def fake_git_source_state(repo: Path, **kwargs: Any) -> dict[str, object]:
        calls.append((repo, kwargs))
        return {
            "repo": repo,
            "identity": repo.name,
            "branch": "main",
            "commit": "a" * 40,
            "clean": True,
            "status": "",
        }

    monkeypatch.setattr(
        codex_adapter_module,
        "git_source_state",
        fake_git_source_state,
    )
    source_repo = tmp_path / "fixture-repo"
    adapter = CodexAdapter(SimpleNamespace(source_repo=source_repo))  # type: ignore[arg-type]

    assert adapter.source_state()["clean"] is True
    assert calls == [(source_repo, {"hardened_read_only": True})]


def test_pack_binding_and_run_eligibility_use_hardened_snapshot_capture(
    monkeypatch,
    tmp_path: Path,
) -> None:
    development_task = "Stable Phase 18.4A acceptance fixture"
    routing = {
        "assignments": [{"capability": "coding"}],
        "assignment_version": 1,
        "routing_snapshot_hash": "b" * 64,
        "provider_state_hash": "c" * 64,
    }
    approved_snapshot: dict[str, Any] = {
        "schema": self_hosting_module.SOURCE_SNAPSHOT_SCHEMA,
        "head_sha": "a" * 40,
        "source_branch": "main",
        "source_repository_identity_method": (
            self_hosting_module.SOURCE_REPOSITORY_IDENTITY_METHOD
        ),
        "source_repository_identity": "d" * 64,
        "staged_patch_b64": "",
        "unstaged_patch_b64": "",
        "untracked_files": [],
        "included_manifest": [],
        "excluded_manifest": [],
    }
    approved_snapshot["digest"] = self_hosting_module._source_snapshot_digest(
        approved_snapshot
    )
    task = SimpleNamespace(
        id=7,
        task_version=1,
        development_task=development_task,
    )
    pack = SimpleNamespace(
        task_id=task.id,
        task_version=task.task_version,
        development_task=development_task,
        development_task_digest=self_hosting_module.development_task_digest(
            development_task
        ),
        assignment_version=routing["assignment_version"],
        routing_snapshot_hash=routing["routing_snapshot_hash"],
        generation_metadata=json.dumps(
            {"provider_state_hash": routing["provider_state_hash"]}
        ),
        source_snapshot_json=json.dumps(approved_snapshot),
        source_snapshot_digest=approved_snapshot["digest"],
    )
    capture_calls: list[tuple[Path, dict[str, Any]]] = []

    monkeypatch.setattr(
        self_hosting_module,
        "model_routing_snapshot",
        lambda _session, _task_id: routing,
    )

    def fake_capture(repo: Path, **kwargs: Any) -> dict[str, Any]:
        capture_calls.append((repo, kwargs))
        return dict(approved_snapshot)

    monkeypatch.setattr(
        self_hosting_module,
        "capture_source_snapshot",
        fake_capture,
    )
    source_repo = tmp_path / "fixture-repo"

    assert (
        self_hosting_module.pack_routing_binding_error(
            object(),
            task,
            pack,
            source_repo,
        )
        is None
    )
    assert capture_calls == [(source_repo, {"hardened_read_only": True})]


def test_run_eligibility_revalidates_pack_through_hardened_binding_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    task = SimpleNamespace(id=11)
    pack = SimpleNamespace(
        id=13,
        version=1,
        source_snapshot_digest="a" * 64,
        source_snapshot_json="{}",
        status="approved",
        invalidated_at=None,
    )
    scalar_results = iter((pack, None))
    session = SimpleNamespace(
        scalar=lambda _statement: next(scalar_results),
        scalars=lambda _statement: (),
    )
    calls: list[tuple[object, object, object, Path]] = []

    monkeypatch.setattr(
        self_hosting_module,
        "latest_model_assignments",
        lambda _session, _task_id: [],
    )

    def fake_binding_error(
        observed_session: object,
        observed_task: object,
        observed_pack: object,
        source_repo: Path,
    ) -> None:
        calls.append(
            (observed_session, observed_task, observed_pack, source_repo)
        )
        return None

    monkeypatch.setattr(
        self_hosting_module,
        "pack_routing_binding_error",
        fake_binding_error,
    )
    source_repo = tmp_path / "fixture-repo"

    self_hosting_module.run_eligibility(session, task, source_repo)

    assert calls == [(session, task, pack, source_repo)]


def test_concurrent_status_poll_during_protected_apply_preserves_index_and_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Real status endpoints may overlap preflight but remain Git-read-only."""
    with phase18b_fixture(tmp_path) as fixture:
        index_path = fixture.source_repo / ".git" / "index"
        baseline_index = index_path.read_bytes()
        poll_start = threading.Event()
        poll_finished = threading.Event()
        poll_errors: list[BaseException] = []
        poll_statuses: list[int] = []
        poll_index_samples: list[bytes] = []

        def poll_status_endpoints() -> None:
            try:
                if not poll_start.wait(timeout=10):
                    raise AssertionError("Apply preflight did not start")
                poll_index_samples.append(index_path.read_bytes())
                poll_statuses.append(
                    fixture.client.get("/api/codex/status").status_code
                )
                poll_statuses.append(
                    fixture.client.get(
                        f"/api/tasks/{fixture.candidate.task_id}/run-eligibility"
                    ).status_code
                )
                poll_index_samples.append(index_path.read_bytes())
            except BaseException as exc:  # pragma: no cover - asserted below
                poll_errors.append(exc)
            finally:
                poll_finished.set()

        original_global_evidence = apply_session_service._global_evidence
        observation_calls = 0

        def observe_while_polling(*args, **kwargs):
            nonlocal observation_calls
            observation_calls += 1
            if observation_calls == 1:
                poll_start.set()
                assert poll_finished.wait(timeout=10), (
                    "status polling did not complete inside protected preflight"
                )
            return original_global_evidence(*args, **kwargs)

        monkeypatch.setattr(
            apply_session_service,
            "_global_evidence",
            observe_while_polling,
        )
        worker = threading.Thread(target=poll_status_endpoints, daemon=True)
        worker.start()

        result, created = _apply(fixture)
        worker.join(timeout=10)

        assert not worker.is_alive()
        assert poll_errors == []
        assert poll_statuses == [200, 200]
        assert poll_index_samples == [baseline_index, baseline_index]
        assert index_path.read_bytes() == baseline_index
        assert observation_calls >= 3
        assert created is True
        assert result["state"] == "APPLIED"
        assert not any(
            blocker.get("code") == "REPOSITORY_CHANGED_DURING_PREFLIGHT"
            for blocker in result["blockers"]
        )
