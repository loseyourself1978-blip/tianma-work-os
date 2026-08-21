from pathlib import Path


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
    assert "elements.runStatus.textContent = run ? humanStatus(runStatus)" in javascript
    assert "elements.resultStatus.textContent = humanStatus(authoritativeStatus)" in javascript
    assert "elements.resultLifecycle.textContent = humanStatus(authoritativeStatus)" in javascript
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
        "Current Run state",
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
        "Sidecar evidence",
        "Result integrity",
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
