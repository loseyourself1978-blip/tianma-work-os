# R2 macOS / Safari primary-path reconciliation — 2026-10-03

Owner's current contract is macOS DMG + Tianma Work OS.app + Safari (the system-default browser). The launcher continues to use NSWorkspace.shared.open; this does not silently change the system browser. Chrome/Firefox/other operating systems are compatibility expansion, unless evidence shows a common-path correctness, security, integrity or data defect.

## Historical evidence remains immutable

101.17: 1430 passed / 5 failed / 1 skipped. 101.18 corrected full suite: 1467 passed / 1 failed / 1 skipped. Both remain FAIL in their original scope. Chrome pack_dialog-1280 timed out at 10 seconds, then at 5 seconds after SIGTERM, then killpg(SIGKILL) raised EPERM. HISTORICAL_CHROME_ROOT_CAUSE=UNKNOWN. No failure or skip was erased.

## Primary validation mechanism

Actual Safari is opened through native macOS UI. `scripts/safari_geometry_bridge.py` is a loopback-only test fixture service. Existing tests send the exact original HTML/CSS fixture and width. The actual Safari tab measures the same fixed-width iframe, including 390px and 1280px. Its event must originate from the current iframe; each result is bound to a unique job, fixture hash, width, test and observation time. Chrome user agents are rejected. Original geometry assertions remain unchanged. The ten-second browser measurement deadline is retained. A missing Safari tab or result fails; there is no fallback browser or cached PASS. Normal product clicks and modal evidence are separate from layout fixture measurements.

The bridge is test-only and is not packaged. The common full suite runs serially, with Safari measurements as part of that suite; no independent GUI/build workload runs concurrently. Chrome process-fault diagnostic tests remain included as synthetic controls. No tests are removed or ignored to implement the new support scope.

## Reviewer terminal state

Strict reviewer parsing plus required reason validation now records schema_validation=PASSED before later controller checks. A valid FAIL verdict is a valid schema and remains REVIEW_FAILED. Invalid schema remains FAILED; failed extraction or nonzero CLI exit never becomes schema PASS. Successful controller checks receive validation=PASSED. The state survives application reload. Existing historical PENDING_CONTROLLER receipts are not rewritten.

## Invocation policy

MODEL_INVOCATION_COUNT_IS_RELEASE_GATE=NO. Existing Codex quota may be used as needed; no additional paid quota or billing-path change is authorized. Historical counts remain audit records. A matching, explicitly provisioned AUDIT_ONLY_EXISTING_QUOTA engineering policy/ledger records new reservations, observed starts and outcomes without imposing the superseded cumulative cap. Environment binding, duplicate execution rejection and normal product plan/approval/budget controls remain enforced. CLI starts are not HTTP request counts. Private LDD transmission still needs its own exact-source permission.

## Artifact and acceptance

Reviewer-state and engineering-ledger changes alter runtime inputs; new internal build 101.19 is required. No Owner App/data replacement, remote Push, Tag, Release, notarization or Owner Acceptance is performed. Runtime schema remains vol20.001. New validation and artifact receipts are recorded separately from 101.18. Owner handoff is not ready until the full primary path and required real journeys are verified.

## 101.19 primary regression follow-up — 2026-10-03

The first 101.19 attempt ended INCOMPLETE (77 passed, 2 failed, exit 2) when its evidence writer reported ENOSPC. The exact source of the storage exhaustion remains unknown. Its log/XML, both failures, and the later bounded unchanged-node replay remain separate records.

The next complete primary run on source `f7085756f15eb9d1b0a432dbcb2e231ffc8e9c89` ended **FAIL: 1477 passed, 3 failed, 1 skipped, exit 1**. All three failures were HTTP 400 responses from the test bridge before measurement: the original shared-step tests used widths 884 and 1329, but the bridge accepted only 390/1280. The tests and their layout assertions were correct. Safari completed both `pack_dialog` sizes in this full run; that does not resolve the historical Chrome process-cleanup failure.

