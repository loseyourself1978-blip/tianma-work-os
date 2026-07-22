from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AICapability,
    AIModel,
    AIModelAssignment,
    AIModelInvocationEvidence,
    AITeamPlan,
    AITeamPlanItem,
    CodexRun,
    Provider,
    RoutingDecision,
    Task,
    utc_now,
)


ROLE_LABELS = {
    "reasoning": "Reasoning analyst",
    "coding": "Implementation builder",
    "research": "Research analyst",
    "verification": "Acceptance verifier",
    "summarization": "Sync synthesizer",
    "planning": "Execution planner",
    "risk_analysis": "Risk analyst",
    "data_analysis": "Data analyst",
}

CAPABILITY_LABELS = {
    name: name.replace("_", " ").title()
    for name in ROLE_LABELS
}

ELIGIBLE_STATUSES = {"healthy", "degraded"}
STATUS_RANK = {"healthy": 0, "degraded": 1}
TIER_RANK = {"low": 0, "medium": 1, "high": 2, "unknown": 3}
ASSIGNMENT_ROLES = ("planning", "coding", "verification")
CONFIGURATION_STATES = {"configured", "needs_setup", "disabled"}
AVAILABILITY_STATES = {"available", "unavailable", "disabled"}
INVOCATION_MODES = {"real", "simulated", "manual", "unavailable"}
EVIDENCE_SOURCES = {
    "none",
    "seeded_registry",
    "local_cli_readiness",
    "invocation_evidence",
    "simulation_record",
    "manual_record",
    "configuration_removed",
}
INVOCATION_OUTCOMES = {"succeeded", "failed", "cancelled", "timed_out", "blocked"}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}$")
_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_MATERIAL = re.compile(
    r"api[_ -]?key|authorization|bearer\s+|password|client[_ -]?secret|"
    r"session[_ -]?token|access[_ -]?token|(?:^|[^a-z0-9])sk-[a-z0-9_-]{16,}",
    re.IGNORECASE,
)

PROCESS_EVIDENCE_SCHEMA = {
    "process_observed": "bool",
    "process_execution_verified": "bool",
    "exit_code": "signed_int",
    "duration_ms": "nonnegative_int",
    "isolated_worktree": "bool",
    "read_only_sandbox": "bool",
    "verification_verdict_observed": "bool",
    "workspace_unchanged_after_verification": "bool",
    "changed_files_checked": "bool",
    "unexpected_files_checked": "bool",
    "exact_content_checked": "bool",
    "test_evidence_checked": "bool",
    "git_boundary_checked": "bool",
    "remote_boundary_checked": "bool",
    "stdout_present": "bool",
    "stderr_present": "bool",
    "codex_jsonl_observed": "bool",
    "codex_thread_started": "bool",
    "codex_turn_started": "bool",
    "codex_turn_completed": "bool",
    "codex_turn_failed": "bool",
    "codex_turn_verified": "bool",
    "model_argument_observed": "bool",
    "model_identity_observed": "bool",
    "actual_model_identity_verified": "bool",
    "model_reroute_observed": "bool",
    "unsupported_model_routing_observed": "bool",
    "final_agent_message_observed": "bool",
    "approved_pack_stdin_complete": "bool",
    "runtime_interrupted": "bool",
    "jsonl_malformed_lines": "nonnegative_int",
    "jsonl_event_count": "nonnegative_int",
    "command_execution_count": "nonnegative_int",
    "file_change_count": "nonnegative_int",
    "command_shape": "safe_text",
    "executable_identity_fingerprint": "sha256",
    "process_id_fingerprint": "sha256",
    "thread_id_fingerprint": "sha256",
    "turn_id_fingerprint": "sha256",
}
PROVIDER_EVIDENCE_SCHEMA = {
    "provider_response_observed": "bool",
    "status_code": "status_code",
    "request_id_fingerprint": "sha256",
    "model_identifier_match": "bool",
    "requested_model_identifier_match": "bool",
}
USAGE_METADATA_SCHEMA = {
    "input_tokens": "nonnegative_int",
    "output_tokens": "nonnegative_int",
    "total_tokens": "nonnegative_int",
    "cached_input_tokens": "nonnegative_int",
    "cache_write_input_tokens": "nonnegative_int",
    "reasoning_output_tokens": "nonnegative_int",
    "estimated_cost_units": "nonnegative_number",
}


def decode_capability_tags(model: AIModel) -> list[str]:
    try:
        tags = json.loads(model.capability_tags)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(tag) for tag in tags] if isinstance(tags, list) else []


def _task_context(task: Task) -> tuple[str, str]:
    project_key = task.project.key if task.project else ""
    text = " ".join(
        [task.title, task.task_type, task.required_output, task.boundary_risk, project_key]
    ).lower()

    if task.workflow_type == "product_development":
        return "product_build", text
    if task.task_type == "Compact Sync" or "compact sync" in text or "summar" in text:
        return "compact_sync", text
    if project_key == "twos" and any(
        token in text for token in ["build", "implement", "coding", "product structure"]
    ):
        return "product_build", text
    if project_key == "ldd" and any(token in text for token in ["risk", "review", "spcx", "admission"]):
        return "ldd_risk_review", text
    if any(token in text for token in ["data", "settlement", "quantitative", "p/l"]):
        return "data_review", text
    if task.task_type == "Acceptance Review":
        return "acceptance_review", text
    if "research" in text:
        return "research", text
    if "risk" in text:
        return "risk_review", text
    return "general", text


def _default_capabilities(task: Task, risk_level: str) -> list[str]:
    context, _ = _task_context(task)

    if context == "compact_sync":
        capabilities = ["summarization", "verification"]
    elif context == "product_build":
        capabilities = ["planning", "coding", "verification"]
    elif context == "ldd_risk_review":
        capabilities = ["reasoning", "risk_analysis", "verification"]
    elif context == "research":
        capabilities = ["research", "reasoning"]
    elif context == "data_review":
        capabilities = ["data_analysis", "verification"]
    elif context == "acceptance_review":
        capabilities = ["verification", "reasoning"]
    elif context == "risk_review":
        capabilities = ["reasoning", "risk_analysis", "verification"]
    else:
        capabilities = ["reasoning", "planning"]

    if risk_level == "high" and "risk_analysis" not in capabilities:
        verification_index = capabilities.index("verification") if "verification" in capabilities else len(capabilities)
        capabilities.insert(verification_index, "risk_analysis")
    return capabilities


