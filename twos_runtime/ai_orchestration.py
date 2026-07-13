from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AICapability, AIModel, AITeamPlan, AITeamPlanItem, Provider, RoutingDecision, Task


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
    requested = capability_override or _default_capabilities(task, risk_level)
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
    candidates: list[tuple[tuple[int, int, int, int, int], AIModel]] = []
    for model in compatible_models:
        provider = model.provider
        if not provider.enabled:
            continue
        if provider.status not in ELIGIBLE_STATUSES or model.status not in ELIGIBLE_STATUSES:
            continue
        if capability.name not in decode_capability_tags(model):
            continue
        score = _routing_score(
            provider,
            model,
            urgency=urgency,
            cost_sensitivity=cost_sensitivity,
            latency_sensitivity=latency_sensitivity,
        )
        candidates.append((score, model))

    candidates.sort(key=lambda item: item[0])
    selected = candidates[0][1] if candidates else None
    fallback = candidates[1][1] if len(candidates) > 1 else None
    requested = requested_capabilities or [capability.name]
    if selected:
        reason = (
            f"Selected the highest-ranked eligible model for {capability.name}; provider is "
            f"{selected.provider.status}, model is {selected.status}, and the routing decision is complete."
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
        if compatible_models and all(provider.status == "unconfigured" for provider in compatible_providers):
            reason = "No configured and healthy provider is available for the requested capabilities."
            fallback_reason = "No fallback is available because all compatible providers are unconfigured."
            next_action = "Configure and verify at least one compatible provider, then recompose the AI Team."
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
