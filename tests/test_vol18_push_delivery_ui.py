from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static_cockpit" / "vol12_static_mvp"
HTML = STATIC / "twos_command_center.html"
SCRIPT = STATIC / "twos_command_center.js"
STYLES = STATIC / "styles.css"


def static_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def function_slice(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_push_delivery_default_controls_and_owner_facts_are_explicit() -> None:
    page = static_source(HTML)

    for selector in (
        "push-delivery-section",
        "push-to-origin-main",
        "view-delivery-result",
        "push-gate-status",
        "push-local-commit",
        "push-commit-subject",
        "push-destination",
        "push-remote-base",
        "push-ahead-behind",
        "push-cleanliness",
        "push-next-action",
        "push-blockers",
    ):
        assert f'id="{selector}"' in page
    assert ">Push to origin/main<" in page
    assert ">View Delivery Result<" in page
    assert "No Push occurs on page load, refresh, preflight review" in page
    assert "one standard fast-forward attempt only" in page


def test_push_confirmation_is_separate_complete_and_cancel_focused() -> None:
    page = static_source(HTML)
    script = static_source(SCRIPT)

    for selector in (
        "push-confirmation-dialog",
        "push-confirmation-repository",
        "push-confirmation-branch",
        "push-confirmation-commit",
        "push-confirmation-subject",
        "push-confirmation-remote-base",
        "push-confirmation-destination",
        "push-confirmation-ahead-behind",
        "push-confirmation-cleanliness",
        "push-confirmation-fast-forward",
        "confirm-push-to-origin-main",
        "cancel-push-to-origin-main",
    ):
        assert f'id="{selector}"' in page
    assert ">Confirm Push to origin/main<" in page
    assert "No force, force-with-lease, tag, other branch" in page
    assert "No automatic retry, Fetch, Pull, Merge, or Rebase" in page
    assert "elements.cancelPushToOriginMain.focus()" in script


def test_preflight_and_confirm_use_the_exact_separate_api_contract() -> None:
    script = static_source(SCRIPT)
    preflight = function_slice(
        script,
        "async function openPushConfirmation",
        "async function confirmPushToOriginMain",
    )
    confirm = function_slice(
        script,
        "async function confirmPushToOriginMain",
        "async function viewDeliveryResult",
    )
    assert '"/push-preflights"' in preflight
    assert 'method: "POST"' in preflight
    assert "body:" not in preflight
    assert '"/push-attempts"' not in preflight
    assert "PUSH_TO_ORIGIN_MAIN" not in preflight

    assert '"/push-attempts"' in confirm
    assert 'method: "POST"' in confirm
    assert 'confirmation: "PUSH_TO_ORIGIN_MAIN"' in confirm
    assert "expected_confirmation_digest: context.confirmation_digest" in confirm
    assert '"/api/push-preflights/"' in confirm
    body = confirm.split("body:", 1)[1].split("}", 1)[0]
    assert "local_commit_sha" not in body
    assert "remote_base" not in body
    assert "destination" not in body
    assert "refspec" not in body


def test_page_load_refresh_and_delivery_review_are_read_only() -> None:
    script = static_source(SCRIPT)
    loader = function_slice(
        script,
        "async function loadPushDelivery",
        "function currentLegacyRun",
    )
    view_result = function_slice(
        script,
        "async function viewDeliveryResult",
        "async function confirmStageApprovedFiles",
    )

    assert '"/push-delivery"' in loader
    assert 'method: "POST"' not in loader
    assert "/push-attempts" not in loader
    assert "await loadPushDelivery(run, true)" in view_result
    assert 'method: "POST"' not in view_result
    assert "/push-preflights" not in view_result
    assert "/push-attempts" not in view_result
    assert "setInterval(openPushConfirmation" not in script
    assert "setTimeout(openPushConfirmation" not in script
    assert "setInterval(confirmPushToOriginMain" not in script
    assert "setTimeout(confirmPushToOriginMain" not in script


def test_push_ui_uses_server_actions_and_terminal_states() -> None:
    script = static_source(SCRIPT)
    rendering = function_slice(
        script,
        "function renderPushDelivery(run)",
        "function confirmationListText",
    )

    for state in (
        "READY_TO_PUSH",
        "PUSHING",
        "PUSHED",
        "PUSH_BLOCKED",
        "REMOTE_MOVED",
        "PUSH_FAILED",
        "RECONCILIATION_BLOCKED",
    ):
        assert state in script
    assert "const canPush = parts.actions.can_push_to_origin_main === true" in rendering
    assert "const canView = parts.actions.can_view_delivery_result === true" in rendering
    assert "const currentBoundary = pushCurrentBoundary(parts)" in rendering
    assert "pushAheadBehind(currentBoundary)" in rendering
    assert "pushCleanliness(currentBoundary)" in rendering
    assert "elements.pushToOriginMain.disabled = !canPush" in rendering
    assert "elements.viewDeliveryResult.disabled = !canView" in rendering
    assert "PUSH_DELIVERY_STATE_LABELS[stateValue] || parts.readiness.status_label" in rendering
    assert "const canPush = parts.readiness.status_label" not in rendering
    assert "const canView = parts.result.status_label" not in rendering


def test_push_summary_uses_live_reconciliation_and_never_renders_null_as_dirty() -> None:
    script = static_source(SCRIPT)
    boundary = function_slice(
        script,
        "function pushCurrentBoundary(parts)",
        "function pushDeliveryState(parts)",
    )
    ahead_behind = function_slice(
        script,
        "function pushAheadBehind(value)",
        "function pushCleanliness(value)",
    )
    cleanliness = function_slice(
        script,
        "function pushCleanliness(value)",
        "function pushCurrentBoundary(parts)",
    )

    assert "parts.result.reconciliation" in boundary
    assert '"ahead", "behind", "worktree_clean", "index_clean", "staged_path_count"' in boundary
    assert "reconciliation[key] !== null" in boundary
    assert "ahead === null" in ahead_behind
    assert "behind === null" in ahead_behind
    assert "record.worktree_clean === null" in cleanliness
    assert "record.index_clean === null" in cleanliness
    assert "record.staged_path_count === null" in cleanliness


def test_push_requests_have_task_commit_and_sequence_stale_guards() -> None:
    script = static_source(SCRIPT)
    loader = function_slice(
        script,
        "async function loadPushDelivery",
        "function currentLegacyRun",
    )
    store = function_slice(
        script,
        "function storePushDeliveryReview",
        "async function reviewCommitPlan",
    )
    preflight = function_slice(
        script,
        "async function openPushConfirmation",
        "async function confirmPushToOriginMain",
    )
    confirm = function_slice(
        script,
        "async function confirmPushToOriginMain",
        "async function viewDeliveryResult",
    )
    rendering = function_slice(
        script,
        "  function renderPushDelivery(run) {",
        "\n  function confirmationListText",
    )

    assert "pushDeliveryRequestSequences" in loader
    assert "requestEpoch !== state.taskSelectionEpoch" in loader
    assert "state.pushDeliveryRequestSequences[key] !== requestSequence" in loader
    assert "pushDeliveryReviewBinding(review) !== key" in loader
    assert "state.pushDeliveryRequestSequences[key]" in store
    assert "selectionEpoch !== state.taskSelectionEpoch" in preflight
    assert "STALE_PUSH_PREFLIGHT_RESPONSE" in preflight
    assert "context.task_selection_epoch !== state.taskSelectionEpoch" in confirm
    assert "STALE_PUSH_RESULT_RESPONSE" in confirm
    assert "confirmationStillCurrent" in rendering
    assert "state.pushConfirmationContext = null" in rendering
    assert "elements.pushConfirmationDialog.close()" in rendering
    assert "freshReadinessBlocked" in rendering
    assert "freshReadinessBlocked ? parts.readiness.next_action" in rendering


def test_api_and_remote_movement_failures_remain_visible() -> None:
    script = static_source(SCRIPT)

    assert "PUSH_DELIVERY_LOAD_FAILED" in script
    assert "PUSH_REQUEST_FAILED" in script
    assert "Push readiness could not be loaded" in script
    assert "Push result could not be confirmed" in script
    assert 'action_state: uncertain ? "RECONCILIATION_BLOCKED" : "PUSH_BLOCKED"' in script
    assert "pushDeliveryBlockers(parts)[0]" in script
    assert "REMOTE_MOVED" in script


def test_delivery_result_covers_the_complete_chain_and_reconciliation() -> None:
    page = static_source(HTML)
    script = static_source(SCRIPT)
    assert "record.outcome_label || record.terminal_status" in script

    for selector in (
        "delivery-result",
        "delivery-result-status",
        "delivery-run-result",
        "delivery-independent-verification",
        "delivery-candidate",
        "delivery-source-drift",
        "delivery-apply-result",
        "delivery-post-apply-verification",
        "delivery-staged-paths",
        "delivery-local-commit",
        "delivery-commit-subject",
        "delivery-push-status",
        "delivery-reconciliation",
        "delivery-local-head",
        "delivery-origin-main",
        "delivery-ahead-behind",
        "delivery-worktree-index",
        "delivery-boundaries",
        "delivery-warnings",
        "delivery-blockers",
        "delivery-next-action",
    ):
        assert f'id="{selector}"' in page
    assert "Local HEAD = origin/main = approved commit." in script
    assert "Number(reconciliation.ahead) === 0" in script
    assert "Number(reconciliation.behind) === 0" in script
    assert "state.pushDeliveryResultVisible" in script


def test_internal_push_evidence_is_advanced_only() -> None:
    page = static_source(HTML)
    default_section = page.split(
        '<section id="push-delivery-section"', 1
    )[1].split('<section id="result-intake-summary"', 1)[0]
    advanced = page.split(
        '<section id="push-delivery-advanced-card"', 1
    )[1].split('<section class="advanced-card"', 1)[0]

    for selector in (
        "push-preflight-digest",
        "push-attempt-digest",
        "push-exact-refspec",
        "push-remote-fingerprint",
        "push-repository-fingerprint",
        "push-candidate-binding",
        "push-apply-plan-binding",
        "push-verification-binding",
    ):
        assert selector not in default_section
        assert f'id="{selector}"' in advanced
    assert "Sanitized Push diagnostics" in advanced
    assert "remote_url" not in default_section
    assert "absolute_path" not in default_section


def test_push_and_delivery_controls_are_understandable_at_mobile_widths() -> None:
    styles = static_source(STYLES)

    assert ".push-delivery-heading" in styles
    assert ".delivery-result-evidence-grid" in styles
    assert ".push-delivery-controls .button" in styles
    assert "@media (max-width: 760px)" in styles
    assert "@media (max-width: 420px)" in styles
    mobile = styles.split("@media (max-width: 420px)", 1)[1]
    assert ".confirmation-dialog" in mobile
    assert ".confirmation-actions" in mobile
    assert ".push-delivery-controls .button" in mobile
    assert "width: 100%" in mobile
    assert "overflow-wrap: anywhere" in styles


def test_phase18_4a_handlers_remain_separate_from_push_delivery() -> None:
    script = static_source(SCRIPT)
    actions = (
        function_slice(
            script,
            "async function reviewCommitPlan",
            "async function openPushConfirmation",
        ),
        function_slice(
            script,
            "async function confirmStageApprovedFiles",
            "async function confirmCreateLocalCommit",
        ),
        function_slice(
            script,
            "async function confirmCreateLocalCommit",
            "async function confirmApplyAcceptedChanges",
        ),
    )
    for action in actions:
        assert "/push-preflights" not in action
        assert "/push-attempts" not in action
        assert "PUSH_TO_ORIGIN_MAIN" not in action
