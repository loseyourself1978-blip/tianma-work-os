# TWOS Vol.16 Closeout and Vol.17 Handoff

## Accepted Source Identity

- Volume: Tianma Work OS Vol.16
- Product milestone: TWOS 1.0 Productization Sprint 1 — Self-Hosting Workbench
- Runtime version: `0.16.0`
- Branch: `main`
- Accepted base and expected closeout parent: `10bb7914f0a9f7c2cf1cd0874312f49949f24f7b`
- Upstream reference at closeout audit: `c97ef1faf586271b0c17a4d51642e1013d257f97`
- Local closeout commit: pending explicit Owner authorization
- Merge and push: not authorized

## Final Accepted Functionality

Vol.16 completes the Owner-controlled product loop for local TWOS product development:

1. Sign up, log in, and log out through the canonical authentication surface.
2. Create and save a TWOS product-development task.
3. Compose and explain the minimum effective AI Team and routing decision.
4. Generate a versioned Codex Instruction Pack.
5. Approve the exact Pack version as Owner.
6. Run the approved Pack through a real local Codex CLI in an isolated worktree.
7. Review process- and Git-derived result evidence.
8. Enforce blocking Owner Acceptance decisions.
9. Persist the accepted Compact Sync.

## Authentication Rewrite

- Sign up and log in share one explicit username normalization rule.
- Password creation and verification share the same supported password-record format.
- Password input is not silently trimmed or stored in plaintext.
- Successful authentication uses an HttpOnly cookie session rather than returning a bearer token to the application UI.
- Public authentication failures remain generic while internal diagnostics retain non-secret reason categories.
- Signup success is returned only after the complete Owner record commits.
- Missing, malformed, unsupported, inactive, and database-failure states follow safe product contracts.
- The local Owner recovery command is disabled by default, requires explicit local confirmation, preserves product records, revokes active sessions, records a non-secret audit event, and becomes unavailable after successful use.

## Responsive Workbench Result

- The Workbench HTML was rewritten around the Owner's task-to-acceptance sequence.
- The responsive CSS supports desktop and compact layouts without moving runtime internals into the default flow.
- The application behavior is implemented in one external local JavaScript module.
- Authentication, task editing, AI Team composition, Pack lifecycle, Run controls, result review, Owner Acceptance, and Compact Sync are visible product operations.
- Provider, model, audit, scheduler, raw output, and Git/runtime details remain under Advanced.
- The frontend has no inline script bodies, inline event handlers, CDN dependency, or external frontend runtime dependency.

## Self-Hosting and Real Codex Evidence

- Codex readiness requires both `codex --version` and `codex exec --help` to exit successfully.
- The approved Pack is revalidated immediately before launch and is supplied through standard input to a fixed no-shell command.
- The child process receives a minimal environment, runs in an isolated worktree, and is subject to timeout, cancellation, process-tree cleanup, and a combined output cap.
- Run completion is derived from process status and Git evidence, not fabricated application output.
- Source main must remain unchanged; commits, merge commits, configured push targets, automatic merge, and automatic push prevent a successful boundary result.

Canonical accepted evidence:

- Pack 6, version 1, remains approved and not invalidated.
- Pack SHA-256: `7f4427c86dd8543ef947dc62aaca7a46c10db1f40801393ae7f0582455f0ee22`
- Run 1 completed with exit code 0.
- Run 1 was not timed out, cancelled, or output-truncated.
- The only changed path was `docs/runtime/VOL16_CODEX_SMOKE_RESULT.md` inside the isolated Run 1 worktree.
- The file contained exactly the approved timestamp-free confirmation and one trailing LF.
- Pre-run and post-run commits both matched the accepted base.
- No commit, merge, push, source-main change, or configured push target was produced.
- The smoke-result file is intentionally absent from source main and is not part of the closeout manifest.

## Owner Acceptance and Blocking Evidence

Run 1 is the canonical accepted product result:

- Acceptance Session 1 is accepted.
- All five required acceptance items are Pass.
- The accepted result generated Compact Sync without merge or push.

A later Run 2 is retained as a separate cancellation and fail-blocking exercise:

- Run 2 was explicitly cancelled and was never accepted.
- Its acceptance session remains in Owner review with blocking Fail/Pending items.
- No accepted-result event exists for Run 2.
- The persisted state proves that blocking items did not become an accepted result.
- Automated acceptance tests independently prove that Accept returns a conflict until every required item is Pass.
- Rejected HTTP conflict attempts are transactional and are not represented as standalone audit events; no claim of such an event is made.
- The Owner classified this separate cancellation/blocking exercise as Pass for Vol.16 closeout. It does not supersede accepted Run 1.
- The task's current lifecycle status reflects the later Run 2 cancellation, while its accepted state and canonical Compact Sync remain bound to Run 1; closeout consumers must use explicit run and acceptance-session identities rather than treating the latest run as the accepted result.

## Compact Sync Persistence

- The Run 1 Compact Sync remains persisted on both the task and its accepted Owner Acceptance session.
- The two persisted copies remain byte-identical after application reload and the later cancellation exercise.
- Compact Sync identifies the accepted run, changed file, validation result, baseline, worktree state, and no-merge/no-push boundary without storing credentials or raw Codex output.

## Security and Boundary Result

- No plaintext password, password hash, authentication cookie, session token, provider token, private key, or raw Codex output belongs in the closeout commit.
- `live_trade`, `live_bet`, broker-order, and betting-order execution remain denied.
- No arbitrary command endpoint or unrestricted shell endpoint was added.
- Codex is started only by the authenticated explicit Run action; Pack approval alone never starts a run.
- No silent external send, fake Codex result generation, automatic merge, automatic push, or force push is implemented.
- Runtime databases, caches, local environments, temporary worktrees, screenshots, profiles, logs, and process files remain local and excluded from Git.

## Validation Summary

- Full suite: 45 passed.
- Authentication suite: 19 passed.
- Self-hosting suite: 17 passed.
- Existing runtime suite: 9 passed.
- Python compilation, JavaScript syntax, HTML parsing, duplicate-ID, canonical local asset, no-inline-script, and no-inline-handler checks passed.
- Migration, legacy authentication compatibility, malformed-Owner recovery, cancellation, timeout, output-cap, exact-Pack, dirty-source, untracked-whitespace, no-commit, and live-denial checks passed.
- The only warning is the known Starlette/httpx TestClient deprecation warning.
- Git whitespace, credential, machine-path, runtime-database, shell, automatic execution, merge, and push scans passed.

## Deferred Vol.17 Backlog

These items are accepted non-blocking deferrals. They are documented here and are not implemented by this closeout.

### VOL16-OA-003 — Fresh Signup Messaging Revalidation

- Fresh Sign up may surface incorrect authentication messaging in some states.
- Revalidate the complete signup path against a genuinely empty database in the next version.

### VOL16-UX-004 — Evidence-Backed Model Assignments

- AI Team currently exposes capabilities but not model-to-capability assignments.
- Future target examples include Planning mapped to a configured planning model, Coding mapped to a configured coding model, and Verification mapped to a configured independent verification model.
- Never claim that a model or provider was invoked without real configuration and runtime evidence.
- Mark simulated assignments explicitly.

## Git and Release State

- The accepted Vol.16 product changes and this handoff remain unstaged in the local working tree.
- The expected local closeout commit message is `feat(twos): complete Vol.16 self-hosting workbench`.
- Commit, merge, push, force push, and origin changes remain pending explicit Owner authorization.
- Vol.17 implementation has not started.
