# LDD Local Static Shell Skeleton

This directory contains the Vol.7 Phase 7.4 local static shell skeleton for the LDD cockpit.

It is a local static preview only. It is not a production UI, not a customer-facing UI, not a hosted app, not an API server, and not a live endpoint.

## Files

- `index.html` - local static shell entry point.
- `styles.css` - static styling only.
- `static_shell_data.js` - embedded fixture snapshot only.
- `render_static_shell.js` - read-only rendering logic only.

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

Open `index.html` directly from the filesystem for local inspection.
