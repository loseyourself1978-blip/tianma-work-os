# Runtime MVP Scope v0.2

Status: Draft for Vol.3

## Goal

Create the smallest useful Tianma Work OS runtime package that can preserve project memory, normalize incoming signals, route decisions into commands, and validate LDD pilot records.

## Included in Vol.3

Vol.3 includes:

- Runtime architecture documentation.
- Project memory record schema.
- Signal intake schema.
- Decision command schema.
- Trigger execution rule schema.
- Strategy state schema.
- LDD pilot examples.
- Offline validation scripts.
- INDEX navigation update.

## First Runtime Chain

```text
Project Memory
-> Multi-Source Signal Intake
-> AI Board Decision
-> Decision-to-Command Routing
-> LDD Financial Cockpit Pilot
-> Runtime Validation
```

## Primary Issues Covered

Vol.3 maps directly to:

- #1 TWOS-005 Project Memory & Index.
- #5 TWOS-029 Multi-Source Signal Intake.
- #6 TWOS-032 Decision-to-Command Routing.
- #16 TWOS-043 Trigger-to-Execution Rule Ledger.
- #12 TWOS-036 Strategy-State Risk Monitor.

## Explicitly Deferred

The following remain design/backlog items:

- #2 TWOS-008 Project-Aware Reminder / Record Routing System.
- #8 TWOS-034 Project-Preserving Model Switching.

They are not implemented in this package.

## Excluded

Vol.3 excludes:

- GitHub Projects board.
- New GitHub issues.
- UI or dashboard.
- Automated trading.
- Brokerage APIs.
- Binance APIs.
- External market data APIs.
- Background schedulers.
- Secrets, tokens, or private account screenshots.

## Success Criteria

Vol.3 is successful when:

- All new runtime docs exist under `docs/runtime/`.
- Runtime schemas exist under `schemas/`.
- LDD examples exist under `examples/ldd/`.
- `scripts/validate_runtime_records.py` validates JSON examples offline.
- `INDEX.md` links to the runtime docs.
- The repository remains simple and document-first.

