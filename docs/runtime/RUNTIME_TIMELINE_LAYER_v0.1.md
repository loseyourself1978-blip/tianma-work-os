# Runtime Timeline Layer v0.1

Status: Vol.4 Phase 4.1 draft

## Purpose

The Runtime Timeline Layer turns file-based runtime records into a chronological view of what happened, what changed, and which source record supports each event.

Tianma Work OS already has runtime records, validation, generated reports, Command Intelligence, delta sync, memory retention, and handoff summaries. The next low-risk step is a deterministic timeline that can feed future cockpit views without building UI yet.

## Why Timeline Before UI

A cockpit should not embed one-off parsing logic directly into the interface. It should read stable cockpit-ready JSON.

The timeline layer creates that bridge:

```text
records/ldd/**/*.json
-> runtime timeline parser
-> reports/ldd/runtime_timeline.md
-> cockpit/ldd/runtime_timeline.json
-> future cockpit / summary / retrieval layer
```

## Data Inputs

The generator reads local JSON records from:

```text
records/ldd/**/*.json
```

It does not read brokerage APIs, Binance APIs, market data feeds, external services, or GitHub APIs.

## Outputs

Generated outputs:

- `reports/ldd/runtime_timeline.md`
- `cockpit/ldd/runtime_timeline.json`

The Markdown file is for human review. The JSON file is cockpit-ready and can be read by future scripts, agents, or UI prototypes.

## Related Runtime Layers

The timeline layer connects to:

- Runtime Query & Report Layer: timeline complements report summaries with chronology.
- Cockpit-Ready JSON Summary Layer: timeline JSON becomes one cockpit data source.
- Sync Delta Protocol: delta updates are represented as timeline events and can supersede older assumptions.
- Command Intelligence: pending and superseded commands can be placed in chronology before execution.
- Memory Retention Management: active memory checkpoints can use the timeline to explain what is current, historical, or superseded.

## Stale-State Handling

The timeline does not delete old records.

Instead, generated events can label older records as historical or superseded. For example, the 2026-06-02 ZEC bot strategy state remains in the archive, while the 2026-06-03 ZEC closure event and delta sync mark the latest state as closed / profit locked.

## Non-Goals

Vol.4 Phase 4.1 does not implement:

- UI.
- External APIs.
- Trading automation.
- Live market connection.
- Brokerage or Binance integration.
- GitHub Projects.

## Next Phase

Recommended next phase:

```text
Vol.4 Phase 4.2 — Cockpit-Ready JSON Summary Layer
```

That layer should summarize active strategy state, active trigger rules, open risks, latest account structure, and memory checkpoint status as stable JSON for future cockpit work.
