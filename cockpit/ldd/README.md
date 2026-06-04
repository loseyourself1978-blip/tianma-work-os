# LDD Cockpit Data

This directory contains cockpit-ready JSON generated from local runtime records.

Current files:

- `manifest.json` is the entrypoint for future cockpit prototypes.
- `latest_state.json` is the current-state summary for the latest active LDD checkpoint.
- `active_rules.json` contains active, near-trigger, awaiting-confirmation, executed, stale, and superseded trigger rules.
- `strategy_states.json` contains current strategy states.
- `account_structure.json` contains section-level account quality state.
- `pending_commands.json` contains command status.
- `memory_checkpoint.json` contains memory status and cleanup guidance.
- `runtime_timeline.json`

`runtime_timeline.json` is chronological event data. The summary files are current-state cockpit data.

The data is generated locally and does not connect to brokerage APIs, Binance APIs, market data, external services, or trading automation.
