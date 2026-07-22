from __future__ import annotations

from dataclasses import dataclass


ACTION_POLICIES = {
    "compact_sync": "auto",
    "codex_execute": "approval_required",
    "sync_review": "approval_required",
    "manual_handoff": "manual",
    "live_trade": "blocked",
    "live_bet": "blocked",
    "broker_order": "blocked",
    "betting_order": "blocked",
}

CONNECTOR_STATUSES = ["unconfigured", "configured", "healthy", "degraded", "failed", "disabled", "blocked"]
LIFECYCLE_STATES = [
    "draft",
    "planned",
    "pack_ready",
    "approval_required",
    "queued",
    "starting",
    "running",
    "verifying",
    "result_ready",
    "owner_review",
    "review",
    "accepted",
    "rejected",
    "needs_review",
    "failed",
    "blocked",
    "cancelled",
    "timed_out",
]


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    policy: str
    reason: str


def evaluate_action(action: str) -> PolicyDecision:
    policy = ACTION_POLICIES.get(action, "approval_required")
    if policy == "blocked":
        return PolicyDecision(False, policy, f"{action} is denied by TWOS backend policy.")
    if action != "compact_sync":
        return PolicyDecision(False, policy, f"{action} is not implemented as an automatic MVP-14 worker action.")
    return PolicyDecision(True, policy, "compact_sync is a safe internal worker action.")
