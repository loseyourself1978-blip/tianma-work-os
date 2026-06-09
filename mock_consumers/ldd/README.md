# LDD Mock Consumer Package

This directory contains static, read-only examples for consumers of:

```text
cockpit/ldd/view_model.json
```

The generated view model remains the primary artifact. These files demonstrate
consumer boundaries; they are not live data, frontend code, API endpoints, or
execution instructions.

## Files

- `view_model_snapshot.json`: compact static snapshot of the current LDD state.
- `ui_boundary_sample.json`: conceptual read-only display zones.
- `report_consumer_sample.json`: report-consumption rules.
- `api_consumer_sample.json`: future response-shape concept only.
- `mobile_consumer_sample.json`: compact display priorities.
- `ai_board_consumer_sample.json`: role-based review boundaries.
- `privacy_masking_notes.md`: customer-facing privacy requirements.
- `consumer_contract_test_matrix.json`: static pass/fail contract cases.
- `privacy_boundary_sample.json`: privacy field classifications and defaults.

## Safety

- Do not infer live prices.
- Do not execute trades.
- Do not turn rules into automated orders.
- Do not add credentials, tokens, API keys, or login details.
- Keep warnings and data-quality fields visible.
- Use raw records only for audit or debug.
