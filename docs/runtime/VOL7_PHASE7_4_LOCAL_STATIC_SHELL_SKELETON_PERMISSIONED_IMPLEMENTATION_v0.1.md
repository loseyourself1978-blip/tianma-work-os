# Vol.7 Phase 7.4 Local Static Shell Skeleton Permissioned Implementation v0.1

## 1. Phase Summary

Vol.7 Phase 7.4 creates a permissioned local static shell skeleton for the LDD cockpit. The shell demonstrates how the Phase 7.0 through Phase 7.3 static contracts can be displayed in a local read-only cockpit shell.

This phase is not a production UI, customer-facing UI, hosted app, API server, or live endpoint. It creates isolated static files only under `static_shell/ldd/`. The shell reads no network data, calls no APIs, accepts no credentials, mutates no runtime state, and creates no execution path.

## 2. Permission Boundary

Allowed in this phase:

- local static shell skeleton only
- read-only display only
- fixture snapshot only
- no-network local preview only
- static labels and guardrails
- no user input that mutates state
- no customer-facing release
- no production deployment

Forbidden in this phase:

- production UI
- customer-facing UI
- hosted app
- API server
- live endpoint
- external API
- broker connection
- Binance connection
- live market data
- trading automation
- credential handling
- login/auth form
- API key input
- runtime mutation UI
- execution trigger
- order placement
- portfolio modification
- background worker
- scheduler
- notification dispatcher
- GitHub Issues
- GitHub Projects board

## 3. Static Shell Files

The local shell is isolated under `static_shell/ldd/`:

- `static_shell/ldd/README.md`
- `static_shell/ldd/index.html`
- `static_shell/ldd/styles.css`
- `static_shell/ldd/static_shell_data.js`
- `static_shell/ldd/render_static_shell.js`

The files are plain static files. They do not introduce a package manager, bundler, development server, backend route, or live integration dependency.

## 4. Required Panels

The shell represents these read-only panels:

1. Runtime Status Panel
2. Readiness Gate Panel
3. Timeline Health Panel
4. Active Rules Panel
5. Strategy States Panel
6. Static Fixture Source Panel
7. LDD Scope Reminder Panel
8. Quote Drift Display Panel
9. Holdings / Candidate / Forbidden / Radar Separation Panel
10. Cash Defense Split Panel
11. Transfer / P&L Separation Panel
12. Forbidden Actions Panel
13. Non-Executable Guardrail Panel

Every panel is static, read-only, fixture-only, non-live, and non-executable.

## 5. Required Labels

The shell must visibly display:

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

## 6. Embedded Fixture Snapshot

`static_shell/ldd/static_shell_data.js` embeds a fixture snapshot only. It includes:

- phase
- baseline commit
- active checkpoint
- latest timeline event
- runtime records count
- timeline event count
- timeline warning count
- active rules count
- strategy states count
- customer-facing readiness
- readiness decision
- operating mode
- portfolio mode
- dry-run status
- drift status
- LDD full-market scope reminder
- required labels
- allowed panels
- forbidden actions
- forbidden integrations
- quote drift requirements
- cash-defense split
- transfer/P&L separation
- GGLL zero-position correction
- ZEC closed/no-reopen
- USDT 70 percent floor

All values are labeled fixture-only, timestamped, non-live, read-only, and non-executable.

## 7. LDD Backfeed Display Requirements

The shell includes the Phase 7.3 LDD addendum concepts as static display content only.

Quote drift display must distinguish:

- broker watchlist latest price
- premarket price
- holding valuation price
- executable order-page price
- final filled order price

Required label:

```text
Execution source of truth remains broker/Binance order page and final filled order records.
```

The shell must never imply that watchlist or holding valuation prices are executable prices.

Holdings / candidate / forbidden / radar separation must distinguish:

- current holdings
- watchlist candidates
- forbidden-chase list
- IPO/new-listing radar
- zero-position former holdings
- residual tiny positions

Specific static state:

- GGLL current state: `zero_position_not_residual_risk_valve`
- ZEC grid state: `closed_no_reopen`

Cash defense split must show fixture-only, timestamped, non-live values:

- U.S. cash ratio: approximately 77.8 percent
- Binance USDT defense ratio: approximately 71.2 percent
- total cross-account defense ratio: placeholder only

Transfer / P&L separation must show the completed 49.99 USDT crypto withdrawal as an account movement event, not trading P/L.

## 8. Interaction Rules

Allowed interactions:

- expand/collapse static panels
- internal anchor navigation
- static tab switching if no data mutation occurs
- static filtering over embedded fixture arrays only, if implemented

Forbidden interactions:

- buy button
- sell button
- rebalance button
- connect broker button
- connect Binance button
- sync broker button
- sync Binance button
- live refresh button
- API key input
- credential form
- login/auth form
- auto-trade toggle
- runtime edit form
- rule mutation editor
- portfolio edit form
- alert dispatch toggle
- scheduler toggle
- background worker trigger
- production publish button
- customer-facing publish flag

## 9. Validation Strategy

The Phase 7.4 validator checks:

- all required files exist
- manifest conforms to schema
- required flags are present and correct
- required labels are present in the static shell
- all required panels are represented
- LDD full-market scope reminder exists
- quote drift display layer exists
- quote-type tagging exists
- cash-defense split exists
- transfer/P&L separation exists
- GGLL zero-position correction exists
- ZEC closed/no-reopen exists
- USDT 70 percent floor exists
- no network fetch patterns exist
- no XMLHttpRequest exists
- no WebSocket exists
- no EventSource exists
- no remote imports or CDN links exist
- no API endpoint references exist
- no credential input fields exist
- no password/token/API-key fields exist
- no buy/sell/rebalance execution controls exist
- no runtime mutation controls exist
- no production/customer-facing publish controls exist
- no package manager files are introduced for this static shell
- no backend/server files are introduced
- no scheduler/background worker files are introduced
- customer-facing readiness remains false

## 10. Exit Criteria

Phase 7.4 is complete only if:

- all required files are created
- static shell manifest validates
- local static shell validator passes
- full existing validation stack passes
- runtime records increment from 103 to 104
- timeline events increment from 103 to 104
- timeline warnings remain 0
- customer-facing readiness remains false
- local static shell remains isolated under `static_shell/ldd/`
- no forbidden integration or execution capability is introduced

## 11. Handoff to Phase 7.5

Next recommended phase:

```text
Vol.7 Phase 7.5 - Local Static Shell Review, Accessibility, and Guardrail Hardening
```

Phase 7.5 should review the local static shell skeleton for clarity, safety labels, accessibility, copy quality, and guardrail visibility. It should not introduce live data, API, broker/Binance connection, credential handling, execution, runtime mutation, scheduler, background worker, or customer-facing release.
