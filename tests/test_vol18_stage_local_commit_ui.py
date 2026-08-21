from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static_cockpit" / "vol12_static_mvp"
HTML = STATIC / "twos_command_center.html"
SCRIPT = STATIC / "twos_command_center.js"
STYLES = STATIC / "styles.css"
APP = ROOT / "twos_runtime" / "app.py"


def static_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_stage_local_commit_controls_remain_separate_from_phase18_4b() -> None:
    page = static_source(HTML)
    script = static_source(SCRIPT)
    app = static_source(APP)

    assert 'id="commit-builder-section"' in page
    assert 'id="review-commit-plan"' in page
    assert ">Review Commit Plan<" in page
    assert 'id="stage-approved-files"' in page
    assert ">Stage Approved Files<" in page
    assert 'id="create-local-commit"' in page
    assert ">Create Local Commit<" in page
    assert 'id="commit-plan-subject"' in page
    assert 'id="commit-plan-body"' in page
    assert 'id="commit-plan-subject" type="text" maxlength="200"' in page
    assert 'id="commit-plan-body" rows="3" maxlength="4000"' in page
    assert 'id="commit-builder-status"' in page
    assert 'id="commit-builder-branch"' in page
    assert 'id="commit-builder-head"' in page
    assert 'id="commit-builder-subject"' in page
    assert 'id="commit-builder-validation"' in page
    assert "<dt>Commit Result</dt>" in page
    assert 'id="commit-approved-files"' in page
    assert 'id="commit-excluded-files"' in page
    assert 'id="commit-builder-next-action"' in page
    assert 'id="commit-builder-blockers"' in page

    assert '"/commit-plans"' in script
    assert '"/stage-sessions"' in script
    assert '"/local-commits"' in script
    assert "new TextEncoder()" in script
    assert "utf8ByteLength(value) <= 200" in script
    assert "utf8ByteLength(value) <= 4000" in script
    assert "elements.commitBuilderBranch.textContent" in script
    assert "elements.commitBuilderHead.textContent" in script
    assert "elements.commitBuilderSubject.textContent" in script
    assert "elements.commitBuilderValidation.textContent" in script
    assert (
        'elements.reviewCommitPlan.addEventListener("click", reviewCommitPlan)'
        in script
    )
    assert (
        'elements.stageApprovedFiles.addEventListener("click", openStageConfirmation)'
        in script
    )
    assert (
        'elements.createLocalCommit.addEventListener("click", openLocalCommitConfirmation)'
        in script
    )
    assert "This Stage + Local Commit section never performs Push." in page
    review_action = script.split(
        "async function reviewCommitPlan",
        1,
    )[1].split("async function openPushConfirmation", 1)[0]
    stage_action = script.split(
        "async function confirmStageApprovedFiles",
        1,
    )[1].split("async function confirmCreateLocalCommit", 1)[0]
    commit_action = script.split(
        "async function confirmCreateLocalCommit",
        1,
    )[1].split("async function confirmApplyAcceptedChanges", 1)[0]
    for action in (review_action, stage_action, commit_action):
        assert "/push-preflights" not in action
        assert "/push-attempts" not in action


def test_stage_and_commit_have_separate_explicit_confirmation_surfaces() -> None:
    page = static_source(HTML)
    script = static_source(SCRIPT)

    assert 'id="stage-confirmation-dialog"' in page
    assert 'id="confirm-stage-approved-files"' in page
    assert ">Confirm Stage Approved Files<" in page
    assert 'id="local-commit-confirmation-dialog"' in page
    assert 'id="confirm-create-local-commit"' in page
    assert ">Confirm Create Local Commit<" in page
    assert "STAGE_APPROVED_FILES" in script
    assert "CREATE_LOCAL_COMMIT" in script
    assert (
        'elements.confirmStageApprovedFiles.addEventListener("click", '
        "confirmStageApprovedFiles)"
    ) in script
    assert (
        'elements.confirmCreateLocalCommit.addEventListener("click", '
        "confirmCreateLocalCommit)"
    ) in script

    stage_action = script.split(
        "async function confirmStageApprovedFiles",
        1,
    )[1].split("async function confirmCreateLocalCommit", 1)[0]
    commit_action = script.split(
        "async function confirmCreateLocalCommit",
        1,
    )[1].split("async function confirmApplyAcceptedChanges", 1)[0]
    assert 'method: "POST"' in stage_action
    assert '"/stage-sessions"' in stage_action
    assert '"/local-commits"' not in stage_action
    assert 'method: "POST"' in commit_action
    assert '"/local-commits"' in commit_action
    assert '"/stage-sessions"' not in commit_action


def test_review_and_refresh_are_read_only_and_never_auto_stage_or_commit() -> None:
    script = static_source(SCRIPT)
    loader = script.split(
        "async function loadCommitBuilder",
        1,
    )[1].split("function currentLegacyRun", 1)[0]
    review = script.split(
        "async function reviewCommitPlan",
        1,
    )[1].split("async function confirmStageApprovedFiles", 1)[0]

    assert 'method: "POST"' not in loader
    assert 'method: "POST"' in review
    assert '"/commit-plans"' in review
    assert '"/stage-sessions"' not in review
    assert '"/local-commits"' not in review
    assert "setInterval(confirmStageApprovedFiles" not in script
    assert "setInterval(confirmCreateLocalCommit" not in script
    assert "setTimeout(confirmStageApprovedFiles" not in script
    assert "setTimeout(confirmCreateLocalCommit" not in script


def test_review_sequence_server_state_and_stale_response_guard_are_explicit() -> None:
    page = static_source(HTML)
    script = static_source(SCRIPT)
    app = static_source(APP)

    for step in (
        "Step 1 — Review Commit Plan",
        "Step 2 — Stage Approved Files",
        "Step 3 — Create Local Commit",
    ):
        assert step in page
    assert "Stage the approved files before creating the local commit." in page
    for state in (
        "REVIEW_REQUIRED",
        "READY_TO_STAGE",
        "STAGING_BLOCKED",
        "READY_TO_COMMIT",
        "COMMIT_BLOCKED",
        "COMMITTED",
    ):
        assert state in app
        assert state in script
    assert "STALE_COMMIT_PLAN_RESPONSE" in script
    assert "requestEpoch !== state.taskSelectionEpoch" in script
    assert "Commit Plan request failed. Review the diagnostic evidence" in script


def test_commit_workflow_polling_cannot_overwrite_an_owner_action() -> None:
    script = static_source(SCRIPT)
    loader = script.split(
        "async function loadCommitBuilder",
        1,
    )[1].split("function currentLegacyRun", 1)[0]
    store = script.split(
        "function storeCommitBuilderReview",
        1,
    )[1].split("async function reviewCommitPlan", 1)[0]
    interval = script.split("window.setInterval(function ()", 1)[1]

    assert "commitBuilderRequestSequences" in loader
    assert "state.commitBuilderRequestSequences[key] !== requestSequence" in loader
    assert "state.commitBuilderRequestSequences[key]" in store
    assert "state.pending.size === 0" in interval


def test_phase18_4a_action_handlers_do_not_invoke_push() -> None:
    script = static_source(SCRIPT)
    phase18_4a_actions = (
        script.split("async function reviewCommitPlan", 1)[1].split(
            "async function openPushConfirmation", 1
        )[0],
        script.split("async function confirmStageApprovedFiles", 1)[1].split(
            "async function confirmCreateLocalCommit", 1
        )[0],
        script.split("async function confirmCreateLocalCommit", 1)[1].split(
            "async function confirmApplyAcceptedChanges", 1
        )[0],
    )
    for action in phase18_4a_actions:
        assert "/push-preflights" not in action
        assert "/push-attempts" not in action
        assert "confirmPushToOriginMain" not in action

    builder = static_source(ROOT / "twos_runtime" / "commit_builder.py")
    assert re.search(r'_run_git\(\s*root,\s*"push"', builder) is None


