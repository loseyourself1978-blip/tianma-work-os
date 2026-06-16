# Vol.8 Static Shell QA Handoff Checklist

Use this checklist only for the local static shell under `static_shell/ldd/`.

## 1. Boundary Confirmation

- [ ] Review target is limited to `static_shell/ldd/`.
- [ ] Review is local only.
- [ ] Review is static only.
- [ ] Review does not imply product release.
- [ ] Review does not imply implementation approval.

## 2. Fixture-Only Confirmation

- [ ] All displayed data is fixture-backed.
- [ ] No live market data is expected.
- [ ] No broker or Binance account state is queried.
- [ ] Any stale or illustrative value is understood as fixture content.

## 3. Read-Only Confirmation

- [ ] The shell provides no editing workflow.
- [ ] The shell provides no runtime update workflow.
- [ ] The shell provides no account or portfolio modification workflow.
- [ ] QA observations remain notes only.

## 4. No Network/API Confirmation

- [ ] No API server is present.
- [ ] No live endpoint is present.
- [ ] No external API is present.
- [ ] No network dependency is required for review.
- [ ] No remote data source is implied by the UI copy.

## 5. No Execution/Mutation Confirmation

- [ ] No execution trigger is present.
- [ ] No order placement is present.
- [ ] No trading automation is present.
- [ ] No scheduler or background worker is present.
- [ ] No notification dispatcher is present.

## 6. No Credential/Auth Confirmation

- [ ] No login/auth flow is present.
- [ ] No API key input is present.
- [ ] No broker credential handling is present.
- [ ] No Binance credential handling is present.
- [ ] No password or token capture is present.

## 7. Visual Scan

- [ ] Information hierarchy is scannable.
- [ ] Panel labels are clear.
- [ ] Fixture values are readable.
- [ ] Critical warnings are visually distinct.
- [ ] Static/read-only limitations are visible enough for the reviewer.

## 8. Operator Comprehension Scan

- [ ] The local operator can tell what the shell is showing.
- [ ] The local operator can tell what the shell cannot do.
- [ ] Strategy state language is understandable.
- [ ] Risk and opportunity language is separated clearly.
- [ ] Confusing or ambiguous states are captured as feedback.

## 9. LDD Full-Market Scope Reminder

- [ ] Reviewer confirms this reminder remains visible and understood:

```text
LDD scope is the entire U.S. equity market, not only existing or former positions.
```

- [ ] Reviewer does not narrow QA expectations to existing or former positions only.

## 10. Customer-Facing Readiness False Confirmation

- [ ] Static shell is not customer-facing.
- [ ] Static shell is not production UI.
- [ ] Static shell is not hosted.
- [ ] Static shell is not ready for public release.
- [ ] Any request to make it customer-facing is categorized for a future gate.

## 11. Feedback Categorization

Classify every feedback item as one of:

- [ ] blocking clarity issue
- [ ] non-blocking UX improvement
- [ ] documentation refinement
- [ ] future product candidate
- [ ] forbidden-scope request
- [ ] out-of-scope live/runtime request

## 12. Final QA Reviewer Notes Placeholder

Reviewer:

Review date:

Review role:

Overall review status:

Blocking clarity issues:

Non-blocking UX improvements:

Documentation refinements:

Future product candidates:

Forbidden-scope requests:

Out-of-scope live/runtime requests:

Final notes:
