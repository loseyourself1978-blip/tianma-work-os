# LDD Local Static Shell Operator Walkthrough

## 1. Local Opening Steps

Open this file directly in a browser:

```text
static_shell/ldd/index.html
```

This is a local static preview. No server is required. No network is required. No API key is required. No login is required. No account connection is required.

Do not run a development server. Do not install packages. Do not connect broker, Binance, market-data, API, or credential systems.

## 2. What to Check First

Verify these labels are visible before reviewing any panel:

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

If any label is missing, stop the demo review and treat the shell as incomplete.

## 3. Panel Walkthrough

### Runtime Status Panel

Confirm the phase, baseline commit, active checkpoint, operating mode, and portfolio mode are visible as static fixture data.

### Readiness Gate Panel

Confirm readiness is limited to local static preview usage and customer-facing readiness remains false.

### Timeline Health Panel

Confirm timeline count and warning count are fixture values. Timeline warnings should remain 0 after Phase 7.6 generation.

### Active Rules Panel

Confirm active rules are presented as non-executable context. They must not appear as automated trade instructions.

### Strategy States Panel

Confirm strategy states are read-only and preserve residual core position mode.

### Static Fixture Source Panel

Confirm the shell says it reads embedded fixture data only and does not fetch live data.

### LDD Scope Reminder Panel

Confirm this sentence is visible:

```text
LDD scope is the entire U.S. equity market, not only existing or former positions.
```

### Quote Drift Display Panel

Explain that holding quote, watchlist quote, night-session quote, premarket quote, executable order-book quote, and final filled order price are different concepts.

Required explanation:

```text
Execution source remains broker/Binance order page and final filled order records.
```

### Holdings / Candidate / Forbidden / Radar Separation Panel

Confirm current holdings, zero-position former holdings, candidate radar, forbidden-chase names, IPO/new-listing radar, and tiny residual positions are separated.

### Cash Defense Split Panel

Explain the separate fixture-only values:

- U.S. account cash-defense ratio: approximately 77.6%
- Binance USDT defense ratio: approximately 70.6%
- HK 02513 holding value: 145,700 HKD
- total cross-account risk placeholder: fixture-only placeholder

### Transfer / P&L Separation Panel

Confirm the 49.99 USDT withdrawal is labeled:

```text
completed transfer / withdrawal, not trading loss
```

### Opportunity Cost Tracker Panel

Explain that opportunity cost is hindsight/context only. It does not mean prior risk-control decisions were wrong, and it cannot trigger buy or re-entry actions.

### Rule Compliance vs Opportunity Capture Panel

Explain that rule compliance, risk control, return capture, account structure, emotional discipline, DUXD feedback value, and overall score are separate review concepts.

### Zero-Position Candidate Radar Panel

Confirm zero-position candidates are visible as radar context only.

### Forbidden Chase List Panel

Confirm SOXL, GDXU, GLD, UGL, SPCX, SPCH, and SSPC are not chase instructions.

### IPO/New-Listing Radar Panel

Confirm SPCX is IPO radar only: max 1 share limit order if considered later, no chase, no SPCH/SSPC, and do not sell GOOG/NVDA to fund it.

### Forbidden Actions Panel

Confirm buy, sell, rebalance, connection, credential, live refresh, mutation, scheduler, background worker, production publish, and customer-facing publish affordances are absent.

### Non-Executable Guardrail Panel

Confirm the shell repeats read-only, no-execution, no-live-data, no-credential, and no-production-deployment flags.

## 4. Safety Explanation

Use this plain-language explanation during handoff:

- The shell cannot trade.
- The shell cannot connect to Longbridge.
- The shell cannot connect to Binance.
- The shell cannot fetch market data.
- The shell cannot accept credentials.
- The shell cannot mutate runtime records.
- The shell cannot publish customer-facing UI.
- Execution source of truth remains broker/Binance order page and final filled order records.

## 5. Stop Conditions

Stop the demo if you see:

- a buy, sell, rebalance, connect, sync, live refresh, edit, publish, scheduler, background worker, or execution control
- a login form, API key input, token field, password field, or credential form
- a network fetch, API endpoint, remote import, CDN reference, package manager file, backend server file, or worker/scheduler file
- customer-facing readiness set to true