def test_effective_blockers_and_explicit_execution_states_drive_truthful_ui() -> None:
    script = static_source(SCRIPT)
    state_logic = script.split(
        "function commitBuilderState",
        1,
    )[1].split("function renderCommitBuilderAdvanced", 1)[0]

    assert 'if (commitBuilderRecordId(parts.commit)) return "COMMITTED"' not in state_logic
    assert 'if (commitBuilderRecordId(parts.stage)) return "STAGED"' not in state_logic
    assert "commitBuilderRecordId(parts.commit) && !commitStatus" in state_logic
    assert "commitBuilderRecordId(parts.stage) && !stageStatus" in state_logic
    assert state_logic.index('["BLOCKED", "FAILED", "EXPIRED"].indexOf(planStatus)') < (
        state_logic.index('commitStatus === "COMMITTING"')
    )
    assert state_logic.index('["BLOCKED", "EXPIRED"].indexOf(eligibilityStatus)') < (
        state_logic.index('stageStatus === "STAGED"')
    )
    assert 'commitStatus === "COMMITTED"' in script
    assert 'commitStatus === "COMMITTING"' in script
    assert 'commitStatus === "FAILED"' in script
    assert '"STAGE RECOVERY REQUIRED"' in script
    assert '"COMMIT RECOVERY REQUIRED"' in script
    assert 'STAGING: "STAGE RECOVERY REQUIRED"' in script
    assert 'COMMITTING: "COMMIT RECOVERY REQUIRED"' in script
    assert 'STAGING: "STAGING"' not in script
    assert 'COMMITTING: "CREATING LOCAL COMMIT"' not in script
    assert '"Staging approved files"' not in script
    assert '"Creating local Commit"' not in script
    assert '"Review blocker evidence."' in script

    render_logic = script.split(
        "function renderCommitBuilder",
        1,
    )[1].split("function closeCommitPlanDialog", 1)[0]
    record_failure = render_logic.index(
        '["FAILED", "INTEGRITY_BLOCKED"].indexOf(commitStatus)'
    )
    committed = render_logic.index('commitStatus === "COMMITTED"', record_failure)
    effective_blocker = render_logic.index(
        '["BLOCKED", "EXPIRED"].indexOf(planStatus)',
        committed,
    )
    stale_record_fallback = render_logic.index(
        "nextAction = parts.commit.next_action || parts.stage.next_action",
        effective_blocker,
    )
    assert record_failure < committed < effective_blocker < stale_record_fallback
    blocker_branch = render_logic[effective_blocker:stale_record_fallback]
    assert "parts.eligibility.next_action || parts.plan.next_action" in blocker_branch

    stage_confirmation = script.split(
        "function openStageConfirmation",
        1,
    )[1].split("function openLocalCommitConfirmation", 1)[0]
    commit_confirmation = script.split(
        "function openLocalCommitConfirmation",
        1,
    )[1].split("function resultManifestEntries", 1)[0]
    assert "advanced.base_head || boundaryEvidence.head" in stage_confirmation
    assert "advanced.index_fingerprint || indexEvidence.fingerprint" in stage_confirmation
    assert "planAdvanced.base_head" in commit_confirmation


def test_commit_builder_advanced_is_collapsed_safe_and_responsive() -> None:
    page = static_source(HTML)
    script = static_source(SCRIPT)
    styles = static_source(STYLES)
    advanced_tag = page.split('<details id="advanced-panel"', 1)[1].split(
        ">",
        1,
    )[0]
    default_section = page.split(
        '<section id="commit-builder-section"',
        1,
    )[1].split("</section>", 1)[0]
    advanced_section = page.split(
        '<section id="commit-builder-advanced-card"',
        1,
    )[1].split("</section>", 1)[0]

    assert " open" not in advanced_tag
    assert "commit-plan-digest" not in default_section
    assert "local-commit-sha" not in default_section
    assert 'id="commit-plan-digest"' in advanced_section
    assert 'id="stage-session-digest"' in advanced_section
    assert 'id="local-commit-sha"' in advanced_section
    assert "Sanitized Git diagnostics" in advanced_section
    assert "absolute_path" not in script
    assert ".commit-builder-heading" in styles
    assert ".commit-builder-file-list" in styles
    assert ".commit-builder-evidence-grid" in styles
    assert "@media (max-width: 760px)" in styles
    assert "@media (max-width: 420px)" in styles
    assert "overflow-wrap: anywhere" in styles
