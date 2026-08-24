import json
from pathlib import Path
from types import SimpleNamespace

from twos_runtime.app import terminal_truth_out


UI_ROOT = (
    Path(__file__).parents[1]
    / "static_cockpit"
    / "vol12_static_mvp"
)


def _sources() -> tuple[str, str, str]:
    return (
        (UI_ROOT / "twos_command_center.html").read_text(encoding="utf-8"),
        (UI_ROOT / "twos_command_center.js").read_text(encoding="utf-8"),
        (UI_ROOT / "styles.css").read_text(encoding="utf-8"),
    )


def test_live_codex_activity_uses_the_authoritative_lifecycle_snapshot() -> None:
    html, javascript, _ = _sources()

    assert '<h2 id="run-activity-title">Live Codex Activity</h2>' in html
    assert 'id="run-activity-list"' in html
    assert "function lifecycleRecordForActivity(record)" in javascript
    assert "const lifecycle = lifecycleRecordForActivity(record);" in javascript
    assert (
        "lifecycle.state || record.monitor_state || monitor.monitor_state"
        in javascript
    )
    assert "function authoritativeRunStatus(run)" in javascript
    assert '"verification_eligible"' in javascript
    assert "function mergeRunActivityLifecycleSnapshots(previous, incoming)" in javascript
    assert "nextVersion < priorVersion" in javascript
    assert (
        "state.runActivity = mergeRunActivityLifecycleSnapshots("
        in javascript
    )


def test_terminal_truth_separates_coding_verification_result_and_review() -> None:
    run = SimpleNamespace(
        status="failed", process_spawned=True, started_at="now", exit_code=0,
        verification_assignment_id=7, verification_status="not_started",
        structured_result='{"workspace_evidence": {"unexpected_files": ["x"]}}',
    )
    truth = terminal_truth_out(run, {
        "state": "failed", "result_integrity": "verified",
        "verification_started": False, "terminal_evidence_observed": True,
        "process_exited": True, "next_action": "Review evidence",
    }, {"integrity_state": "INVALID"})
    assert truth["coding"]["status"] == "succeeded"
    assert truth["verification"]["status"] == "unavailable"
    assert truth["result"]["integrity"] == "invalid"
    assert truth["workspace"]["state"] == "conflict"
    assert truth["primary_status"] == "needs_review"
    assert truth["primary_label"] == "Needs Review"


def test_terminal_truth_keeps_optional_verification_and_coding_failure_distinct() -> None:
    optional_run = SimpleNamespace(
        status="completed",
        process_spawned=True,
        started_at="now",
        exit_code=0,
        verification_assignment_id=None,
        verification_status="not_started",
        verification_summary=None,
        structured_result=json.dumps(
            {
                "workspace_evidence": {
                    "status": "captured",
                    "attribution": {"run_produced": []},
                }
            }
        ),
        acceptance_session=None,
    )
    optional_truth = terminal_truth_out(
        optional_run,
        {
            "state": "result_available",
            "result_integrity": "verified",
            "verification_started": False,
        },
        {"integrity_state": "verified"},
    )
    assert optional_truth["coding"]["status"] == "succeeded"
    assert optional_truth["verification"]["status"] == "not_required"
    assert optional_truth["primary_status"] == "result_available"

    failed_run = SimpleNamespace(
        status="failed",
        process_spawned=True,
        started_at="now",
        exit_code=9,
        verification_assignment_id=None,
        verification_status="not_started",
        verification_summary=None,
        structured_result="{}",
        acceptance_session=None,
    )
    failed_truth = terminal_truth_out(
        failed_run,
        {
            "state": "result_available",
            "result_integrity": "verified",
            "verification_started": False,
        },
        {"integrity_state": "verified"},
    )
    assert failed_truth["coding"]["status"] == "failed"
    assert failed_truth["result"]["state"] == "available"
    assert failed_truth["primary_status"] == "failed"
    assert failed_truth["primary_label"] == "Failed"


def test_terminal_truth_keeps_unavailable_workspace_evidence_incomplete() -> None:
    run = SimpleNamespace(
        status="completed",
        process_spawned=True,
        started_at="now",
        exit_code=0,
        verification_assignment_id=None,
        verification_status="not_started",
        verification_summary=None,
        structured_result="{}",
        acceptance_session=None,
    )
    truth = terminal_truth_out(
        run,
        {
            "state": "result_available",
            "result_integrity": "verified",
            "verification_started": False,
        },
        {
            "integrity_state": "verified",
            "advanced": {
                "workspace_evidence": {
                    "status": "unavailable",
                    "availability_reason": "Workspace evidence was not captured.",
                }
            },
        },
    )
    assert truth["workspace"]["state"] == "incomplete"
    assert truth["primary_status"] == "needs_review"


