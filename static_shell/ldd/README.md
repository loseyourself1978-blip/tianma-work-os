# LDD Local Static Shell

This directory contains the LDD local static shell after the Vol.7 Phase 7.6 local demo pack and operator walkthrough pass.

It is a local static preview only. It is not a production UI, not a customer-facing UI, not a hosted app, not an API server, and not a live endpoint. It reads an embedded fixture snapshot only.

## Files

- `index.html` - local static shell entry point.
- `styles.css` - static styling only.
- `static_shell_data.js` - embedded fixture snapshot only.
- `render_static_shell.js` - read-only rendering logic only.
- `OPERATOR_WALKTHROUGH.md` - local-only operator walkthrough.
- `DEMO_CHECKLIST.md` - local demo inspection checklist.
- `SAFETY_BOUNDARY.md` - human-readable static shell safety boundary.

## Review Notes

Phase 7.5 hardens the shell for guardrail visibility, accessibility, quote-drift clarity, cash-defense split clarity, transfer/P&L separation, opportunity-cost tracking, and holdings / zero-position / candidate / forbidden / radar separation.

The 2026-06-15 LDD post-close review values are fixture-only product backfeed. They are timestamped, non-live, read-only, and non-executable. Execution source remains broker/Binance order page and final filled order records.

## Demo Pack Notes

Phase 7.6 adds local-only handoff material for operators. Open `index.html` directly from the filesystem, then use `OPERATOR_WALKTHROUGH.md`, `DEMO_CHECKLIST.md`, and `SAFETY_BOUNDARY.md` to inspect the shell.

No server is required. No network is required. No API key is required. No login is required. No account connection is required.

## Boundaries

The shell must remain:

- fixture-only
- read-only
- local static preview only
- no-network
- no-credential
- no-live-data
- no-runtime-mutation
- no-execution
- not customer-facing

It must not:

- fetch remote or local API data
- use broker or Binance connectivity
- include credential fields
- include order, trade, rebalance, or portfolio-edit controls
- include scheduler, background worker, or notification dispatch logic
- write runtime records or mutate cockpit artifacts
- imply that holding, watchlist, night-session, or premarket quotes are executable prices
- treat opportunity cost as a rule-compliance failure or execution instruction

## Accessibility Notes

- Critical guardrails are visible as text, not color-only signals.
- The panel list uses clear links and the panels use semantic headings/regions.
- The shell includes a skip link for keyboard navigation.
- Critical warnings are not hidden behind hover-only disclosure.

Open `index.html` directly from the filesystem for local inspection.
