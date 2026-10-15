# R2 response-contract recovery

This continues R2; it does not grant Owner acceptance or change delivery scope.
The 101.16 engineering result (1405 passed, 1 skipped) remains scoped to its old
inputs. The ninth real CLI invocation remains FAILED. Its exact non-sensitive
response is retained as an offline rejection fixture; it is never repaired or
relabelled as a successful execution.

## Controller contract

The shipped `iteration-patch.schema.json` is the single strict producer/consumer
contract. `codex exec --output-schema` receives an invocation-private copy with
its SHA-256 recorded. The prompt includes that exact schema; the parser uses the
same file and rejects duplicate/extra fields, missing summary, wrong types and
an extra `noSourcesDesc` layer. The reviewer has its own strict two-field schema.
The plan binds schema fingerprints and controller build-input fingerprints;
changed contracts require a new plan and approval.

Each CLI invocation has a fresh private `--output-last-message` path. The
controller separately tracks process status, JSONL terminal events and final
file extraction. A terminal success plus exactly one matching final agent
message is required. Missing/empty/linked files, ambiguous messages, malformed
or incomplete event streams, refusals, errors, nonzero exits and cancellation
cannot become an accepted candidate. Raw provider stderr is not exposed.

Only the two approved paths may change. Both language values must change from
the immutable Git baseline; every non-target catalog value must remain equal to
that baseline. The platform invariant is separate from the model's unittest.
The unchanged model unittest also runs against before/one-sided negative
controls in the same read-only, no-network, no-child-process sandbox. A test
that accepts those controls blocks independent review. Semantic quality still
requires the separately invoked readonly reviewer.

## Engineering allowance

The normal GUI environment budget remains a separate, tightening constraint.
An optional locally provisioned engineering invocation policy binds an exact
environment to a shared private, locked ledger. The gate runs before the CLI
adapter; it cannot grant authority or raise the environment budget. It reserves
one immutable execution ID and ordinal, records whether the process start was
actually observed, and never automatically releases an uncertain reservation.
Other environments, wrong phases, duplicate executions and exhausted total
limits fail closed. This is engineering enforcement, not a new billing path.

The current authorized experiment is cumulative 9 before / maximum 15 overall,
with six new slots: document, document, document, planner, executor, reviewer.
The old project's unused reviewer allowance is transferred, never duplicated.
Historical failed records remain unchanged. CLI starts are not HTTP counts;
internal HTTP counts remain unknown where the CLI does not expose them.

## Bilingual modal

Source-view labels and errors carry the same live localization bindings as the
open dialog title and controls. Switching English/Simplified Chinese updates
those nodes without closing the dialog or rewriting source text, hashes,
drafts, task output language, plans or approvals. Counted actions are labelled
model CLI invocations in both languages.

## Validation scope

Offline fixtures and real local CLI transport against an isolated loopback
fixture are separate from real provider evidence. The loopback experiment uses
an empty credential home and a kernel policy denying external networking. It
proves local parameter/schema/result-file compatibility only. Final packaged GUI,
real provider execution, readonly review, child-candidate update/restart/rollback,
full regression and private-source authorization retain their independent gates.
No external Push, Tag, Release, notarization, trading, clinical permission or
Owner business action is authorized by this record.

## 2026-10-02 packaged journey: blocked, not an Owner handoff

The paragraphs above describe the frozen implementation contract, not a claim
that all R2 gates passed. Parent 101.17 was built from
`95e18ecfcfd77d4a181ca36556f37740c1d1b648`. Its 77 build inputs have aggregate
SHA-256 `da18849db1abe713e5a14c9d3b5dab9f0f797f4556c650722acfd08f78741d4c`.
The retained local engineering DMG has SHA-256
`722621eb0bb8ae0ca59f38ab4cf6889767a13577bf4440af9c6f6200b82ccdd8`.

