# View Model Quality Gates v0.1

## Purpose

Vol.5 Phase 5.4 adds semantic quality gates for `cockpit/ldd/view_model.json`.
JSON Schema confirms structure; these gates confirm that the generated state is
internally consistent, current, and safe for future read-only consumers.

## Scope

The validator reads local cockpit artifacts only:

- `cockpit/ldd/view_model.json`
- `cockpit/ldd/manifest.json`
- `cockpit/ldd/latest_state.json`
- `cockpit/ldd/runtime_timeline.json`

It does not call external services or change runtime records.

## Quality Gates

1. Checkpoint consistency
   - The view model, manifest, and latest state must agree on
     `2026-06-08T08:44:00+08:00`.
2. Portfolio mode
   - The current mode must remain `core_position_defense_mode`.
3. Timeline consistency
   - Event counts must match across the view model, latest state, and runtime
     timeline.
   - Timeline warnings must remain zero.
4. Closed-position consistency
   - SOXL, UGL, and INTC must remain `closed_position`, have zero quantity, and
     stay out of active positions.
5. No-reentry and prohibition safety
   - Represented cleanup, inverse, and leveraged products must not appear as buy
     candidates.
6. Remaining leveraged-risk role
   - GGLL must remain the main remaining leveraged ETF risk valve.
7. Core-risk role
   - NVDA must remain the main core-risk watch.
8. GLD rule semantics
   - GLD must use ordinary concentration and risk-line protection, not stale
     UGL-linked protection.
9. Crypto defense
   - Binance remains USDT-dominant.
   - BTC buyback remains inactive below the 75,500-76,000 trigger.
   - The ZEC grid remains closed, profit-locked, and prohibited from reopening.
10. Data quality
    - Required view-model sections must exist.
    - Missing optional fields may produce warnings.
    - Missing required fields or contradictory state blocks validation.
11. UI safety
    - No credentials may be exposed.
    - No live market or external API connection may be implied.
    - No automated trade execution may be enabled or implied.

## Validator Behavior

Run:

```bash
bash scripts/validate_cockpit_view_model_quality.sh
```

The validator prints each passing gate, warnings, and blocking failures. It
returns a non-zero exit code when any blocking gate fails.

The validator uses only the Python standard library and performs no network
calls.

## Current Defense-Mode Baseline

- Latest checkpoint: `2026-06-08T08:44:00+08:00`
- Portfolio mode: `core_position_defense_mode`
- Active rules: `6`
- Strategy states: `16`
- Timeline warnings: `0`
- SOXL / UGL / INTC: closed, zero shares, no re-add
- GGLL: main remaining leveraged ETF risk valve
- NVDA: main core-risk watch
- GLD: ordinary concentration / risk-line protection
- Crypto: USDT-dominant defense
- BTC buyback: inactive
- ZEC grid: closed / profit-locked / do not reopen

## Known Limitations

- The gates validate current local cockpit semantics, not live market state.
- Optional state that is absent can only be reported as a warning.
- The validator does not replace source screenshot review or execution
  confirmation.
- The checks are intentionally specific enough to catch current LDD
  contradictions while remaining separate from trading execution.

## Non-Goals

- No UI is built.
- No frontend application files are created.
- No external APIs are connected.
- No trading automation is added.
- No GitHub Projects board or GitHub Issue is created.
- No historical checkpoint is re-ingested.

## Recommended Next Phase

Phase 5.5 implements the recommended consumer-readiness review in:

```text
docs/runtime/COCKPIT_CONSUMER_READINESS_REVIEW_v0.1.md
```

Next:

```text
Vol.5 Phase 5.6 - Mock Consumer Package / UI Boundary Sample
```

That phase should create mock/sample consumer payloads or static boundary
examples while still avoiding a real UI app.
