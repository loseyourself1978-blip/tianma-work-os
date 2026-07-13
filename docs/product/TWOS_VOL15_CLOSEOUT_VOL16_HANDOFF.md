# TWOS Vol.15 Closeout and Vol.16 Handoff

## Accepted Source Identity

- Branch: `main`
- Cleaned MVP-15 commit: `9eb69c58a3cb38849947a58d22cb726e048a2dc8`
- Runtime version: `0.15.1`
- Validation: `.venv/bin/python -m pytest -q` passed 9 tests.

## Vol.15 Accepted Baseline

TWOS now provides one LDD / 2026WC / TWOS command center with a real local backend and same-origin API, Owner authentication, SQLite persistence, recurring scheduler, worker runtime, deterministic acceptance, audit trail, and Compact Sync.

The AI orchestration baseline includes a capability registry, provider/model registry, task-driven AI Team composition, explainable routing, persisted unavailable decisions, honest unconfigured provider states, and backend policy denial for `live_trade` and `live_bet`.

## Deferred Productization UX Debt

- Move Owner login into the global header; separate first-time Owner creation from normal login.
- Show explicit logged-in/logged-out feedback and prevent repeated pending submissions.
- Keep New task, task fields, Save, Recompose, Generate Pack, and Execute in one operation surface.
- Show only the current operation and verification path by default.
- Keep provider, model, runtime, audit, risk, and debug details under Advanced.

## Fixed DUXD Rules

- Hide complexity, not capability. Owner sees decisions; developer sees internals.
- Acceptance is a product feature.
- Every capability requires backend capability + Owner operation path + visible result + visible acceptance evidence + persistence.
- Only the current milestone operation and verification content is visible by default.

## Latest Project Feedback

### 2026WC

- Spain 2-1 Belgium produced `+130.89 / +16.36%`; the profit did not validate every hedge ticket.
- In single-match mode, use no more than two core markets unless a third materially improves an uncovered normal outcome.
- A ticket that wins only alongside a cheaper main ticket is not valid protection.
- Keep primary exact-score misses separate from defensive-score hits.

### LDD / DUXD

- SMH 1 share at 600 became the first clean H2 Strategy ticket.
- After fill, switch from cancellation handling to Post-fill Risk Handling.
- Full Market Scan remains mandatory in Pre / Mid / Post; scan SNDK / MU / DRAM separately.
- Retain both regular-close and after-hours quotes.
- Replace SMH only with a clearly superior candidate; do not stack redundant tickets.
- The LDD AI Board remains limited to market analysis and risk execution roles.
- TWOS has no live broker-order authority.

## Vol.16 Identity

- Tianma Work OS Vol.16
- TWOS 1.0 Productization Sprint 1
- Self-Hosting Workbench
- Internal release target: `2026-07-30`; do not display this date in product UI.

## First Product Loop

Owner -> Create TWOS development task -> Compose AI Team -> Generate Codex Instruction Pack -> Approve Codex execution -> Run in isolated worktree -> Collect structured result -> Generate Owner Acceptance checklist -> Owner accepts or rejects -> Generate Compact Sync.

## Hard Boundaries

- No fake integration, silent auto-send, automatic merge, or automatic push.
- Codex execution requires explicit Owner approval by default.
- No live trading or live betting execution.
- Sprint 1 must use an isolated worktree and Git-derived evidence for every Codex run.