The transport now accepts bounded integer widths 240–4096, covering all original widths. Before every request it durably writes the exact fixture, input hashes and start time. A failed request retains a safe error code/status/hash, never raw response secrets. Dedicated negative controls verify HTTP rejection and timeout preservation without retries.

A width-only associated run ended **26 passed / 2 failed**: two bridge jobs timed out with no product-layout assertion failure. The old transport did not record dispatch/receipt/browser visibility, so their exact cause remains **UNKNOWN**. The event-driven bridge removes periodic browser-timer dispatch and records served/received times plus browser visibility/focus. The 10-second measurement and 12-second controller deadlines are unchanged. No old timeout is relabelled PASS or assigned an unproven root cause.

The predeclared event-driven control consisted of two serial rounds, stopping on the first failure, with no concurrent GUI/build/test workload: **28 passed**, then **14 passed**. These include actual Safari measurements at all original widths and zoom variants. Some successful measurements report an occluded/background document; this is an observation, not proof of the preceding timeout cause. These are bounded associated controls, not a substitute for a new complete regression on the frozen test input.

Only harness/tests/documentation changed after packaging 101.19. The 78 packaged inputs remain bound to `f7085756f15eb9d1b0a432dbcb2e231ffc8e9c89`, input SHA-256 `4352d3e8298ad2f64f67ee88e57afb8903cd0ca911b62f27141b8cbde8cd0201`. No rebuild is justified by those changes. The single retained full-suite skip requires the historical 101.1/101.2 artifact pair; it is not evidence of current upgrade validation.

The exact 101.19 DMG copy was launched through LaunchServices in isolated engineering storage, retaining the normal host HOME. The app handed off to actual Safari, displayed 1.0.1 / 101.19 and English by default, and completed local account and Project creation through ordinary GUI controls. This does not claim the remaining modal, restart or real-model journeys have completed. Native GUI work pauses when macOS is locked; no repeated execution or fabricated GUI result is permitted.

## Same-package real journey and update preparation — 2026-10-05

The later complete 101.19 primary run passed: 1494 passed, 0 failed, 1 skipped, exit 0 (1495 collected). The old 1478/16/1 FAIL remains historical. Actual Safari restart/readback and six real CLI invocations then completed: two non-sensitive source-grounded LDD reports, non-clinical Dashu planning, TWOS planning, bounded execution and independent read-only review. The reviewer reached schema PASSED and verdict PASS. A real local child candidate was built. These are engineering results, not Owner acceptance, private-source egress permission or public distribution.

The next ordinary GUI action, “Prepare backup and update review”, failed with INSTALLATION_BUSY. A new HTTP integration test reproduced the same failure without a provider. Root cause: the iteration endpoint acquired the ordinary shared maintenance request lease and bypassed the maintenance mutation coordinator, then requested an exclusive backup while request/pool/background-reader leases still existed. A session commit alone cannot release those leases. Prior iteration tests ended before a successful candidate update preparation and missed this boundary.

The bounded correction uses the existing Owner-authenticated maintenance coordinator, closes/disposes the validation session before the exclusive snapshot, preserves request/worker exclusion, and writes an update preview only after a sealed backup. The exact POST route is exempt from the shared request lease solely because it enters that coordinator. Unrelated requests retain their leases. Project ownership, recovery epoch, candidate revision/plan/hash, separate update confirmation and external connection exclusion remain enforced. No schema change or automatic installer is introduced.

New tests exercise a real sealed backup, authentication/origin/project refusal, missing/stale candidate evidence, active/settling work, external lease conflict, visible disk failure with explicit retry, and overlapping requests. The initial reproducer failed as expected; 137 scoped/associated tests subsequently passed. Runtime inputs changed, so build 101.20 is allocated only after confirming it was unused. 101.19 and its child remain immutable evidence. New artifact/full regression and packaged GUI completion are pending until recorded separately; no inherited result certifies new inputs.
