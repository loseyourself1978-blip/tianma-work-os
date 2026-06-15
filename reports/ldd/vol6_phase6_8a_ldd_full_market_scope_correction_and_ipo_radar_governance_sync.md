# Vol.6 Phase 6.8a LDD Full-Market Scope Correction and IPO Radar Governance Sync

## Baseline

- Starting TWOS baseline: `Vol.6 Phase 6.8 / 704f006b52461459ccc995ee0b6de7a53bbb0de2`
- Stale LDD-referenced baseline: `Vol.6 Phase 6.7 / c2a2a06edba6216eed64998caba018c3a3adf03d`
- Active checkpoint remains: `2026-06-12T09:18:00+08:00`
- Governance evidence timestamp: `2026-06-12T17:20:00+08:00`
- Checkpoint promoted: `false`
- Execution event: `false`

## Scope Correction

LDD review scope is corrected to `entire_us_equity_market`. Future reviews must include account risk management, full-market scan, sector rotation heatmap, IPO/new listing radar, non-position candidate watchlist, forbidden chase list, and position replacement/expansion review.

## Candidate Radar

`SPCX / SpaceX` is recorded as a user/LDD-provided candidate radar item only. TWOS does not verify listing status, fetch quotes, stage orders, or execute trades. Any action requires external verification, a real executable quote, and manual user action outside TWOS.

## Static Contracts Created

- Full-market scan scope contract
- Sector rotation heatmap contract
- New listing / IPO radar contract
- Non-position candidate watchlist
- Candidate-to-position pipeline
- Forbidden chase list
- Position replacement / expansion review contract

## Validation Result

The Phase 6.8a semantic validator checks the scope correction, SPCX safety rules, non-position candidates, pipeline automation blocks, forbidden chase list, drift correction, and safety flags.

## Remaining Gap Before Phase 6.9

Phase 6.9 should carry this scope correction into the Vol.6 handoff summary and preserve the active checkpoint unless a later confirmed execution reconciliation promotes a newer checkpoint.