def _selection_reason(task: Task, capability: str) -> str:
    context, _ = _task_context(task)
    title = task.title
    context_reasons = {
        "product_build": {
            "planning": f'Planning turns "{title}" into an ordered implementation path tied to the required output.',
            "coding": f'Coding is needed because "{title}" asks for a product implementation artifact.',
            "verification": "Verification checks the build against acceptance conditions and the stated boundary.",
            "risk_analysis": "Risk Analysis is included because the selected risk level requires a separate downside check.",
        },
        "ldd_risk_review": {
            "reasoning": f'Reasoning interprets the supplied LDD evidence and frames the decision for "{title}".',
            "risk_analysis": "Risk Analysis examines downside, admission gates, and chase boundaries before a conclusion.",
            "verification": "Verification checks the evidence and confirms that no live trading action is implied.",
        },
        "compact_sync": {
            "summarization": f'Summarization compresses the source evidence for "{title}" into the required sync output.',
            "verification": "Verification confirms that the compact sync preserves its required output and boundary.",
        },
    }
    if capability in context_reasons.get(context, {}):
        return context_reasons[context][capability]

    generic_reasons = {
        "reasoning": f'Reasoning resolves the decision and ambiguity in "{title}".',
        "coding": f'Coding produces the implementation requested by "{title}".',
        "research": f'Research gathers evidence that is not already present in the source sync for "{title}".',
        "verification": f'Verification checks the output and acceptance boundary for "{title}".',
        "summarization": f'Summarization condenses the supplied context into the requested output for "{title}".',
        "planning": f'Planning orders the work and dependencies required by "{title}".',
        "risk_analysis": f'Risk Analysis isolates downside and boundary exposure in "{title}".',
        "data_analysis": f'Data Analysis interprets the structured or quantitative evidence in "{title}".',
    }
    return generic_reasons[capability]


def _omission_reason(task: Task, capability: str) -> str:
    context, _ = _task_context(task)
    context_reasons = {
        "product_build": {
            "reasoning": "The build context is already explicit, so a separate reasoning role would duplicate Planning.",
            "research": "The task uses the supplied product context and does not request new evidence gathering.",
            "summarization": "Sync compression is not the required output of this product build.",
            "risk_analysis": "The stated risk does not require a separate downside-analysis role at this level.",
            "data_analysis": "The task does not require structured quantitative analysis.",
        },
        "ldd_risk_review": {
            "coding": "This is an analysis and review task, not an implementation task.",
            "research": "The review uses the supplied LDD evidence rather than opening new research.",
            "summarization": "The required output is a risk decision, not a compact sync.",
            "planning": "The task asks for a bounded risk review, not an implementation plan.",
            "data_analysis": "No separate settlement or quantitative-processing output is requested.",
        },
        "compact_sync": {
            "reasoning": "The source decision already exists and only needs faithful compression.",
            "coding": "No implementation artifact is requested.",
            "research": "No new evidence gathering is requested.",
            "planning": "No execution plan is requested.",
            "risk_analysis": "The task preserves an existing boundary rather than creating a new risk judgment.",
            "data_analysis": "No structured quantitative processing is requested.",
        },
    }
    if capability in context_reasons.get(context, {}):
        return context_reasons[context][capability]
    return f"{CAPABILITY_LABELS[capability]} would not materially improve this task's required output."


def _team_explanation(task: Task, capabilities: list[str]) -> str:
    context, _ = _task_context(task)
    labels = ", ".join(CAPABILITY_LABELS[name] for name in capabilities)
    if context == "product_build" and {"planning", "coding", "verification"}.issubset(capabilities):
        return (
            f'"{task.title}" needs an ordered build plan, implementation capability, and an independent '
            f"acceptance check. {labels} are the minimum effective team for that outcome."
        )
    if context == "ldd_risk_review" and {"reasoning", "risk_analysis", "verification"}.issubset(capabilities):
        return (
            f'"{task.title}" needs evidence interpretation, a distinct downside and admission-gate review, '
            f"and an independent boundary check. {labels} are the minimum effective team for that decision."
        )
    return (
        f'"{task.title}" requires {labels}. These {len(capabilities)} capabilities are the minimum effective '
        "team after removing roles that would duplicate the requested output."
    )


def _omission_explanation(task: Task, omitted: list[dict[str, str]]) -> str:
    if not omitted:
        return "No capability was omitted because every enabled capability is required by this task."
    context, _ = _task_context(task)
    labels = ", ".join(CAPABILITY_LABELS[item["capability"]] for item in omitted)
    if context == "product_build":
        return (
            f"Not added: {labels}. They would not improve this defined implementation and acceptance output "
            "enough to expand the minimum effective team."
        )
    if context == "ldd_risk_review":
        return (
            f"Not added: {labels}. This is a bounded risk review using supplied evidence, not a build, new "
            "research, sync compression, execution plan, or settlement calculation."
        )
    return f"Not added: {labels}. Each was omitted because it would duplicate work or not improve the required output."


def compose_team(
    session: Session,
    task: Task,
    risk_level: str = "medium",
    urgency: str = "normal",
    capability_override: list[str] | None = None,
) -> AITeamPlan:
    capability_rows = {
        item.name: item
        for item in session.scalars(
            select(AICapability).where(AICapability.enabled == True).order_by(AICapability.id)  # noqa: E712
        ).all()
    }
    requested = list(capability_override or _default_capabilities(task, risk_level))
    if task.workflow_type == "product_development":
        # Workbench capability focus is additive for product builds. Vol.17's
        # Planning/Coding/Verification responsibilities are mandatory and may
        # not be removed by focusing the composition on one capability.
        for required_capability in ("planning", "coding", "verification"):
            if required_capability not in requested:
                requested.append(required_capability)
    capabilities: list[str] = []
    for name in requested:
        if name not in capability_rows:
            raise ValueError(f"Unknown or disabled AI capability: {name}")
        if name not in capabilities:
            capabilities.append(name)

    if len(capabilities) < 2:
        complement = "verification" if "verification" not in capabilities else "reasoning"
        if complement in capability_rows:
            capabilities.append(complement)

    verification_required = any(capability_rows[name].requires_verification for name in capabilities)
    if verification_required and "verification" not in capabilities:
        capabilities.append("verification")

    omitted = [
        {"capability": name, "reason": _omission_reason(task, name)}
        for name in capability_rows
        if name not in capabilities
    ]

    plan = AITeamPlan(
        task_id=task.id,
        risk_level=risk_level,
        urgency=urgency,
        required_capabilities=json.dumps(capabilities, separators=(",", ":")),
        omitted_capabilities=json.dumps(omitted, separators=(",", ":")),
        minimum_role_count=len(capabilities),
        status="composed",
        explanation=_team_explanation(task, capabilities),
        omission_explanation=_omission_explanation(task, omitted),
    )
    session.add(plan)
    session.flush()
    for ordinal, name in enumerate(capabilities):
        session.add(
            AITeamPlanItem(
                plan_id=plan.id,
                capability_id=capability_rows[name].id,
                role_label=ROLE_LABELS.get(name, name.replace("_", " ").title()),
                selection_reason=_selection_reason(task, name),
                ordinal=ordinal,
            )
        )
    session.flush()
    return plan


def _routing_score(
    provider: Provider,
    model: AIModel,
    urgency: str,
    cost_sensitivity: str,
    latency_sensitivity: str,
) -> tuple[int, int, int, int, int]:
    cost_rank = TIER_RANK.get(model.cost_metadata, TIER_RANK["unknown"])
    latency_rank = TIER_RANK.get(model.latency_metadata, TIER_RANK["unknown"])
    cost_weight = 0 if cost_sensitivity == "low" else cost_rank
    latency_weight = 0 if latency_sensitivity == "low" and urgency != "high" else latency_rank
    return (
        STATUS_RANK[provider.status],
        STATUS_RANK[model.status],
        latency_weight,
        cost_weight,
        model.routing_priority,
    )


