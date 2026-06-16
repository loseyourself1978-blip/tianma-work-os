# LDD Local Static Shell Safety Boundary

This static shell is:

- local only
- static only
- fixture-only
- read-only
- no network
- no API
- no live data
- no broker/Binance connection
- no credential handling
- no execution
- no runtime mutation
- no customer-facing release
- no production deployment

It may be opened directly from:

```text
static_shell/ldd/index.html
```

No server, package manager, build tool, framework, network access, login, credential, broker connection, Binance connection, API key, or live data source is required.

## Forbidden Affordances

The shell must not include:

- Buy button
- Sell button
- Rebalance button
- Connect broker button
- Connect Binance button
- Sync broker button
- Sync Binance button
- Live refresh button
- API key input
- Credential form
- Login/auth form
- Auto-trade toggle
- Runtime edit form
- Rule mutation editor
- Portfolio edit form
- Alert dispatch toggle
- Scheduler toggle
- Background worker trigger
- Production publish button
- Customer-facing publish flag

## Forbidden Integration Classes

The shell must not include:

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
- runtime mutation UI
- execution trigger
- order placement
- portfolio modification
- background worker
- scheduler
- notification dispatcher

## Source-of-Truth Boundary

Displayed values are static fixtures. Execution source remains broker/Binance order page and final filled order records.

Holding quotes, watchlist quotes, night-session quotes, and premarket quotes are not executable prices.

## Customer-Facing Boundary

Customer-facing readiness remains false. This shell cannot be published as a customer-facing cockpit.