def test_terminal_truth_uses_phase_evidence_after_result_intake() -> None:
    run = SimpleNamespace(
        status="cancelled",
        process_spawned=True,
        started_at="now",
        exit_code=0,
        verification_assignment_id=9,
        verification_assignment=SimpleNamespace(independence_required=True),
        verification_status="cancelled",
        verification_summary="Owner cancelled Verification.",
        structured_result=json.dumps(
            {
                "coding_process": {"status": "completed", "exit_code": 0},
                "verification_process": {"status": "cancelled"},
            }
        ),
        acceptance_session=None,
    )
    truth = terminal_truth_out(
        run,
        {
            "state": "result_available",
            "result_integrity": "verified",
            "verification_started": True,
        },
        {
            "integrity_state": "verified",
            "verification_result": {"verdict": "NOT_REACHED"},
        },
    )
    assert truth["coding"]["status"] == "succeeded"
    assert truth["verification"]["status"] == "cancelled"
    assert truth["primary_status"] == "needs_review"


def test_terminal_truth_does_not_call_contradictory_coding_evidence_success() -> None:
    for exit_code, coding_process in (
        (7, {"status": "completed", "exit_code": 7}),
        (0, {"status": "failed", "exit_code": 0}),
        (9, {"status": "completed", "exit_code": 0}),
    ):
        run = SimpleNamespace(
            status="failed",
            process_spawned=True,
            started_at="now",
            exit_code=exit_code,
            verification_assignment_id=None,
            verification_status="not_started",
            verification_summary=None,
            structured_result=json.dumps({"coding_process": coding_process}),
            acceptance_session=None,
        )
        truth = terminal_truth_out(
            run,
            {
                "state": "result_available",
                "result_integrity": "verified",
                "verification_started": False,
            },
            {"integrity_state": "verified"},
        )
        assert truth["coding"]["status"] == "failed"
        assert truth["primary_status"] == "failed"

    interrupted_run = SimpleNamespace(
        status="blocked",
        process_spawned=True,
        started_at="now",
        exit_code=None,
        verification_assignment_id=None,
        verification_status="not_started",
        verification_summary=None,
        structured_result="{}",
        acceptance_session=None,
    )
    interrupted_truth = terminal_truth_out(
        interrupted_run,
        {"state": "process_lost", "result_integrity": "blocked"},
        None,
    )
    assert interrupted_truth["coding"]["status"] == "interrupted"
    assert interrupted_truth["primary_status"] == "interrupted"


def test_terminal_truth_does_not_trust_invalid_envelope_verification_verdict() -> None:
    run = SimpleNamespace(
        status="failed",
        process_spawned=True,
        started_at="now",
        exit_code=0,
        verification_assignment_id=8,
        verification_assignment=SimpleNamespace(independence_required=True),
        verification_process_spawned=True,
        verification_status="failed",
        verification_summary="Independent Verification failed.",
        structured_result=json.dumps(
            {
                "coding_process": {"status": "completed", "exit_code": 0},
                "verification_process": {"status": "failed"},
            }
        ),
        acceptance_session=None,
    )
    truth = terminal_truth_out(
        run,
        {
            "state": "result_available",
            "result_integrity": "blocked",
            "verification_started": True,
        },
        {
            "integrity_state": "blocked",
            "verification_result": {"verdict": "PASS"},
        },
    )
    assert truth["verification"]["status"] == "failed"
    assert truth["primary_status"] == "needs_review"


def test_terminal_truth_does_not_inherit_legacy_failed_after_all_phases_pass() -> None:
    run = SimpleNamespace(
        status="failed",
        process_spawned=True,
        started_at="now",
        exit_code=0,
        verification_assignment_id=8,
        verification_process_spawned=True,
        verification_status="completed",
        verification_summary="Independent Verification passed.",
        structured_result=json.dumps(
            {
                "coding_process": {"status": "completed", "exit_code": 0},
                "verification_process": {"status": "completed"},
            }
        ),
        acceptance_session=None,
    )
    truth = terminal_truth_out(
        run,
        {
            "state": "failed",
            "result_integrity": "verified",
            "verification_started": True,
        },
        {
            "integrity_state": "verified",
            "verification_result": {"verdict": "PASS"},
            "advanced": {
                "workspace_evidence": {
                    "status": "captured",
                    "attribution": {"run_produced": ["codex_target.txt"]},
                }
            },
        },
    )

    assert truth["coding"]["status"] == "succeeded"
    assert truth["verification"]["status"] == "passed"
    assert truth["result"]["state"] == "available"
    assert truth["workspace"]["state"] == "captured"
    assert truth["primary_status"] == "result_available"


