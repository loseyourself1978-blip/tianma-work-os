# Signal Command Layer Spec v0.1

Status: Draft for Vol.3 Runtime MVP

## Purpose

The Signal Command Layer converts raw events into structured signals that Tianma Work OS can evaluate, prioritize, and route.

## Runtime Position

```text
Project Memory
-> Multi-Source Signal Intake
-> AI Board Decision
-> Decision-to-Command Routing
```

## Signal Sources

Vol.3 supports manual records from:

- User instruction.
- LDD review.
- Codex execution result.
- GitHub issue or commit context.
- External observation entered by a human.

No external API connection is included.

## Signal Intake Fields

Each signal should include:

- `signal_id`
- `project_id`
- `source_type`
- `source_ref`
- `received_at`
- `urgency`
- `priority`
- `summary`
- `payload`
- `routing_hint`

## Priority Model

Suggested priority values:

- `p0`
- `p1`
- `p2`
- `p3`

Suggested urgency values:

- `low`
- `medium`
- `high`
- `critical`

## Routing Hints

Routing hints help decide the next step:

- `project_memory`
- `ai_board`
- `decision_command`
- `ldd_cockpit`
- `manual_review`
- `backlog`

## Relationship to TWOS-029

This spec is the first lightweight implementation surface for TWOS-029. It does not implement automated ingestion, classification models, or external integrations.

