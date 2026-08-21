from __future__ import annotations

from tests.test_vol18_apply_revert import (
    APPLY_CONFIRMATION,
    phase18b_fixture,
)


def test_owner_apply_summary_persists_pending_and_applied_truth(tmp_path):
    with phase18b_fixture(tmp_path) as fixture:
        plan_id = fixture.plan["id"]
        url = f"/api/apply-plans/{plan_id}/apply-sessions"

        pending = fixture.client.get(url)
        assert pending.status_code == 200
        for field, expected in {
            "approval_state": "AWAITING OWNER CONFIRMATION",
            "execution_state": "Pending",
            "changed_file_count": 0,
            "validation_result": "NOT RUN",
            "recovery_available": False,
        }.items():
            assert pending.json()[field] == expected

        applied = fixture.client.post(
            url,
            json={
                "confirmation": APPLY_CONFIRMATION,
                "expected_plan_digest": fixture.plan["advanced"]["plan_digest"],
                "expected_candidate_digest": fixture.plan["advanced"]["candidate_digest"],
            },
        )
        assert applied.status_code == 200, applied.text
        summary = applied.json()
        assert summary["approval_state"] == "OWNER CONFIRMED"
        assert summary["execution_state"] == "Applied"
        assert summary["changed_file_count"] == 4
        assert summary["validation_result"] == "PASSED"
        assert summary["recovery_available"] is True
        assert summary["result_summary"] == "Applied 4 approved file(s)."

        reloaded = fixture.client.get(url)
        assert reloaded.status_code == 200
        for field in (
            "approval_state",
            "execution_state",
            "result_summary",
            "changed_file_count",
            "validation_result",
            "recovery_available",
        ):
            assert reloaded.json()[field] == summary[field]


def test_owner_apply_surface_has_required_primary_summary(tmp_path):
    with phase18b_fixture(tmp_path) as fixture:
        page = fixture.client.get("/twos")
        assert page.status_code == 200
        for element_id in (
            "apply-session-approval",
            "apply-session-readiness",
            "apply-session-state",
            "apply-session-result-summary",
            "apply-session-changed-count",
            "apply-session-validation",
            "apply-session-recovery",
        ):
            assert f'id="{element_id}"' in page.text
        assert "Apply and Revert do not stage, commit, or push." in page.text
