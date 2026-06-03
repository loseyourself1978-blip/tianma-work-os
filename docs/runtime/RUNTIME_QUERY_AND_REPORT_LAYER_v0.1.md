# Runtime Query And Report Layer v0.1

Status: Draft for Vol.3 Phase 4.1

## Purpose

Tianma Work OS now has file-based runtime records, schemas, examples, validation scripts, Command Intelligence, rule ledger records, strategy-state monitor records, and delta sync updates.

The next runtime need is inspection.

Without a query/report layer, a user has to manually open many JSON files to understand the current LDD state. Phase 4.1 adds a lightweight local reporting layer so runtime records can produce readable Markdown summaries.

## Runtime Flow

```text
records/ldd/
-> local parser
-> runtime summaries
-> Markdown reports
-> future cockpit / memory compression / AI retrieval
```

## How It Works

The report layer reads local JSON records under `records/ldd/` recursively.

It detects record families such as:

- Trigger rules.
- Strategy states.
- Portfolio states.
- Account structure reviews.
- Pending commands.
- Rule-based execution reviews.
- Delta sync updates.
- Execution events.

It then generates Markdown reports under `reports/ldd/`.

The script uses only the Python standard library. It does not call external APIs, connect to brokerage/Binance, access market data, or execute trades.

## Generated Reports

Phase 4.1 generates:

- `reports/ldd/latest_runtime_report.md`
- `reports/ldd/active_trigger_rules.md`
- `reports/ldd/strategy_state_summary.md`
- `reports/ldd/pending_commands_summary.md`
- `reports/ldd/account_structure_summary.md`
- `reports/ldd/execution_review_summary.md`
- `reports/ldd/delta_sync_summary.md`
- `reports/ldd/memory_cleanup_recommendations.md`
- `reports/ldd/latest_active_memory_checkpoint.md`

These reports are deterministic and safe to regenerate.

## Why This Comes Before UI

A cockpit UI should read from a stable query/report layer rather than directly embedding one-off JSON parsing logic.

The report layer proves that Tianma Work OS can:

- Read runtime memory.
- Identify the latest state.
- Summarize active rules.
- Summarize strategy states.
- Summarize pending commands.
- Explain execution reviews and delta sync updates.

Once these summaries are stable, a cockpit can display them without reinventing the logic.

## Memory Retention And Compression Support

Runtime reports also support future memory capacity management.

They can become compact active checkpoints while detailed JSON records remain archived in `records/`.

This helps future TWOS-045 work:

- Keep latest valid checkpoints active.
- Compact old snapshots into summaries.
- Mark superseded records.
- Preserve durable rules.
- Avoid manual one-by-one memory cleanup.

Phase 4.2 turns this into the first memory lifecycle layer by generating cleanup recommendations and a latest active memory checkpoint report.

## Future Agent And Cockpit Support

Future agents, cockpit views, and project summaries can use reports as a retrieval layer.

Examples:

- An AI agent can read the latest runtime report before executing a command.
- A cockpit can display active trigger rules without parsing every JSON file in real time.
- A memory retention workflow can archive old snapshots and keep generated summaries active.

## Non-Goals

Phase 4.1 does not implement:

- Web UI.
- GitHub Projects.
- New GitHub issues.
- Brokerage or Binance API access.
- Market data access.
- Automated trading.
- External service integrations.