def _eligible_model_candidates(
    session: Session,
    capability: AICapability,
    *,
    urgency: str,
    cost_sensitivity: str,
    latency_sensitivity: str,
) -> list[tuple[tuple[int, int, int, int, int], AIModel]]:
    candidates: list[tuple[tuple[int, int, int, int, int], AIModel]] = []
    for model in session.scalars(select(AIModel).order_by(AIModel.id)).all():
        if capability.name not in decode_capability_tags(model):
            continue
        provider = model.provider
        if not provider.enabled:
            continue
        if provider.status not in ELIGIBLE_STATUSES or model.status not in ELIGIBLE_STATUSES:
            continue
        if _configuration_state(model) != "configured":
            continue
        if _availability_state(model) != "available":
            continue
        if model.invocation_mode not in {"real", "simulated", "manual"}:
            continue
        candidates.append(
            (
                _routing_score(
                    provider,
                    model,
                    urgency=urgency,
                    cost_sensitivity=cost_sensitivity,
                    latency_sensitivity=latency_sensitivity,
                ),
                model,
            )
        )
    candidates.sort(key=lambda item: item[0])
    return candidates


def route_capability(
    session: Session,
    task: Task,
    capability: AICapability,
    team_plan_id: int | None = None,
    requested_capabilities: list[str] | None = None,
    urgency: str = "normal",
    cost_sensitivity: str = "balanced",
    latency_sensitivity: str = "balanced",
) -> RoutingDecision:
    models = session.scalars(select(AIModel).order_by(AIModel.id)).all()
    compatible_models = [model for model in models if capability.name in decode_capability_tags(model)]
    candidates = _eligible_model_candidates(
        session,
        capability,
        urgency=urgency,
        cost_sensitivity=cost_sensitivity,
        latency_sensitivity=latency_sensitivity,
    )
    selected = candidates[0][1] if candidates else None
    fallback = candidates[1][1] if len(candidates) > 1 else None
    requested = requested_capabilities or [capability.name]
    if selected:
        reason = (
            f"Selected the highest-ranked eligible model for {capability.name}; provider is "
            f"{selected.provider.status}, model availability is {_availability_state(selected)}, "
            f"invocation mode is {selected.invocation_mode}, and the routing decision is complete."
        )
        if fallback:
            reason += " A second eligible model is recorded as fallback."
            fallback_status = "available"
            fallback_reason = (
                f"Fallback is {fallback.provider.name} / {fallback.model_name}, the next highest-ranked "
                "healthy compatible option."
            )
        else:
            fallback_status = "unavailable"
            fallback_reason = "No fallback is available because only one compatible model passed the routing gate."
        next_action = "Proceed under the task's approval, execution, and acceptance policies."
        status = "selected"
    else:
        compatible_providers = {model.provider.id: model.provider for model in compatible_models}.values()
        if compatible_models and all(
            _configuration_state(model) != "configured" for model in compatible_models
        ):
            reason = "No configured and healthy provider is available for the requested capabilities."
            fallback_reason = "No fallback is available because all compatible providers are unconfigured."
            next_action = "Configure and verify at least one compatible provider, then recompose the AI Team."
        elif compatible_models and all(
            _availability_state(model) != "available" for model in compatible_models
        ):
            reason = "Compatible models are configured but none is currently available."
            fallback_reason = "No fallback is available because every compatible model is unavailable."
            next_action = "Resolve model and provider readiness, then recompose the AI Team."
        elif not compatible_models:
            reason = f"No registered model declares support for the requested {capability.name} capability."
            fallback_reason = "No fallback is available because the model registry has no compatible candidate."
            next_action = "Register a compatible model profile, then recompose the AI Team."
        else:
            reason = (
                "Routing evaluation completed, but no compatible provider and model are both enabled and healthy."
            )
            fallback_reason = "No fallback is available because every compatible candidate failed the routing gate."
            next_action = "Resolve provider health or enablement, then recompose the AI Team."
        fallback_status = "unavailable"
        status = "unavailable"

    decision = RoutingDecision(
        task_id=task.id,
        team_plan_id=team_plan_id,
        capability_id=capability.id,
        urgency=urgency,
        cost_sensitivity=cost_sensitivity,
        latency_sensitivity=latency_sensitivity,
        requested_capabilities=json.dumps(requested, separators=(",", ":")),
        selected_model_id=selected.id if selected else None,
        fallback_model_id=fallback.id if fallback else None,
        status=status,
        reason=reason,
        fallback_status=fallback_status,
        fallback_reason=fallback_reason,
        next_action=next_action,
    )
    session.add(decision)
    session.flush()
    return decision


def _configuration_state(model: AIModel) -> str:
    state = model.configuration_status
    if state not in CONFIGURATION_STATES:
        state = "needs_setup"
    if model.status in {"blocked", "disabled"} or model.provider.status in {"blocked", "disabled"}:
        return "disabled"
    return state


def _availability_state(model: AIModel) -> str:
    state = model.availability_status
    if state not in AVAILABILITY_STATES:
        state = "unavailable"
    if model.status in {"blocked", "disabled"} or model.provider.status in {"blocked", "disabled"}:
        return "disabled"
    if not model.provider.enabled or model.provider.status not in ELIGIBLE_STATUSES:
        return "unavailable"
    if model.status not in ELIGIBLE_STATUSES:
        return "unavailable"
    return state


def _public_diagnostic(value: str) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return ""
    if len(text_value) > 500 or _SECRET_MATERIAL.search(text_value):
        return "Diagnostic withheld by safety policy."
    return text_value


def model_registry_snapshot(model: AIModel) -> dict[str, Any]:
    """Return the stable, secret-free registry contract used by Vol.17 APIs."""
    provider = model.provider
    invocation_mode = model.invocation_mode if model.invocation_mode in INVOCATION_MODES else "unavailable"
    stable_id = str(model.stable_id or "")
    if not _SAFE_IDENTIFIER.fullmatch(stable_id) or _SECRET_MATERIAL.search(stable_id):
        stable_id = f"legacy-model-{model.id}"
    provider_model_id = str(model.provider_model_id or "")
    if provider_model_id and (
        not _SAFE_IDENTIFIER.fullmatch(provider_model_id) or _SECRET_MATERIAL.search(provider_model_id)
    ):
        provider_model_id = ""
    display_name = str(model.display_name or model.model_name)
    if len(display_name) > 160 or _SECRET_MATERIAL.search(display_name):
        display_name = "Configured model"
    provider_name = str(provider.name or "")
    if not provider_name or len(provider_name) > 120 or _SECRET_MATERIAL.search(provider_name):
        provider_name = "Configured provider"
    evidence_source = str(model.evidence_source or "none")
    if evidence_source not in EVIDENCE_SOURCES:
        evidence_source = "none"
    return {
        "stable_id": stable_id,
        "display_name": display_name,
        "provider": {
            "id": provider.id,
            "name": provider_name,
            "kind": provider.kind,
            "enabled": provider.enabled,
            "status": provider.status,
        },
        "provider_model_id": provider_model_id,
        "execution_adapter": str(model.execution_adapter or ""),
        "capabilities": decode_capability_tags(model),
        "configuration_status": _configuration_state(model),
        "availability_status": _availability_state(model),
        "invocation_mode": invocation_mode,
        "last_invocation_outcome": model.last_invocation_outcome,
        "evidence_status": model.evidence_status,
        "evidence_source": evidence_source,
        "last_verified_at": model.last_verified_at.isoformat() if model.last_verified_at else None,
        "safe_diagnostic": _public_diagnostic(model.safe_diagnostic),
    }


def _model_routing_snapshot(model: AIModel | None) -> dict[str, Any] | None:
    if model is None:
        return None
    registry = model_registry_snapshot(model)
    return {
        "stable_id": registry["stable_id"],
        "provider_id": registry["provider"]["id"],
        "provider_model_id": registry["provider_model_id"],
        "execution_adapter": registry["execution_adapter"],
        "capabilities": registry["capabilities"],
        "configuration_status": registry["configuration_status"],
        "availability_status": registry["availability_status"],
        "invocation_mode": registry["invocation_mode"],
    }


def _assignment_payloads(
    session: Session,
    routing_decisions: Iterable[RoutingDecision],
    routing_source: str,
) -> list[dict[str, Any]]:
    latest_by_capability: dict[str, RoutingDecision] = {}
    for decision in sorted(routing_decisions, key=lambda item: item.id or 0):
        latest_by_capability[decision.capability.name] = decision

    payloads: list[dict[str, Any]] = []
    ordered_capabilities = [name for name in ASSIGNMENT_ROLES if name in latest_by_capability]
    ordered_capabilities.extend(
        name for name in sorted(latest_by_capability) if name not in ASSIGNMENT_ROLES
    )
    for role in ordered_capabilities:
        decision = latest_by_capability[role]
        assigned_model = decision.selected_model
        fallback_model = decision.fallback_model
        available = bool(assigned_model and _availability_state(assigned_model) == "available")
        fallback_available = bool(fallback_model and _availability_state(fallback_model) == "available")
        payloads.append(
            {
                "role": role,
                "capability": role,
                "assigned_model": assigned_model,
                "fallback_model": fallback_model,
                "assignment_reason": decision.reason,
                "routing_source": routing_source,
                "availability_at_composition": "available" if available else "unavailable",
                "fallback_allowed": fallback_available,
                "fallback_reason": decision.fallback_reason,
                "independence_required": role == "verification",
                "independence_status": "pending" if role == "verification" else "not_required",
                "independent_from_roles": [],
            }
        )

    verification = next((payload for payload in payloads if payload["role"] == "verification"), None)
    if verification is None:
        return payloads
    producer_payloads = [payload for payload in payloads if payload["role"] != "verification"]
    verification["independent_from_roles"] = [payload["role"] for payload in producer_payloads]
    primary_ids = {
        payload["assigned_model"].id
        for payload in producer_payloads
        if payload["assigned_model"] is not None
    }
    verification_model = verification["assigned_model"]
    verification_decision = latest_by_capability["verification"]
    independent_candidates = [
        model
        for _, model in _eligible_model_candidates(
            session,
            verification_decision.capability,
            urgency=verification_decision.urgency,
            cost_sensitivity=verification_decision.cost_sensitivity,
            latency_sensitivity=verification_decision.latency_sensitivity,
        )
        if model.id not in primary_ids
    ]
    if verification_model is None:
        if independent_candidates:
            verification["assigned_model"] = independent_candidates[0]
            verification["fallback_model"] = (
                independent_candidates[1] if len(independent_candidates) > 1 else None
            )
            verification["independence_status"] = "independent_fallback"
            verification["availability_at_composition"] = "available"
            verification["fallback_allowed"] = len(independent_candidates) > 1
            verification["assignment_reason"] += (
                " Verification uses the highest-ranked independent eligible model from the full routing set."
            )
            verification["fallback_reason"] = (
                "A second independent eligible verification model is recorded as fallback."
                if len(independent_candidates) > 1
                else "No second independent eligible verification model is available as fallback."
            )
        else:
            verification["independence_status"] = "unavailable"
            verification["availability_at_composition"] = "unavailable"
            verification["fallback_allowed"] = False
    elif verification_model.id not in primary_ids:
        verification["independence_status"] = "independent"
        independent_fallbacks = [
            model for model in independent_candidates if model.id != verification_model.id
        ]
        verification["fallback_model"] = independent_fallbacks[0] if independent_fallbacks else None
        verification["fallback_allowed"] = bool(independent_fallbacks)
        verification["fallback_reason"] = (
            "The next independent eligible verification model is recorded as fallback."
            if independent_fallbacks
            else "No second independent eligible verification model is available as fallback."
        )
    else:
        if routing_source == "owner_setup":
            # An explicit Owner model binding is authoritative. Independence is
            # proven by a distinct Verification process and evidence record,
            # not by silently substituting a different catalog model.
            verification["fallback_model"] = None
            verification["independence_status"] = "separate_invocation"
            verification["availability_at_composition"] = "available"
            verification["fallback_allowed"] = False
            verification["assignment_reason"] += (
                " The same model is assigned to a separate Verification invocation; "
                "this is not a multi-model execution."
            )
            verification["fallback_reason"] = (
                "Owner selected the same model for Coding and Verification; Verification must run "
                "as a separate invocation with separate evidence."
            )
        elif independent_candidates:
            verification["assigned_model"] = independent_candidates[0]
            verification["fallback_model"] = (
                independent_candidates[1] if len(independent_candidates) > 1 else None
            )
            verification["availability_at_composition"] = "available"
            verification["fallback_allowed"] = len(independent_candidates) > 1
            verification["independence_status"] = "independent_fallback"
            verification["assignment_reason"] += (
                " Verification uses the highest-ranked independent eligible model from the full routing set."
            )
            verification["fallback_reason"] = (
                "A second independent eligible verification model is recorded as fallback."
                if len(independent_candidates) > 1
                else "The producer model is not an allowed fallback and no second independent model is available."
            )
        else:
            # A different model is preferable when one is genuinely eligible,
            # but model identity is not the same thing as invocation identity.
            # Keep the real selected model and require a distinct Verification
            # process/evidence record instead of making the executable path
            # unreachable merely because Coding uses the same model.
            verification["fallback_model"] = None
            verification["independence_status"] = "separate_invocation"
            verification["availability_at_composition"] = "available"
            verification["fallback_allowed"] = False
            verification["assignment_reason"] += (
                " The same model is assigned to a separate Verification invocation; "
                "this is not a multi-model execution."
            )
            verification["fallback_reason"] = (
                "No different eligible Verification model is available; Verification must run "
                "as a separate invocation with separate evidence."
            )
    return payloads


