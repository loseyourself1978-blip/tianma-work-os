# TWOS AI Board Gate Protocol v0.1

## First-Principles Loop

What is the essence of the problem?
Work must not begin until the AI Board decision process is visible.

Why are we doing this?
TWOS needs a trustworthy pre-work control plane for Codex instructions, new requirements, design analysis, and sync intake.

Can we solve it?
Yes.

How do we solve it?
Use a compact gate with board-role audit rows, status, Commander decision, and next action.

Is there a better way?
Yes: keep the gate short enough to use every time.

There is no best, only better.

## Gate Format

Each AI Board Gate must show:

- Task.
- Gate Status.
- Board checks.
- Commander Decision.
- Next Action.

Board check rows must include:

- Role.
- Discussion / Audit.
- Decision.
- Status.

Required board roles:

- Source Keeper.
- First-Principles Diagnoser.
- DUXD Officer.
- UX Minimalist.
- Acceptance Officer.
- Boundary Officer.
- Commander.

## Gate States

- `PASS`: work may proceed.
- `REVISE`: refine the task before work proceeds.
- `BLOCKED`: do not proceed.
- `RECORD ONLY`: record the sync/intake, no implementation.
- `ANALYZE FIRST`: discuss and classify before implementation.
- `WORKFLOW-LEVEL UPDATE`: update process/memory, not direct execution.
- `IMPLEMENTATION REQUESTED`: implementation may be considered only after explicit approval and Commander PASS.

## Before Codex Gate

Used before generating Codex instructions or beginning implementation.

Minimum checks:

- Source Keeper: what existing source should be used first?
- First-Principles Diagnoser: what is the essence?
- DUXD Officer: are we adopting existing first?
- UX Minimalist: is this simpler than the mature baseline?
- Acceptance Officer: how will the user validate?
- Boundary Officer: are we faking capability?
- Commander: can Codex proceed?

Rule:

Codex instructions may only be generated after `Commander Decision: PASS`.

## New Requirement Gate

Used when the user gives new product/design feedback.

Default state: `ANALYZE FIRST`.

Minimum checks:

- Source Keeper identifies the current accepted source.
- First-Principles Diagnoser separates essence from proposed solution.
- DUXD Officer identifies the real user pain or experience.
- UX Minimalist checks whether the current mature pattern should be copied.
- Acceptance Officer defines the user acceptance path.
- Boundary Officer blocks fake capability.
- Commander decides PASS / REVISE / BLOCKED.

## Sync Intake Gate

Used when the user provides an LDD / 2026WC / TWOS sync.

Possible states:

- `RECORD ONLY`
- `WORKFLOW-LEVEL UPDATE`
- `IMPLEMENTATION REQUESTED`
- `BLOCKED`

Default rule:

Implementation: No unless separately approved.

Sync intake must clarify whether the sync is:

- source memory;
- workflow learning;
- project state update;
- implementation request;
- blocked due to missing permission or forbidden scope.

## Commander Decision Rules

- PASS: proceed with the next scoped action.
- REVISE: refine task, source, acceptance path, or boundary first.
- BLOCKED: stop until user input or external state changes.
- RECORD: record source/sync only.
- WORKFLOW-LEVEL UPDATE: update process memory without implementation.

## DUXD Rule

DUXD = Deep User Experience Development / 用户深度体验开发模式.

Execution rule:

1. Adopt existing.
2. Adapt lightly.
3. Invent only if needed.

Use real high-intensity user projects as seed battlefields. Convert real pain, friction, errors, and good experiences into product requirements.

## Boundary Rule

The gate must not imply:

- fake model routing;
- hidden execution;
- live data access;
- backend automation;
- scheduler activation;
- broker or betting execution;
- schema/validator/framework work unless explicitly approved.

## Vol.13 Accepted Examples

Before Codex Gate example:

- Task: Generate Stage C v1.6 Codex instruction.
- Result: PASS.
- Reason: existing 2026WC project page screenshots and full v4.4 report were source-of-truth; the task was to copy existing project UX into TWOS.

Sync Intake Gate example:

- Task: LDD / TWOS Sync | FactorMiner Intake.
- Result: WORKFLOW-LEVEL UPDATE / RECORD.
- Reason: FactorMiner was an external mechanism source for workflow learning, not a direct trading signal or implementation request.
