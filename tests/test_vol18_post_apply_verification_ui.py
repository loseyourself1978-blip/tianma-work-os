from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static_cockpit" / "vol12_static_mvp"
HTML = STATIC / "twos_command_center.html"
SCRIPT = STATIC / "twos_command_center.js"
STYLES = STATIC / "styles.css"


def static_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_post_apply_verification_ui_contract_and_phase18_4_boundary() -> None:
    page = static_source(HTML)
    script = static_source(SCRIPT)

    assert 'id="post-apply-verification-section"' in page
    assert 'id="verify-applied-changes"' in page
    assert ">Verify Applied Changes<" in page
    assert 'id="post-apply-verification-status"' in page
    assert 'id="post-apply-verification-changed-files"' in page
    assert 'id="post-apply-verification-unexpected-files"' in page
    assert 'id="post-apply-verification-tests"' in page
    assert 'id="post-apply-verification-boundaries"' in page
    assert 'id="post-apply-verification-next-action"' in page
    assert 'id="post-apply-verification-blockers"' in page

    assert '"/post-apply-verifications"' in script
    assert 'elements.verifyAppliedChanges.addEventListener("click", verifyAppliedChanges)' in script
    # Phase 18.4B legitimately adds a Push control to the shared shell.  The
    # Phase 18.3 verification action itself must still stop at persisted
    # verification and never reach either Push endpoint.
    verification_action = script.split(
        "async function verifyAppliedChanges",
        1,
    )[1].split("async function openPushConfirmation", 1)[0]
    assert '"/push-preflights"' not in verification_action
    assert '"/push-attempts"' not in verification_action
    assert "confirmPushToOriginMain" not in verification_action


def test_control_is_exactly_scoped_and_get_never_runs_the_verification() -> None:
    script = static_source(SCRIPT)
    context = script.split(
        "function postApplyVerificationContextAvailable",
        1,
    )[1].split("function postApplyVerificationReviewForSession", 1)[0]
    loader = script.split(
        "async function loadPostApplyVerification",
        1,
    )[1].split("function currentLegacyRun", 1)[0]
    action = script.split(
        "async function verifyAppliedChanges",
        1,
    )[1].split("async function confirmApplyAcceptedChanges", 1)[0]

    assert 'normalizedApplySessionState(record.apply_state) === "APPLIED"' in context
    assert 'normalizedApplySessionState(record.revert_state) === "NOT_REQUESTED"' in context
    assert 'method: "POST"' not in loader
    assert 'method: "POST"' in action
    assert "postApplyVerificationContextAvailable(applySession)" in action


def test_advanced_evidence_is_collapsed_and_separate_from_default_view() -> None:
    page = static_source(HTML)
    advanced_tag = page.split('<details id="advanced-panel"', 1)[1].split(">", 1)[0]
    default_section = page.split(
        '<section id="post-apply-verification-section"',
        1,
    )[1].split("</section>", 1)[0]
    advanced_section = page.split(
        '<section id="post-apply-verification-advanced-card"',
        1,
    )[1].split("</section>", 1)[0]

    assert " open" not in advanced_tag
    assert "verification-digest" not in default_section
    assert "observation-digest" not in default_section
    assert 'id="post-apply-verification-digest"' in advanced_section
    assert 'id="post-apply-observation-digest"' in advanced_section
    assert 'id="post-apply-verification-expected-paths"' in advanced_section
    assert 'id="post-apply-verification-observed-paths"' in advanced_section
    assert "Sanitized Git diagnostics" in advanced_section


def test_git_metadata_refresh_is_advanced_only_and_not_an_unexpected_file_label() -> None:
    script = static_source(SCRIPT)
    advanced_renderer = script.split(
        "function renderPostApplyVerificationAdvanced",
        1,
    )[1].split("function renderPostApplyVerification(run)", 1)[0]
    default_renderer = script.split(
        "function renderPostApplyVerification(run)",
        1,
    )[1].split("function confirmationListText", 1)[0]

    assert "diagnosticText(advanced.diagnostics" in advanced_renderer
    assert "advanced.diagnostics" not in default_renderer
    assert "verification.unexpected_files" in default_renderer
    assert "Git metadata refresh observed" not in default_renderer
    assert "Unexpected file changed" not in advanced_renderer


def test_post_apply_verification_layout_supports_1280_and_390_widths() -> None:
    styles = static_source(STYLES)

    assert ".post-apply-verification-heading" in styles
    assert ".post-apply-verification-file-list" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in styles
    assert "@media (max-width: 760px)" in styles
    assert "@media (max-width: 420px)" in styles
    assert ".post-apply-verification-heading .button-row" in styles
    assert ".post-apply-verification-controls .button" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "grid-template-columns: minmax(0, 1fr);" in styles