def _routing_snapshot_hash(payloads: list[dict[str, Any]]) -> str:
    semantic_snapshot = [
        {
            "role": payload["role"],
            "capability": payload["capability"],
            "assigned_model": _model_routing_snapshot(payload["assigned_model"]),
            "fallback_model": _model_routing_snapshot(payload["fallback_model"]),
            "assignment_reason": payload["assignment_reason"],
            "routing_source": payload["routing_source"],
            "availability_at_composition": payload["availability_at_composition"],
            "fallback_allowed": payload["fallback_allowed"],
            "fallback_reason": payload["fallback_reason"],
            "independence_required": payload["independence_required"],
            "independence_status": payload["independence_status"],
            "independent_from_roles": payload["independent_from_roles"],
        }
        for payload in payloads
    ]
    encoded = json.dumps(semantic_snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def latest_model_assignments(session: Session, task_id: int) -> list[AIModelAssignment]:
    latest_binding = session.execute(
        select(AIModelAssignment.assignment_version, AIModelAssignment.task_version)
        .where(AIModelAssignment.task_id == task_id)
        .order_by(
            AIModelAssignment.assignment_version.desc(),
            AIModelAssignment.task_version.desc(),
        )
        .limit(1)
    ).first()
    if latest_binding is None:
        return []
    assignment_version, task_version = latest_binding
    return list(
        session.scalars(
            select(AIModelAssignment)
            .where(
                AIModelAssignment.task_id == task_id,
                AIModelAssignment.assignment_version == assignment_version,
                AIModelAssignment.task_version == task_version,
            )
            .order_by(AIModelAssignment.id)
        ).all()
    )


def recompose_model_assignments(
    session: Session,
    task: Task,
    routing_decisions: Iterable[RoutingDecision],
    *,
    team_plan: AITeamPlan | None = None,
    task_version: int | None = None,
    routing_source: str = "routing_decision",
) -> list[AIModelAssignment]:
    """Persist immutable capability assignments, versioning only semantic route changes."""
    if task.id is None:
        raise ValueError("Task must be persisted before model assignment.")
    if team_plan is None or team_plan.id is None:
        raise ValueError("A persisted AI Team plan is required for model assignment.")
    if team_plan.task_id != task.id:
        raise ValueError("The AI Team plan must belong to the assigned task.")
    effective_task_version = task_version if task_version is not None else task.task_version
    if effective_task_version < 1:
        raise ValueError("task_version must be at least 1.")
    if effective_task_version < task.task_version:
        raise ValueError("task_version cannot regress below the persisted task version.")
    if not _SAFE_CODE.fullmatch(routing_source):
        raise ValueError("routing_source must be a safe identifier.")

    decisions = list(routing_decisions)
    if not decisions:
        raise ValueError("At least one routing decision is required for model assignment.")
    if any(
        decision.id is None
        or decision.task_id != task.id
        or decision.team_plan_id != team_plan.id
        for decision in decisions
    ):
        raise ValueError("Every routing decision must be persisted for the assigned task and AI Team plan.")
    capability_ids = [decision.capability_id for decision in decisions]
    if len(set(capability_ids)) != len(capability_ids):
        raise ValueError("Only one routing decision per capability may be assigned.")
    payloads = _assignment_payloads(session, decisions, routing_source)
    snapshot_hash = _routing_snapshot_hash(payloads)
    current = latest_model_assignments(session, task.id)
    same_snapshot = bool(current and current[0].routing_snapshot_hash == snapshot_hash)
    assignment_version = (
        current[0].assignment_version
        if same_snapshot
        else current[0].assignment_version + 1 if current else 1
    )
    existing_binding = list(
        session.scalars(
            select(AIModelAssignment)
            .where(
                AIModelAssignment.task_id == task.id,
                AIModelAssignment.assignment_version == assignment_version,
                AIModelAssignment.task_version == effective_task_version,
            )
            .order_by(AIModelAssignment.id)
        ).all()
    )
    if existing_binding:
        if (
            {item.routing_snapshot_hash for item in existing_binding} != {snapshot_hash}
            or {item.role for item in existing_binding} != {payload["role"] for payload in payloads}
        ):
            raise ValueError("Task version already has a different routing snapshot.")
        if team_plan is not None:
            team_plan.assignment_version = assignment_version
            team_plan.task_version = effective_task_version
            team_plan.routing_snapshot_hash = snapshot_hash
        session.flush()
        return existing_binding

    assignments: list[AIModelAssignment] = []
    for payload in payloads:
        assignment = AIModelAssignment(
            task_id=task.id,
            team_plan_id=team_plan.id if team_plan is not None else None,
            task_version=effective_task_version,
            assignment_version=assignment_version,
            role=payload["role"],
            capability=payload["capability"],
            routing_snapshot_hash=snapshot_hash,
            assigned_model_id=payload["assigned_model"].id if payload["assigned_model"] else None,
            fallback_model_id=payload["fallback_model"].id if payload["fallback_model"] else None,
            assignment_reason=payload["assignment_reason"],
            routing_source=payload["routing_source"],
            availability_at_composition=payload["availability_at_composition"],
            fallback_allowed=payload["fallback_allowed"],
            fallback_reason=payload["fallback_reason"],
            independence_required=payload["independence_required"],
            independence_status=payload["independence_status"],
            independent_from_roles=json.dumps(payload["independent_from_roles"], separators=(",", ":")),
        )
        session.add(assignment)
        assignments.append(assignment)
    task.task_version = max(task.task_version, effective_task_version)
    if team_plan is not None:
        team_plan.assignment_version = assignment_version
        team_plan.task_version = effective_task_version
        team_plan.routing_snapshot_hash = snapshot_hash
    session.flush()
    return assignments


def assignment_binding(assignments: Iterable[AIModelAssignment]) -> dict[str, Any]:
    rows = list(assignments)
    if not rows:
        return {"assignment_version": 0, "task_version": 1, "routing_snapshot_hash": ""}
    versions = {row.assignment_version for row in rows}
    task_versions = {row.task_version for row in rows}
    hashes = {row.routing_snapshot_hash for row in rows}
    if len(versions) != 1 or len(task_versions) != 1 or len(hashes) != 1:
        raise ValueError("Assignments do not belong to one routing snapshot.")
    return {
        "assignment_version": versions.pop(),
        "task_version": task_versions.pop(),
        "routing_snapshot_hash": hashes.pop(),
    }


def assignment_snapshot(assignment: AIModelAssignment) -> dict[str, Any]:
    """Serialize one assignment using only bounded registry and routing evidence."""
    try:
        independent_from_roles = json.loads(assignment.independent_from_roles or "[]")
    except (TypeError, json.JSONDecodeError):
        independent_from_roles = []
    if not isinstance(independent_from_roles, list):
        independent_from_roles = []
    return {
        "id": assignment.id,
        "role": assignment.role,
        "capability": assignment.capability,
        "assigned_model": (
            model_registry_snapshot(assignment.assigned_model) if assignment.assigned_model else None
        ),
        "assignment_reason": assignment.assignment_reason,
        "routing_source": assignment.routing_source,
        "availability_at_composition": assignment.availability_at_composition,
        "fallback_allowed": assignment.fallback_allowed,
        "fallback_model": (
            model_registry_snapshot(assignment.fallback_model) if assignment.fallback_model else None
        ),
        "fallback_reason": assignment.fallback_reason,
        "independence_required": assignment.independence_required,
        "independence_status": assignment.independence_status,
        "independent_from_roles": independent_from_roles,
        "assignment_version": assignment.assignment_version,
        "task_version": assignment.task_version,
        "routing_snapshot_hash": assignment.routing_snapshot_hash,
        "created_at": assignment.created_at.isoformat(),
    }


def provider_state_hash(models: Iterable[AIModel]) -> str:
    """Hash routing-relevant provider/model state without diagnostics or credentials."""
    snapshots = []
    for model in models:
        registry = model_registry_snapshot(model)
        snapshots.append(
            {
                "stable_id": registry["stable_id"],
                "provider": registry["provider"],
                "provider_model_id": registry["provider_model_id"],
                "execution_adapter": registry["execution_adapter"],
                "capabilities": registry["capabilities"],
                "configuration_status": registry["configuration_status"],
                "availability_status": registry["availability_status"],
                "invocation_mode": registry["invocation_mode"],
            }
        )
    encoded = json.dumps(
        sorted(snapshots, key=lambda item: str(item["stable_id"])),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bind_assignment_snapshot(target: object, assignments: Iterable[AIModelAssignment]) -> None:
    """Bind a pack or run model to the exact assignment snapshot it executes."""
    binding = assignment_binding(assignments)
    for field, value in binding.items():
        if not hasattr(target, field):
            raise TypeError(f"Target does not support assignment binding field {field}.")
        setattr(target, field, value)


def _safe_text(value: str, field: str, *, maximum: int = 500) -> str:
    result = str(value or "").strip()
    if len(result) > maximum or _SECRET_MATERIAL.search(result):
        raise ValueError(f"{field} contains unsafe diagnostic material.")
    return result


def _safe_fingerprint(value: str, field: str) -> str:
    result = str(value or "")
    if result and not _SHA256.fullmatch(result):
        raise ValueError(f"{field} must be an empty value or a SHA-256 fingerprint.")
    return result


def _safe_metadata(
    value: Mapping[str, Any] | None,
    field: str,
    schema: Mapping[str, str],
) -> str:
    payload = dict(value or {})
    unknown = set(payload) - set(schema)
    if unknown:
        raise ValueError(f"{field} contains unsupported fields: {', '.join(sorted(unknown))}.")
    for key, item in payload.items():
        expected = schema[key]
        if expected == "bool" and type(item) is not bool:
            raise ValueError(f"{field}.{key} must be a boolean.")
        if expected in {"signed_int", "nonnegative_int", "status_code"} and type(item) is not int:
            raise ValueError(f"{field}.{key} must be an integer.")
        if expected == "signed_int" and not -(2**31) <= item < 2**31:
            raise ValueError(f"{field}.{key} is outside the supported integer range.")
        if expected == "nonnegative_int" and not 0 <= item <= 10**12:
            raise ValueError(f"{field}.{key} must be a bounded nonnegative integer.")
        if expected == "status_code" and not 0 <= item <= 999:
            raise ValueError(f"{field}.{key} must be a bounded status code.")
        if expected == "nonnegative_number" and (
            type(item) not in {int, float}
            or not math.isfinite(item)
            or not 0 <= item <= 10**12
        ):
            raise ValueError(f"{field}.{key} must be a bounded nonnegative number.")
        if expected == "sha256" and (not isinstance(item, str) or not _SHA256.fullmatch(item)):
            raise ValueError(f"{field}.{key} must be a SHA-256 fingerprint.")
        if expected == "safe_text" and (
            not isinstance(item, str)
            or len(item) > 500
            or _SECRET_MATERIAL.search(item)
        ):
            raise ValueError(f"{field}.{key} must be bounded non-secret text.")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _real_invocation_proof_error(
    model: AIModel,
    actual_invoked_model_identifier: str,
    process_evidence: Mapping[str, Any] | None,
    provider_evidence: Mapping[str, Any] | None,
    *,
    require_current_readiness: bool = True,
    require_codex_process_proof: bool = False,
) -> str | None:
    provider = model.provider
    if provider.kind != "model":
        return "A successful real invocation requires a model provider."
    if require_current_readiness and (
        not provider.enabled or provider.status not in ELIGIBLE_STATUSES
    ):
        return "A successful real invocation requires an enabled and healthy model provider."
    if require_current_readiness and (
        model.status in {"blocked", "disabled"}
        or model.configuration_status == "disabled"
        or model.availability_status == "disabled"
    ):
        return "A disabled model cannot record a successful real invocation."
    if not process_evidence or process_evidence.get("process_observed") is not True:
        return "A successful real invocation requires observed process evidence."
    if process_evidence.get("runtime_interrupted") is True:
        return "A runtime-interrupted process cannot verify a successful real invocation."
    exit_code = process_evidence.get("exit_code")
    if type(exit_code) is not int or exit_code != 0:
        return "A successful real invocation requires zero process exit evidence."
    if not provider_evidence:
        return "A successful real invocation requires bounded provider evidence."
    configured_identifier = str(model.provider_model_id or "")
    if require_codex_process_proof:
        if (
            not configured_identifier
            or not _SAFE_IDENTIFIER.fullmatch(configured_identifier)
            or provider_evidence.get("requested_model_identifier_match") is not True
        ):
            return "A successful Codex invocation requires the exact approved requested model argument."
    else:
        if not _SAFE_IDENTIFIER.fullmatch(actual_invoked_model_identifier):
            return "A successful real invocation requires a safe actual model identifier."
        if require_current_readiness and configured_identifier != actual_invoked_model_identifier:
            return "A successful real invocation requires the exact configured provider model identifier."
        if provider_evidence.get("model_identifier_match") is not True:
            return "A successful real invocation requires matching model evidence."
    if provider_evidence.get("provider_response_observed") is True and not require_codex_process_proof:
        status_code = provider_evidence.get("status_code")
        if type(status_code) is not int or not 200 <= status_code < 300:
            return "A successful real invocation requires a successful provider status code."
        return None
    codex_process_proof = all(
        process_evidence.get(field) is True
        for field in (
            "codex_jsonl_observed",
            "codex_thread_started",
            "codex_turn_started",
            "codex_turn_completed",
            "codex_turn_verified",
            "model_argument_observed",
            "approved_pack_stdin_complete",
            "process_execution_verified",
        )
    )
    thread_fingerprint = process_evidence.get("thread_id_fingerprint")
    if not codex_process_proof or not isinstance(thread_fingerprint, str) or not _SHA256.fullmatch(
        thread_fingerprint
    ):
        return "A successful Codex invocation requires complete structured process evidence."
    return None


def _codex_run_capability_target(
    run: CodexRun,
    capability: str,
) -> tuple[int | None, int | None, int | None]:
    """Return the immutable Run target for one executable capability."""
    if capability == "coding":
        return (
            run.execution_assignment_id,
            run.execution_model_id,
            run.execution_provider_id,
        )
    if capability == "verification":
        return (
            run.verification_assignment_id,
            run.verification_model_id,
            run.verification_provider_id,
        )
    raise ValueError("Codex Run evidence supports only coding or verification capabilities.")


def _codex_run_capability_process(
    run: CodexRun,
    capability: str,
) -> tuple[bool, int | None, bool, bool, bool]:
    """Return process facts for the capability-specific invocation."""
    if capability == "coding":
        return (
            run.process_spawned,
            run.exit_code,
            run.timed_out,
            run.cancelled,
            run.output_truncated,
        )
    if capability == "verification":
        return (
            run.verification_process_spawned,
            run.verification_exit_code,
            run.verification_timed_out,
            run.verification_cancelled,
            run.verification_output_truncated,
        )
    raise ValueError("Codex Run evidence supports only coding or verification capabilities.")


def _run_target_accepts_evidence(
    evidence: AIModelInvocationEvidence,
    target_assignment_id: int | None,
    target_model_id: int | None,
    target_provider_id: int | None,
) -> bool:
    """Bind evidence to the capability-specific target or its approved fallback."""
    if (
        target_assignment_id is None
        or target_model_id is None
        or target_provider_id is None
        or evidence.assignment_id != target_assignment_id
    ):
        return False
    if evidence.configured_model_id == target_model_id:
        return evidence.configured_provider_id == target_provider_id
    return bool(
        evidence.assignment is not None
        and evidence.assignment.fallback_allowed
        and evidence.configured_model_id == evidence.assignment.fallback_model_id
    )


def is_verified_real_invocation(evidence: AIModelInvocationEvidence) -> bool:
    """Revalidate stored evidence before presenting it as a verified real invocation."""
    run_process_facts: tuple[bool, int | None, bool, bool, bool] | None = None
    if (
        evidence.invocation_mode != "real"
        or evidence.outcome != "succeeded"
        or evidence.timed_out
        or evidence.cancelled
        or evidence.output_truncated
        or evidence.configured_model is None
        or evidence.configured_provider is None
        or evidence.configured_provider.id != evidence.configured_provider_id
        or evidence.configured_model.provider_id != evidence.configured_provider_id
        or evidence.started_at is None
        or evidence.completed_at is None
        or evidence.completed_at < evidence.started_at
    ):
        return False
    if evidence.assignment_id is not None:
        if (
            evidence.assignment is None
            or evidence.task_id != evidence.assignment.task_id
            or evidence.assignment_version != evidence.assignment.assignment_version
            or evidence.capability != evidence.assignment.capability
            or evidence.configured_model_id
            not in {evidence.assignment.assigned_model_id, evidence.assignment.fallback_model_id}
        ):
            return False
    if evidence.codex_run_id is not None:
        if evidence.codex_run is None:
            return False
        try:
            target_assignment_id, target_model_id, target_provider_id = _codex_run_capability_target(
                evidence.codex_run,
                evidence.capability,
            )
            run_process_facts = _codex_run_capability_process(
                evidence.codex_run,
                evidence.capability,
            )
        except ValueError:
            return False
        if (
            not run_process_facts[0]
            or evidence.task_id != evidence.codex_run.task_id
            or evidence.assignment_version != evidence.codex_run.assignment_version
            or not _run_target_accepts_evidence(
                evidence,
                target_assignment_id,
                target_model_id,
                target_provider_id,
            )
            or evidence.codex_run.pack is None
            or evidence.codex_run.pack.task_id != evidence.codex_run.task_id
            or evidence.codex_run.pack.assignment_version != evidence.codex_run.assignment_version
            or evidence.codex_run.pack.task_version != evidence.codex_run.task_version
            or evidence.codex_run.pack.routing_snapshot_hash
            != evidence.codex_run.routing_snapshot_hash
        ):
            return False
        if evidence.assignment is not None and (
            evidence.assignment.task_version != evidence.codex_run.task_version
            or evidence.assignment.routing_snapshot_hash != evidence.codex_run.routing_snapshot_hash
        ):
            return False
    try:
        process_evidence = json.loads(evidence.process_evidence or "{}")
        provider_evidence = json.loads(evidence.provider_evidence or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(process_evidence, dict) or not isinstance(provider_evidence, dict):
        return False
    if run_process_facts is not None:
        _, run_exit_code, run_timed_out, run_cancelled, run_output_truncated = run_process_facts
        if (
            evidence.timed_out != run_timed_out
            or evidence.cancelled != run_cancelled
            or evidence.output_truncated != run_output_truncated
        ):
            return False
        if "exit_code" in process_evidence and process_evidence.get("exit_code") != run_exit_code:
            return False
    return _real_invocation_proof_error(
        evidence.configured_model,
        evidence.actual_invoked_model_identifier,
        process_evidence,
        provider_evidence,
        require_current_readiness=False,
        require_codex_process_proof=evidence.codex_run_id is not None,
    ) is None


def has_complete_verified_codex_run_evidence(
    session: Session,
    run: CodexRun,
) -> bool:
    """Require distinct, exact Coding and Verification proof for one Codex Run."""
    if run.id is None:
        return False
    required_assignments = {
        "coding": run.execution_assignment_id,
        "verification": run.verification_assignment_id,
    }
    if any(assignment_id is None for assignment_id in required_assignments.values()):
        return False
    verified_capabilities: set[str] = set()
    for evidence in session.scalars(
        select(AIModelInvocationEvidence).where(
            AIModelInvocationEvidence.codex_run_id == run.id,
            AIModelInvocationEvidence.capability.in_(required_assignments),
        )
    ).all():
        if (
            evidence.assignment_id == required_assignments[evidence.capability]
            and is_verified_real_invocation(evidence)
        ):
            verified_capabilities.add(evidence.capability)
    return verified_capabilities == set(required_assignments)


def record_model_invocation_evidence(
    session: Session,
    *,
    model: AIModel,
    capability: str,
    assignment_version: int,
    invocation_ref: str,
    invocation_mode: str,
    outcome: str,
    actual_invoked_model_identifier: str,
    assignment: AIModelAssignment | None = None,
    task_id: int | None = None,
    codex_run_id: int | None = None,
    process_evidence: Mapping[str, Any] | None = None,
    provider_evidence: Mapping[str, Any] | None = None,
    usage_metadata: Mapping[str, Any] | None = None,
    request_fingerprint: str = "",
    response_fingerprint: str = "",
    duration_ms: int | None = None,
    timed_out: bool = False,
    cancelled: bool = False,
    output_truncated: bool = False,
    error_category: str = "",
    diagnostic_code: str = "",
    safe_summary: str = "",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> AIModelInvocationEvidence:
    """Record bounded invocation proof; raw prompts, outputs, tokens, and credentials are not accepted."""
    if invocation_mode not in INVOCATION_MODES:
        raise ValueError("invocation_mode must be real, simulated, manual, or unavailable.")
    if outcome not in INVOCATION_OUTCOMES:
        raise ValueError("Unsupported invocation outcome.")
    if assignment_version < 1:
        raise ValueError("assignment_version must be at least 1.")
    if not _SAFE_CODE.fullmatch(capability):
        raise ValueError("capability must be a safe identifier.")
    if len(invocation_ref) > 120 or not _SAFE_IDENTIFIER.fullmatch(invocation_ref):
        raise ValueError("invocation_ref must be a safe non-secret identifier.")
    if actual_invoked_model_identifier and not _SAFE_IDENTIFIER.fullmatch(actual_invoked_model_identifier):
        raise ValueError("actual_invoked_model_identifier must be empty or a safe identifier.")
    _safe_text(invocation_ref, "invocation_ref", maximum=120)
    if actual_invoked_model_identifier:
        _safe_text(
            actual_invoked_model_identifier,
            "actual_invoked_model_identifier",
            maximum=240,
        )
    if error_category and not _SAFE_CODE.fullmatch(error_category):
        raise ValueError("error_category must be a safe diagnostic code.")
    if diagnostic_code and not _SAFE_CODE.fullmatch(diagnostic_code):
        raise ValueError("diagnostic_code must be a safe diagnostic code.")
    if duration_ms is not None and duration_ms < 0:
        raise ValueError("duration_ms cannot be negative.")
    if timed_out and outcome != "timed_out":
        raise ValueError("timed_out evidence must use the timed_out outcome.")
    if cancelled and outcome != "cancelled":
        raise ValueError("cancelled evidence must use the cancelled outcome.")
    if invocation_mode == "unavailable" and outcome == "succeeded":
        raise ValueError("An unavailable model cannot record a successful invocation.")
    verified_real = invocation_mode == "real" and outcome == "succeeded"
    if verified_real and output_truncated:
        raise ValueError("Truncated output cannot verify a successful real invocation.")
    if assignment is not None:
        if assignment.id is None:
            raise ValueError("Evidence assignment must be persisted.")
        if assignment.assigned_model_id != model.id and assignment.fallback_model_id != model.id:
            raise ValueError("Evidence model is not bound to the supplied assignment.")
        if assignment.assignment_version != assignment_version or assignment.capability != capability:
            raise ValueError("Evidence does not match the supplied assignment version and capability.")
        if task_id is not None and task_id != assignment.task_id:
            raise ValueError("Evidence task does not match the supplied assignment.")
        task_id = assignment.task_id
    if codex_run_id is not None:
        codex_run = session.get(CodexRun, codex_run_id)
        if codex_run is None:
            raise ValueError("Evidence Codex run does not exist.")
        try:
            target_assignment_id, target_model_id, target_provider_id = _codex_run_capability_target(
                codex_run,
                capability,
            )
            (
                process_spawned,
                process_exit_code,
                process_timed_out,
                process_cancelled,
                process_output_truncated,
            ) = _codex_run_capability_process(codex_run, capability)
        except ValueError as exc:
            raise ValueError(
                "Evidence Codex run does not match an executable coding or verification target."
            ) from exc
        if (
            codex_run.pack is None
            or not process_spawned
            or codex_run.pack.task_id != codex_run.task_id
            or codex_run.pack.assignment_version != codex_run.assignment_version
            or codex_run.pack.task_version != codex_run.task_version
            or codex_run.pack.routing_snapshot_hash != codex_run.routing_snapshot_hash
        ):
            raise ValueError("Evidence Codex run does not match its exact approved pack binding.")
        if task_id is None:
            task_id = codex_run.task_id
        if codex_run.task_id != task_id or codex_run.assignment_version != assignment_version:
            raise ValueError("Evidence Codex run does not match the task and assignment version.")
        if assignment is not None and (
            codex_run.task_version != assignment.task_version
            or codex_run.routing_snapshot_hash != assignment.routing_snapshot_hash
            or target_assignment_id != assignment.id
        ):
            raise ValueError("Evidence Codex run does not match the exact assignment snapshot.")
        model_matches_target = (
            model.id == target_model_id and model.provider_id == target_provider_id
        )
        model_matches_approved_fallback = bool(
            assignment is not None
            and assignment.fallback_allowed
            and model.id == assignment.fallback_model_id
        )
        if not model_matches_target and not model_matches_approved_fallback:
            raise ValueError("Evidence model is outside the queued execution target and approved fallback.")
        if (
            timed_out != process_timed_out
            or cancelled != process_cancelled
            or output_truncated != process_output_truncated
        ):
            raise ValueError("Evidence outcome flags do not match the persisted Codex run.")
        if process_evidence and "exit_code" in process_evidence:
            if process_evidence.get("exit_code") != process_exit_code:
                raise ValueError("Evidence exit code does not match the persisted Codex run.")
        if verified_real and (
            process_exit_code != 0
            or process_timed_out
            or process_cancelled
            or process_output_truncated
        ):
            raise ValueError("Persisted Codex run facts do not support a successful real invocation.")
    if verified_real:
        proof_error = _real_invocation_proof_error(
            model,
            actual_invoked_model_identifier,
            process_evidence,
            provider_evidence,
            require_codex_process_proof=codex_run_id is not None,
        )
        if proof_error:
            raise ValueError(proof_error)

    started = started_at or utc_now()
    completed = completed_at or utc_now()
    if completed < started:
        raise ValueError("completed_at cannot precede started_at.")
    safe_summary_value = _safe_text(safe_summary, "safe_summary")
    evidence = AIModelInvocationEvidence(
        invocation_ref=invocation_ref,
        capability=capability,
        assignment_version=assignment_version,
        configured_model_id=model.id,
        configured_provider_id=model.provider_id,
        assignment_id=assignment.id if assignment is not None else None,
        task_id=task_id,
        codex_run_id=codex_run_id,
        actual_invoked_model_identifier=actual_invoked_model_identifier,
        invocation_mode=invocation_mode,
        outcome=outcome,
        process_evidence=_safe_metadata(process_evidence, "process_evidence", PROCESS_EVIDENCE_SCHEMA),
        provider_evidence=_safe_metadata(provider_evidence, "provider_evidence", PROVIDER_EVIDENCE_SCHEMA),
        timed_out=timed_out,
        cancelled=cancelled,
        output_truncated=output_truncated,
        usage_metadata=_safe_metadata(usage_metadata, "usage_metadata", USAGE_METADATA_SCHEMA),
        error_category=error_category,
        request_fingerprint=_safe_fingerprint(request_fingerprint, "request_fingerprint"),
        response_fingerprint=_safe_fingerprint(response_fingerprint, "response_fingerprint"),
        duration_ms=duration_ms,
        diagnostic_code=diagnostic_code,
        safe_summary=safe_summary_value,
        started_at=started,
        completed_at=completed,
    )
    session.add(evidence)
    model.last_invocation_outcome = outcome
    model.safe_diagnostic = safe_summary_value or diagnostic_code
    if verified_real:
        model.evidence_status = "verified"
        model.evidence_source = "invocation_evidence"
        model.last_verified_at = completed
        model.configuration_status = "configured"
        model.availability_status = "available"
        if model.status not in ELIGIBLE_STATUSES:
            model.status = "healthy"
    elif invocation_mode == "simulated":
        model.evidence_status = "simulated"
        model.evidence_source = "simulation_record"
    elif invocation_mode == "manual":
        model.evidence_status = "manual"
        model.evidence_source = "manual_record"
    else:
        model.evidence_status = "recorded"
        model.evidence_source = "invocation_evidence"
    session.flush()
    return evidence