A fresh engineering environment used this same installed parent through normal
GUI actions. Real CLI invocations 10 and 11 produced source-linked reports from
synthetic LDD inputs, including changed-input continuation. Invocation 12
produced a nonclinical Dashu plan with human gates still pending. Invocation 13,
the new development planner, failed with `RESULT_FINAL_AMBIGUOUS`; its process
exit was zero, but no plan was accepted. The dependent executor and independent
reviewer were not started. Global usage is 13 of 15, with two unspent slots
still allocated to the stopped executor/reviewer. No retry or reallocation
occurred. Internal HTTP counts remain unknown. No real generated diff, child
candidate, child installation, update return or child rollback is claimed.

Two real-path defects remain:

1. The local CLI 0.156.1 omits message phase in its JSONL `agent_message` output.
   An additional actual-CLI offline fixture sent commentary and a final result;
   the invocation-owned final file correctly matched the last message, but the
   frozen adapter rejected both phase-less messages. The earlier transport
   fixture had only one agent message, while a unit substitute preserved phase,
   so neither exposed this compatibility defect. The real invocation 13's raw
   text and final-file hash were not retained before temporary-file cleanup.
   Its exact message difference is therefore unknown; the offline fixture
   proves the failure class, not a byte replay of that lost output. Follow-up
   must preserve safe failure counts/order/hashes and test unambiguous final
   channel binding without accepting stale, mismatched or arbitrary messages.
2. The still-open source-reading dialog updates its original-content label in
   both language directions and preserves the body and hash. The still-open
   import dialog's `importBoundary` notice lacks a live localization binding,
   however, and remains Chinese after switching to English. The existing test
   omitted that product-owned notice. R2-CONT-002 is consequently only partially
   remediated; complete bilingual coverage is not accepted.

The parent's normal GUI restart preserved the new projects, sources, works,
executions, activity and budget without a new CLI invocation. Private LDD
selective import/readback was separately checked locally; private source IDs
were absent from model inputs. A private-source model result remains blocked
on exact egress authorization and is not replaced by synthetic reports.
Original Owner business records and delivered Git identities were unchanged
within the explicitly captured comparison scope. Private source bodies,
accounts, databases and raw private logs are not included in this public note.

The sole next checkpoint is `R2-101.17-FINAL-CHANNEL-COMPATIBILITY`, beginning
with offline fixes and their negative tests. Changed product inputs require a
new provenance identity; earlier successful calls must not be relabelled as a
replacement parent's complete journey. The two remaining allocations cannot
fund or authorize a new six-call journey by themselves. No Owner installation,
additional model call, paid quota, public release or acceptance is requested by
this note. Prior 101.6 local acceptance remains closed and preserved.

### Frozen-input complete regression

The single complete run finished with **1430 passed, 5 failed, 1 skipped**,
exit code 1, in 6901.36 seconds (pytest console duration). The retained XML
reports 6901.156 seconds for its test suite. This is **FAIL**, not a total
assembled from earlier directed runs or the historical 101.16 result.

The two guided-layout failures (`guide-390`, `pack_dialog-1280`) did not produce
the headless browser geometry marker. The three independent-preflight failures
(`remote`, `git`, `workspace`) did not reach `blocked` within their five-second
test deadline. Retained synthetic databases show no model process started;
two later shutdown receipts are not proof that the required preflight block
occurred, and the third retained row was still `starting`. The underlying
runtime-versus-fixture/timing cause is not established by those observations.
Do not dismiss them as harmless or weaken the assertions.

The skipped historical artifact-pair upgrade/rollback test requires both
retained desktop artifacts. This run did not supply that pair. The new parent's
normal restart evidence does not replace that missing historical-pair test.

One subsequent serial diagnostic run of exactly those five failures passed
all five in 45.02 seconds, without product/test edits or real model calls.
This establishes a differing isolated outcome, not the cause of the earlier
failures. The original complete result remains FAIL. No second complete suite
was run, no assertion or timeout was weakened, and the directed outcome is not
added to the full-suite count.