def test_terminal_truth_preserves_explicit_workspace_conflict_status() -> None:
    run = SimpleNamespace(
        status="completed",
        process_spawned=True,
        started_at="now",
        exit_code=0,
        verification_assignment_id=None,
        verification_status="not_started",
        verification_summary=None,
        structured_result="{}",
        acceptance_session=None,
    )
    truth = terminal_truth_out(
        run,
        {"state": "result_available", "result_integrity": "verified"},
        {
            "integrity_state": "verified",
            "advanced": {
                "workspace_evidence": {
                    "status": "conflict",
                    "conflict_reason": "The planned workspace baseline changed.",
                }
            },
        },
    )

    assert truth["workspace"]["state"] == "conflict"
    assert truth["workspace"]["conflict_reasons"] == [
        "The planned workspace baseline changed."
    ]
    assert truth["primary_status"] == "needs_review"


def test_terminal_truth_ui_uses_primary_label_for_terminal_badges_and_keeps_live_state() -> None:
    _, javascript, styles = _sources()
    assert "primary_label" in javascript
    assert "lifecycleIsActive(view.status) ? humanStatus(view.status) : view.primaryLabel" in javascript
    assert "Coding completed; independent Verification was not started" in javascript
    assert "@media" in styles
    assert "elements.runStatus.textContent = run" in javascript
    assert "runTerminalTruth.primary_label || humanStatus" in javascript
    assert "humanStatus(run.canonical_status || runStatus)" in javascript
    assert "record.completion_classification" in javascript
    assert "const primaryLabel = terminalTruth.primary_label || humanStatus(authoritativeStatus);" in javascript
    assert "elements.resultStatus.textContent = lifecycleIsActive(authoritativeStatus)" in javascript
    assert "elements.resultLifecycle.textContent = humanStatus(authoritativeStatus)" in javascript
    assert "availability does not by itself establish objective success" in javascript
    assert "Verified evidence envelope — independent Verification is shown separately" in javascript
    assert "activity\n        ? activity.status" in javascript
    assert "Pending authoritative lifecycle settlement" in javascript
    assert (
        "!lifecycleIsActive(view.status) && resultEnvelopeIsValid(view.envelope)"
        in javascript
    )
    assert (
        "const valid = resultEnvelopeIsValid(record) && !lifecycleActive && !lifecycleBlocked;"
        in javascript
    )
    assert "!(activity && lifecycleIsActive(activity.status))" in javascript

    for label in (
        "Run outcome",
        "Coding outcome",
        "Independent Verification",
        "Result availability",
        "Workspace evidence",
        "Evidence envelope integrity",
        "Owner warning",
        "Current execution state",
        "Coding / Verification phase",
        "Current observable activity",
        "Run started at",
        "Current elapsed time",
        "Coding elapsed time",
        "Verification elapsed time",
        "Result-settlement elapsed time",
        "Last observable activity at",
        "Time since last activity",
        "Process live",
        "Monitor attached",
        "Coding started",
        "Process exited",
        "Verification started",
        "Terminal evidence observed",
        "Latest safe event summary",
        "Blocker code",
        "Event count",
        "Exact next Owner action",
        "Safe activity timeline",
    ):
        assert f'"{label}"' in javascript

    # Elapsed and inactivity values are rendered from the server snapshot. The
    # lifecycle presentation must never invent progress from a browser clock.
    assert "formatLifecycleDuration(lifecycle.elapsed_ms)" in javascript
    assert "formatLifecycleDuration(lifecycle.coding_elapsed_ms)" in javascript
    assert "formatLifecycleDuration(lifecycle.verification_elapsed_ms)" in javascript
    assert "lifecycle.result_settlement_elapsed_ms" in javascript
    assert "lifecycle.settlement_elapsed_ms" in javascript
    assert "formatLifecycleDuration(lifecycle.inactivity_ms)" in javascript
    assert "Date.now()" not in javascript


def test_terminal_integrity_blocked_is_never_presented_as_active_or_available() -> None:
    html, javascript, _ = _sources()

    assert "<dt>Readiness for a new Run</dt>" in html
    assert "<dt>New Run readiness reason</dt>" in html
    assert (
        'id="cancel-codex" class="button button-secondary" type="button" hidden'
        in html
    )
    assert "function activityResultIsBlocked(view)" in javascript
    assert "function activityResultIsAvailable(view)" in javascript
    assert "if (view.lifecycleAvailable)" in javascript
    assert "lifecycle.result_integrity" in javascript
    assert "const lifecycleBlocked = Boolean(" in javascript
    assert "&& !lifecycleBlocked" in javascript
    assert 'elements.cancelCodex.hidden = !activeRun;' in javascript
    assert '"No active Run"' not in javascript

    # The newest authoritative blocker wins over a valid failure envelope or
    # any older available result, both in the badge and notification.
    assert javascript.index(': blocked.length') < javascript.index(': available.length')
    assert javascript.index("if (headline && activityResultIsBlocked(headline))") < javascript.index(
        "else if (headline && activityResultIsAvailable(headline))"
    )
    assert '"Result integrity blocked"' in javascript


