# Vol.6 Phase 6.1 UI Boundary Architecture

Phase 6.1 defines a static read-only boundary for future Cockpit consumers.

## Verified Boundary

- Source artifact: `cockpit/ldd/view_model.json`
- Latest checkpoint: `2026-06-10T08:49:00+08:00`
- Consumer mode: `internal_read_only`
- Customer-facing readiness: `false`
- Surface definitions: `12`
- Visibility classes: `5`
- State-taxonomy groups: `5`
- Frontend implementation: absent
- API server: absent
- External, broker, and Binance connections: absent
- Trading automation: absent

## Boundary Artifacts

- `mock_consumers/ldd/ui_boundary_contract.json`
- `mock_consumers/ldd/ui_field_visibility_matrix.json`
- `mock_consumers/ldd/ui_surface_map.json`
- `mock_consumers/ldd/ui_state_taxonomy.json`

## Next

```text
Vol.6 Phase 6.2 - Permission and Privacy Masking Model
```

Canonical specification:
`docs/runtime/VOL6_UI_BOUNDARY_ARCHITECTURE_v0.1.md`
