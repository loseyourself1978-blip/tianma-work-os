# Consumer Contract Test Matrix And Privacy Boundary v0.1

## Purpose

Vol.5 Phase 5.7 verifies that future consumers can read
`cockpit/ldd/view_model.json` without changing its meaning, exposing private
data, or bypassing safety gates.

The layer converts consumer guidance into explicit test cases. It remains
static, local, read-only, and non-executable.

## Scope

The matrix covers:

- generated reports;
- future read-only UI;
- future API layer;
- mobile display;
- AI Board / role-based review;
- future customer-facing cockpit.

Artifacts:

- `schemas/consumer_contract_test_matrix.schema.json`
- `records/ldd/2026-06-09/consumer_contract_test_matrix_0828_sgt.json`
- `mock_consumers/ldd/consumer_contract_test_matrix.json`
- `mock_consumers/ldd/privacy_boundary_sample.json`
- `reports/ldd/consumer_contract_test_matrix.md`

## Non-Goals

- No UI or frontend app is built.
- No API endpoint or server is created.
- No broker, Binance, market-data, or external API is connected.
- No live prices are inferred.
- No trades are executed.
- No trading automation is added.
- No masking engine or permission system is implemented.
- No historical checkpoint is re-ingested.

## Consumer Types Covered

1. Generated reports
2. Future UI
3. API layer
4. Mobile display
5. AI Board / role-based review
6. Future customer-facing cockpit

## Contract Test Dimensions

1. Checkpoint integrity
2. Portfolio mode integrity
3. Active versus closed position separation
4. Active-position P/L versus historical, closed, or headline P/L
5. Rule compliance versus opportunity cost
6. Quote type separation
7. GLD active-risk interpretation
8. GLD rule-compliant execution interpretation
9. NVDA 204 / 200 downside protection
10. GOOG / GGLL risk-valve interpretation
11. Crypto defense interpretation
12. HK high-profit protection separation
13. Warning and data-quality rendering
14. No-trading-automation boundary
15. Mock-data versus live-data boundary
16. Privacy and masking boundary

## Privacy Boundary Model

### Public-Safe Fields

- product concept;
- generic portfolio-mode labels;
- generic risk-state examples.

### Internal-Only Fields

- detailed account values;
- position quantities;
- P/L values;
- rule-state details.

### Sensitive Account Fields

- broker account identifiers;
- Binance account identifiers;
- screenshot-derived account values in customer-facing contexts.

### Execution-Sensitive Fields

- executable quotes;
- pending order instructions;
- stop or reduce thresholds.

These may be displayed only as restricted read-only context. They are not an
order path.

### Never-Expose Fields

- API keys;
- tokens;
- login credentials;
- exact broker account numbers;
- raw customer personal identifiers.

## Safety Boundary Model

- `cockpit/ldd/view_model.json` is the primary generated artifact.
- Consumers are read-only.
- Rules are monitored conditions, not automated orders.
- Mock samples are examples, not live data.
- Quality gates must pass before downstream use.
- Human control and Command Intelligence remain required.
- User-provided broker and Binance screenshots remain execution source of
  truth.

## Data-Source Boundary Model

| Source | Permitted use |
|---|---|
| `cockpit/ldd/view_model.json` | Primary consumer payload |
| `mock_consumers/ldd/*` | Static examples only |
| `cockpit/ldd/runtime_timeline.json` | Chronological audit context |
| `records/ldd/**` | Audit/debug and source traceability |
| User screenshots | Execution source of truth |
| External market context | Cross-check only; not execution source |

Consumers must not reconstruct current state from raw records unless operating
in an explicit audit or debug mode.

## Rendering Boundary Model

- Active positions and closed positions use separate collections.
- Section P/L values remain attributed to their account sections.
- Closed-position opportunity cost remains separate from rule compliance.
- Quote type accompanies price-related rendering.
- Warning and data-quality panels remain available even when empty.
- Thresholds and rules must not render as executable buttons or submitted
  orders.
- Customer-facing views mask or omit internal and sensitive fields.

## Consumer Misinterpretation Risks

- Treating SOXL rebound as proof that cleanup failed.
- Rendering SOXL, UGL, INTC, SOXS, TSLQ, or GDXU as active positions.
- Combining total-account, U.S., HK, crypto, active, or historical P/L.
- Calling a post-close or static price executable.
- Treating GLD execution price outcome as identical to rule compliance.
- Treating NVDA or GOOG/GGLL thresholds as automated orders.
- Treating mock files as a live market feed.
- Publishing private values or identifiers without masking.
- Ignoring `warnings` or `data_quality`.

## Required Pass Criteria

- All 16 contract tests pass.
- Blocking failures equal `0`.
- Test warnings equal `0`.
- Consumer readiness remains `ready_with_limits`.
- Latest checkpoint remains `2026-06-10T08:49:00+08:00`.
- Portfolio mode remains `core_position_defense_mode`.
- Timeline warnings remain `0`.
- View-model quality gates remain passed.
- No UI, API, live connection, or trading automation is created.

## Current LDD Defense-Mode Test Cases

- GLD has two confirmed 5-share reductions, remains at 10 shares, and retains
  385 / 380 downside protection.
- NVDA has one confirmed 5-share reduction, remains at 15 shares, and retains
  200 downside protection.
- GOOG 355 defense and GGLL risk-valve roles remain distinct.
- SOXL / UGL / INTC / SOXS / TSLQ / GDXU remain closed or no-reentry.
- SOXL rebound remains opportunity cost, not rule failure.
- Crypto remains USDT-dominant; BTC buyback is inactive; ZEC grid remains
  closed.
- HK Zhipu / 02513 protection remains separate from U.S. risk scoring.
- Quote Type Tagging remains mandatory.
- Static mock files remain examples, not live data.

## Known Limitations

- The matrix records expected behavior but does not yet execute fixture-level
  assertions against every mock JSON file.
- No privacy-masking engine exists.
- No field-level permission system exists.
- No API authentication or authorization exists.
- No customer-facing disclosure policy exists.
- The test matrix is LDD-pilot and single-project focused.

## Recommended Next Phase

```text
Vol.5 Handoff Summary -> Open Vol.6
```

Phase 5.8 implements this recommendation in:

- `docs/runtime/READ_ONLY_CONSUMER_FIXTURE_VALIDATOR_v0.1.md`
- `scripts/validate_read_only_consumer_fixtures.py`
- `scripts/validate_read_only_consumer_fixtures.sh`
- `reports/ldd/read_only_consumer_fixture_validation.md`

The validator executes the matrix boundaries locally and confirms source files
remain unchanged by comparing hashes before and after validation.

Phase 5.9 additionally confirms that consumers preserve executed-order
writeback, distinguish rule compliance from price outcome, and honor the
resolved runtime baseline without rolling back Phase 5.7 or Phase 5.8.