def test_terminal_run_keeps_new_run_readiness_separate_from_owner_action() -> None:
    _, javascript, _ = _sources()

    assert 'blockerCode === "ACTIVE_RUN_EXISTS"' in javascript
    assert 'status = "Recheck required";' in javascript
    assert (
        'reason = "The current Run is terminal. Refresh readiness before starting a new Run.";'
        in javascript
    )
    assert "const lifecycleNextAction = runLifecycle.next_action" in javascript
    assert "terminal && lifecycleNextAction" in javascript
    lifecycle_start = javascript.index("const lifecycleNextAction = runLifecycle.next_action")
    lifecycle_end = javascript.index("elements.codexReadiness.textContent", lifecycle_start)
    lifecycle_block = javascript[lifecycle_start:lifecycle_end]
    assert '"Review blocker evidence"' in lifecycle_block
    assert '"Review blocker evidence."' not in lifecycle_block
    assert "activity && activity.nextAction\n      ||" in javascript


def test_terminal_cancel_visibility_and_owner_action_remain_responsive() -> None:
    _, javascript, css = _sources()

    assert "[hidden] {\n  display: none !important;\n}" in css
    assert "@media (max-width: 760px)" in css
    assert "@media (max-width: 420px)" in css
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert "overflow-wrap: anywhere" in css
    assert "appendRunActivityFact(facts, \"Exact next Owner action\", view.nextAction);" in javascript


def test_source_snapshot_prelaunch_blocker_disables_result_recovery_controls() -> None:
    _, javascript, _ = _sources()

    assert "recoveryBlocked: actions.recovery_blocked === true" in javascript
    assert "const recoveryBlocked = Boolean(current && current.recoveryBlocked);" in javascript
    assert "const reconnectable = hasRun && !recoveryBlocked" in javascript
    assert "const importable = hasRun && !recoveryBlocked" in javascript
    assert (
        "Source snapshot unavailable. Regenerate Codex Pack; result import and reconnect "
        "are not valid for a Run that never launched."
        in javascript
    )


def test_live_codex_activity_is_bounded_private_and_advanced_is_collapsed() -> None:
    _, javascript, _ = _sources()

    assert "source.slice(-12).map(lifecycleEventView)" in javascript
    assert 'return "Codex is reasoning";' in javascript
    assert (
        "event.safe_summary || event.current_activity || event.activity || event.label || type"
        in javascript
    )
    assert "event.message" not in javascript
    assert "event.reasoning" not in javascript
    assert "event.analysis" not in javascript
    assert "event.repository_relative_path || event.repository_path" in javascript
    assert 'document.createElement("details")' in javascript
    assert 'advancedSummary.textContent = "Advanced"' in javascript
    assert "advanced.open" not in javascript

    for label in (
        "Lifecycle snapshot version",
        "Execution attempt",
        "Monitor",
        "Execution",
        "Process-start identity",
        "Terminal-event identity",
        "Receipt digest",
        "Stream offsets",
        "Event histogram",
        "Result sidecar",
        "Exit code",
        "Reconciliation version",
    ):
        assert f'"{label}"' in javascript

    # Advanced rendering uses an explicit field allowlist. It cannot serialize
    # raw commands, paths, credentials, environment values, or model reasoning.
    for unsafe_access in (
        "advanced.path",
        "advanced.command",
        "advanced.argv",
        "advanced.environment",
        "advanced.credentials",
        "advanced.reasoning",
        "JSON.stringify(advanced)",
    ):
        assert unsafe_access not in javascript


def test_live_codex_activity_layout_is_responsive_and_never_triggers_delivery() -> None:
    html, javascript, css = _sources()

    for selector in (
        ".run-activity-item-open",
        ".live-codex-activity",
        ".live-codex-facts",
        ".live-codex-timeline",
        ".live-codex-advanced",
        ".live-codex-advanced-facts",
    ):
        assert selector in css
    assert "min-width: 0" in css
    assert "overflow-wrap: anywhere" in css
    assert "@media (max-width: 760px)" in css
    assert "@media (max-width: 420px)" in css
    assert (
        ".run-activity-item-grid,\n  .live-codex-facts,\n  .live-codex-advanced-facts"
        in css
    )

    combined = html + javascript
    assert "Verify Applied Changes" in combined
    activity_renderer = javascript.split(
        "function renderRunActivity()",
        1,
    )[1].split("function appendTextList", 1)[0]
    activity_selection = javascript.split(
        "function selectRunActivity",
        1,
    )[1].split("function activityResultIsBlocked", 1)[0]
    for activity_path in (activity_renderer, activity_selection):
        assert '"/push-preflights"' not in activity_path
        assert '"/push-attempts"' not in activity_path
        assert "confirmPushToOriginMain" not in activity_path
