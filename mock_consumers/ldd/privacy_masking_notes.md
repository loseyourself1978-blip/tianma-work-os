# Privacy And Masking Notes

This mock package is internal and is not ready for customer-facing publication.

## Never Include

- broker or Binance login information;
- account passwords;
- API keys;
- access tokens;
- session cookies;
- private account identifiers;
- unredacted authentication screenshots;
- credentials embedded in URLs or logs.

## Future Masking Requirements

- Mask account identifiers by default.
- Define whether exact balances and position values are visible by role.
- Separate internal audit evidence from customer-facing summaries.
- Add field-level permissions for account, position, and source-evidence data.
- Add role-based display policies for owner, reviewer, advisor, and customer
  contexts.
- Preserve source traceability without exposing private screenshots.

## Current Boundary

- `cockpit/ldd/view_model.json` is a local, read-only project artifact.
- `mock_consumers/ldd/` contains examples only.
- No privacy-masking engine exists.
- No permission system exists.
- No API or UI exposes these files.
- Customer-facing use remains `ready_with_limits` until masking and permissions
  are implemented and validated.
