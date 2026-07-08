# TWOS 1.0 Workbench Architecture Map v0.1

## Purpose

This map defines the build-directed product shape for the TWOS 1.0 Unified AI Team Workbench.
It prepares the next product-code milestone, the Unified Project Workbench UI, without starting UI implementation or any live integration work.

| Field | Standard |
|---|---|
| Scope | Product architecture document only |
| Baseline | Vol.14 gate and memory-control baseline at `d5d1ba7fc22794404816f238553f8ee03b73a8fd` |
| Next milestone enabled | Unified Project Workbench UI |
| Current activation | Static planning only |
| Non-activation | No product code, backend, API, scheduler, schema, fixture, validator, protocol expansion, decorative role theater, live tool integration, auto-send, trading execution, betting execution, or fake model-provider integration |

## Unified Command Center

The TWOS 1.0 Workbench is a single command center with three first-class project lanes:

| Module | Purpose | Primary Surface | Boundary |
|---|---|---|---|
| Command Center Shell | Show all active work, selected project, intake queue, board status, and handoff state | Global header, project switcher, sync inbox, task lane summary, acceptance queue | Static UI only until separately approved |
| LDD Lane | Preserve LDD as the trading seed battlefield for memory, risk, review, and command discipline | LDD status card, source-of-truth panel, task queue, review notes, sync handoff | No live market data, broker connection, Binance connection, order placement, or account mutation |
| 2026WC Lane | Preserve 2026WC as the long-running prediction and review seed project | Match-day workbench, prediction task queue, result review, source notes, sync handoff | No live odds feed, bookmaker integration, betting execution, or auto-published prediction |
| TWOS Product Development Lane | Coordinate TWOS requirements, UI milestones, docs/code boundary, and acceptance evidence | Product backlog, milestone board, decision log, acceptance checklist, release sync | No hidden implementation or roadmap phase activation |
| Cross-Project Sync | Route record-only updates across LDD, 2026WC, and TWOS Product Development | Sync inbox, classification chips, handoff preview, copy/export action | Manual copy only; no auto-send or background sync |

## AI Team And AI Board Model

The AI team and AI Board are simulated control models until real integrations exist. In the next UI milestone, roles may be shown as labeled review lenses and assignment targets, but they must not imply autonomous agents, provider routing, or real multi-model execution.

| Layer | Composition | Product Meaning | Required Boundary |
|---|---|---|---|
| AI Team | Commander, Strategist, Research Analyst, Data Verifier, Risk Officer, Product / Solution Designer, Execution Secretary, Review Officer, Meta-Strategist | Role-based work decomposition and review | Simulated until real role execution exists |
| AI Board Gate | Source Keeper, First-Principles Diagnoser, DUXD Officer, UX Minimalist, Acceptance Officer, Boundary Officer, Commander | Pre-work control plane for source, scope, acceptance, and boundary checks | Simulated gate state, not autonomous authority |
| Assignment Model | One or more roles can be attached to a task as responsible review lenses | Helps the user see who should inspect or advance the task | No fake Gemini, Claude, or other provider claims |
| Evidence Model | Each role output must cite a source, assumption, or pending question | Prevents decorative role labels from replacing evidence | Empty evidence means hold or unresolved |
| Approval Model | The user remains final approver for strategy, acceptance, and external action | Preserves human strategy and accountability | No approval bypass |

## Task Lifecycle

The workbench lifecycle is:

```text
intake -> assignment -> execution placeholder -> review -> acceptance -> sync
```

| Stage | UI Responsibility | Stored Meaning | Boundary |
|---|---|---|---|
| Intake | Capture a user request, sync note, source update, or product requirement | A new candidate task or record-only sync | Does not execute anything |
| Assignment | Attach project lane, priority, status, role lenses, and owner placeholder | A planned responsibility map | Does not contact a model or external worker |
| Execution Placeholder | Show the intended execution route and manual next step | A disabled or manual action slot | No backend, scheduler, API, or automation |
| Review | Collect role review, source check, risk check, and boundary check | Evidence for proceed, revise, hold, or block | No decorative approval without evidence |
| Acceptance | Record user-facing acceptance criteria and final Commander verdict | The acceptance state for the task | User approval remains required |
| Sync | Generate a manual handoff block for project memory or external tools | Copyable sync text only | No auto-send to calendar, Outlook, IM, task tools, broker, or betting service |

## Tool-Routing Slots

Tool routing in TWOS 1.0 is a product surface contract only. The UI may reserve slots and show disabled/manual actions, but no real integration exists in this phase.

| Slot | Future Intent | Current Product Surface | Explicit Non-Integration |
|---|---|---|---|
| Codex | Route implementation or documentation work after a gate passes | Manual Codex handoff preview and copy action | No automatic Codex invocation |
| Calendar | Reserve time, reminders, or review windows | Disabled schedule slot with manual note | No calendar API, event creation, or reminder scheduler |
| Outlook | Draft email-style status or handoff text | Disabled Outlook draft slot with copyable text | No email send, mailbox read, or account connection |
| IM | Prepare short team updates or approval pings | Disabled IM draft slot with copyable text | No Slack, Teams, WeChat, or other message send |
| Task Tools | Create future task cards in project systems | Disabled task-export slot with manual task text | No Jira, Linear, GitHub Issues, or task API write |

## Product Surface Contract For Unified Project Workbench UI

The next UI milestone should implement only the surface required to make this architecture visible and usable.

| Surface | Required In UI | Must Not Include |
|---|---|---|
| Project Switcher | LDD, 2026WC, and TWOS Product Development lanes | Hidden project creation workflow unless separately approved |
| Command Center Summary | Cross-project status, intake count, review count, acceptance count, sync-ready count | Live metrics, background polling, or external status claims |
| Intake Panel | Paste/manual entry area, source tag, project lane, record-only or task classification | Automatic source ingestion |
| AI Board Panel | Simulated role rows, gate status, evidence fields, Commander verdict | Fake provider names, autonomous role execution, or decorative role scripts |
| Task Board | Lifecycle columns from intake through sync | Scheduler, worker queue, or backend persistence claims |
| Execution Route Panel | Codex, calendar, Outlook, IM, and task tool slots as disabled/manual routes | Real connection, token storage, send buttons, or API calls |
| Acceptance Panel | Criteria, review evidence, boundary confirmation, user approval state | Approval bypass or automatic acceptance |
| Sync Panel | Manual handoff text for LDD, 2026WC, or TWOS Product Development | Auto-send, auto-commit, auto-trade, auto-bet, or remote mutation |

## Acceptance For This Architecture Map

- LDD, 2026WC, and TWOS Product Development are represented as unified command center modules.
- AI Team and AI Board behavior is explicitly simulated until real integrations exist.
- The lifecycle is defined as intake -> assignment -> execution placeholder -> review -> acceptance -> sync.
- Codex, calendar, Outlook, IM, and task-tool routes are reserved as disabled/manual slots only.
- The next product-code milestone is clearly enabled as Unified Project Workbench UI.
- No live trading, betting, backend, scheduler, protocol, schema, fixture, validator, decorative role theater, or fake provider integration is authorized.
