# Vol.7 Phase 7.6 - Local Static Shell Demo Pack and Operator Walkthrough

## 1. Phase Summary

Phase 7.6 creates a local-only demo pack and operator walkthrough for the LDD local static shell created in Phase 7.4 and hardened in Phase 7.5.

The goal is to make the static shell easy to inspect, open locally, explain, and hand off without changing its safety boundary. This phase does not create production UI, customer-facing UI, an API server, a live endpoint, broker/Binance connectivity, live market data, credential handling, runtime mutation, or execution capability.

## 2. Demo Pack Scope

The demo pack covers:

- what the static shell is
- what the static shell is not
- how to open `static_shell/ldd/index.html` locally
- which files are part of the local static shell
- which data is embedded fixture-only data
- which panels should be visible
- which guardrails must be visible
- how to inspect that no network/API/credential/execution capability exists
- how to explain quote drift, cash-defense split, opportunity cost, zero-position radar, forbidden chase, transfer/P&L separation, and LDD full-market scope

The demo pack is documentation and fixture-contract work only.

## 3. Local Static Shell Boundary

The shell remains:

- local only
- static only
- fixture-only
- read-only
- local-static-preview-only
- no network
- no API
- no live data
- no broker connection
- no Binance connection
- no credential handling
- no execution
- no runtime mutation
- not customer-facing
- not production deployable

## 4. Demo Documents

Phase 7.6 adds three operator-facing static shell documents:

- `static_shell/ldd/OPERATOR_WALKTHROUGH.md`
- `static_shell/ldd/DEMO_CHECKLIST.md`
- `static_shell/ldd/SAFETY_BOUNDARY.md`

These documents explain how to inspect the static shell locally, how to walk through each panel, and how to verify that forbidden capabilities are absent.

## 5. Local Opening Procedure

Open:

```text
static_shell/ldd/index.html
```

directly in a browser as a local file.

No server is required. No network is required. No API key is required. No login is required. No account connection is required.

## 6. Required Guardrail Labels

The operator must verify these labels are visible:

- `LOCAL STATIC PREVIEW ONLY`
- `STATIC FIXTURE`
- `READ ONLY`
- `NOT EXECUTABLE`
- `NO LIVE DATA`
- `NO BROKER CONNECTION`
- `NO BINANCE CONNECTION`
- `NO CREDENTIAL HANDLING`
- `NO RUNTIME MUTATION`
- `CUSTOMER-FACING READINESS: FALSE`

These labels must remain visible as text and must not rely on color alone.

## 7. Panel Walkthrough Coverage

The walkthrough covers:

- Runtime Status Panel
- Readiness Gate Panel
- Timeline Health Panel
- Active Rules Panel
- Strategy States Panel
- Static Fixture Source Panel
- LDD Scope Reminder Panel
- Quote Drift Display Panel
- Holdings / Candidate / Forbidden / Radar Separation Panel
- Cash Defense Split Panel
- Transfer / P&L Separation Panel
- Opportunity Cost Tracker Panel
- Rule Compliance vs Opportunity Capture Panel
- Zero-Position Candidate Radar Panel
- Forbidden Chase List Panel
- IPO/New-Listing Radar Panel
- Forbidden Actions Panel
- Non-Executable Guardrail Panel

Panels are static read-only explanations. They do not create controls.

## 8. Quote Drift Explanation

The demo must explain that these quote types are separate:

- holding quote
- watchlist quote
- night-session quote
- premarket quote
- executable order-book quote
- final filled order price

Holding, watchlist, night-session, and premarket quotes must not be treated as executable prices.

Required copy remains:

```text
Execution source remains broker/Binance order page and final filled order records.
```

## 9. Cash Defense Split Explanation

The demo must explain separate fixture-only concepts:

- U.S. account cash-defense ratio: approximately 77.6%
- Binance USDT defense ratio: approximately 70.6%
- HK 02513 holding value: 145,700 HKD
- total cross-account risk placeholder: fixture-only placeholder

These values are timestamped, fixture-only, read-only, non-live, and non-executable.

## 10. Opportunity Cost Tracker Explanation

The demo must explain the Opportunity Cost Tracker as hindsight/context only.

It may include:

- SOXL
- GDXU
- GGLL
- GLD
- UGL
- INTC
- SPCX
- MU
- DRAM

Opportunity cost must stay separate from rule compliance score. It must not trigger buy/re-entry actions, override cash-defense mode, or become execution advice.

## 11. Zero-Position Candidate Radar and Forbidden Chase List

The demo must show the difference between:

- current holdings
- zero-position former holdings
- zero-position candidate radar
- forbidden-chase list
- IPO/new-listing radar
- residual tiny positions

Corrections preserved:

- GGLL is zero-position, not an active residual risk valve.
- ZEC grid is closed/no-reopen.
- SPCX is IPO radar only, no chase, no SPCH/SSPC, and do not sell GOOG/NVDA to fund it.
- SOXL/GDXU/GLD/UGL are no-chase after high-beta rebound.

## 12. Transfer and P/L Separation

The demo must show the 49.99 USDT crypto withdrawal as:

```text
completed transfer / withdrawal, not trading loss
```

Transfer and withdrawal events must remain separate from trading P/L.

## 13. LDD Full-Market Scope

The scope reminder remains:

```text
LDD scope is the entire U.S. equity market, not only existing or former positions.
```

This supports future inclusion of market-wide candidates such as MU, DRAM, AMD, TSM, SPCX, and other U.S. equity candidates even when they are not current holdings.

## 14. Demo Pack Validation Strategy

The Phase 7.6 validator checks:

- required demo documents exist
- demo pack fixture conforms to schema
- required statuses are passed
- warnings and errors are empty
- required static flags remain correct
- required labels remain visible
- required panels are represented
- quote drift, cash-defense split, HK exposure, transfer/P&L separation, opportunity cost, radar, forbidden chase, IPO radar, GGLL correction, ZEC closure, and LDD full-market scope remain explicit
- no fetch, XMLHttpRequest, WebSocket, EventSource, remote import/CDN, API endpoint, credential input, password/token/API-key field, buy/sell/rebalance control, runtime mutation control, publish control, package manager file, backend/server file, scheduler, or background worker is introduced

## 15. Phase 7.6 Exit Criteria

Phase 7.6 is complete only if:

- all required files are created
- demo pack fixture validates
- full existing validation stack passes
- runtime records increment from 105 to 106
- timeline events increment from 105 to 106
- timeline warnings remain 0
- customer-facing readiness remains false
- static shell remains isolated under `static_shell/ldd/`
- no forbidden integration or execution capability is introduced
- no package manager/build tool/framework/network dependency is introduced

## 16. Handoff to Phase 7.7

Next recommended phase:

```text
Vol.7 Phase 7.7 - Local Static Shell Snapshot QA and Vol.7 Completion Readiness
```

Phase 7.7 should perform final static snapshot QA and decide whether Vol.7 is ready for handoff. It must remain local/static/read-only/fixture-only and must not introduce live integrations or production/customer-facing UI.

## 17. Explicit Non-goals

- No production UI
- No customer-facing UI
- No hosted app
- No API server
- No live endpoint
- No external API
- No broker connection
- No Binance connection
- No live market data
- No trading automation
- No credential handling
- No login/auth form
- No API key input
- No runtime mutation UI
- No execution trigger
- No order placement
- No portfolio modification
- No background worker
- No scheduler
- No notification dispatcher
- No GitHub Issues
- No GitHub Projects board
- No package manager files
- No build tools
- No frontend framework
- No network dependency
