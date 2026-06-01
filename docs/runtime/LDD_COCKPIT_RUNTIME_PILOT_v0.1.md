# LDD Cockpit Runtime Pilot v0.1

Status: Draft for Vol.3 Runtime MVP

## Purpose

LLM Daredevil Desk is the first pilot domain for Tianma Work OS runtime records.

The pilot records financial-cockpit logic without connecting to trading platforms or executing trades.

## Pilot Scope

The LDD pilot includes:

- Trigger-to-execution rule records.
- Strategy-state risk records.
- Manual sync block examples.
- Offline validation.

## Pilot Non-Goals

The pilot does not include:

- Automated trading.
- Brokerage API integration.
- Binance API integration.
- External market data API calls.
- Private account screenshots.
- Private account identifiers.

## Runtime Records

### Trigger-to-Execution Rule

Used for assets with defined trigger lines and next actions.

Examples:

- BTC staged buyback trigger.
- SOXL protection trigger.

### Strategy State

Used for ongoing bot or strategy health monitoring.

Example:

- ZEC 500U / 60-grid bot state with profit surge protection.

## LDD Pilot Examples

Files:

- `examples/ldd/ldd_sync_block_20260601.example.md`
- `examples/ldd/btc_buyback_trigger_rule.example.json`
- `examples/ldd/zec_bot_strategy_state.example.json`
- `examples/ldd/soxl_trigger_rule.example.json`

## Validation

Run:

```bash
scripts/validate_runtime_records.sh
```

The validator checks local JSON examples against local schemas. It does not call external networks.

## Relationship to Backlog Issues

The pilot primarily exercises:

- TWOS-036 Strategy-State Risk Monitor.
- TWOS-043 Trigger-to-Execution Rule Ledger.
- TWOS-039 Rule-Based Execution Review.
- TWOS-040 Volatility-Aware Execution Splitter.

