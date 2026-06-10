# Read-Only Consumer Fixture Validator v0.1

## Purpose

The Read-Only Consumer Fixture Validator turns the Vol.5 consumer contract
matrix into deterministic local checks. It verifies that future consumers can
read `cockpit/ldd/view_model.json` and the static files under
`mock_consumers/ldd/` without mutating runtime state, implying live data, or
turning risk guidance into automated execution.

This was the first of the final two Vol.5 pressure tests. Phase 5.9 is the
second: a real post-close executed-order writeback pressure test.

## Scope

The validator reads:

- `cockpit/ldd/manifest.json`
- `cockpit/ldd/view_model.json`
- the eight JSON fixtures under `mock_consumers/ldd/`

It validates checkpoint and portfolio-mode integrity, fixture presence,
manifest references, consumer boundaries, privacy categories, rule
interpretation, P/L attribution, quote types, and the 16-case contract matrix.

## Read-Only Guarantee

`scripts/validate_read_only_consumer_fixtures.py` hashes every source artifact
before validation and compares the hashes after all checks. Any source-file
mutation is a blocking failure.

The validator:

- uses only the Python standard library;
- makes no network calls;
- writes no runtime records or cockpit artifacts;
- submits no orders and exposes no trading integration;
- treats mock files as fixed examples, never live data.

## Blocking Checks

1. Latest checkpoint remains `2026-06-10T08:49:00+08:00`.
2. Portfolio mode remains `core_position_defense_mode`.
3. The cockpit manifest references the existing view model.
4. All eight required fixtures exist and contain JSON objects.
5. No fixture claims a live broker, Binance, market-data, order, or execution
   connection.
6. No fixture contains executable trading call structures or credential
   values.
7. Active rules remain read-only guidance.
8. Closed positions, opportunity cost, rule compliance, and P/L scopes remain
   separate.
9. Quote Type Tagging remains explicit.
10. The consumer contract matrix remains `16/16` passed with
    `ready_with_limits`.

## Current LDD Assertions

- GLD reductions from 20 to 10 shares remain rule-compliant writebacks; the
  residual 10 shares remain under 385 / 380 protection.
- NVDA reduction from 20 to 15 shares remains rule-compliant despite an
  imperfect short-term price outcome; the residual position retains 200
  downside protection.
- GOOG 355 defense and GGLL risk-valve roles remain read-only.
- SOXL / UGL / INTC / SOXS / TSLQ / GDXU remain closed or no-reentry.
- SOXL rebound opportunity cost remains separate from rule compliance.
- Crypto remains USDT-dominant, BTC buyback remains inactive, and the ZEC grid
  remains closed.
- HK high-profit protection remains separate from U.S. risk scoring.

## Privacy Boundary

The validator confirms that fixture payloads do not contain API keys, tokens,
passwords, login credentials, exact broker account numbers, or raw customer
identifiers. Descriptions of forbidden fields are allowed because the privacy
fixture must name what consumers may never expose.

Customer-facing masking, role permissions, and API authorization remain future
work.

## Usage

```bash
bash scripts/validate_read_only_consumer_fixtures.sh
```

A blocking failure returns a non-zero exit code. Warnings are printed
separately.

## Non-Goals

- No UI or frontend application.
- No API implementation or live connection.
- No broker or Binance connection.
- No trading automation or order execution.
- No mutation of historical runtime facts.

## Recommended Next Phase

```text
Vol.5 Handoff Summary -> Open Vol.6
```

Phase 5.9 confirms that the same read-only fixtures remain valid after real
executed-order writeback, account-structure improvement, and non-blocking
runtime-status arbitration.
