# R2 final-channel compatibility — offline engineering continuation

Routing: SINGLE_PRIMARY. This checkpoint authorizes zero new real model starts.
The shared R2 ledger remains 13/15; the remaining executor/reviewer allocation
is unchanged. CLI starts, internal HTTP requests and offline fixture processes
are different quantities. No Owner acceptance or real-iteration completion is
claimed here.

## Final result and failure evidence

The former adapter required exactly one non-commentary message. Actual CLI
0.156.1 can emit several agent_message items without phase, even when its
upstream fixture supplies commentary/final_answer. The adapter now validates a
single complete turn, stable item identities and event order, then binds the
current invocation's private output-last-message file to the final completed
agent message. Repeated identical items are idempotent; conflicting item IDs,
explicit final answers, terminals, missing/old files and content mismatch fail
closed. File bytes are hashed without stripping. Only an empirically checked
single appended LF may differ from the matching event text.

Execution/project/phase, input/plan hash, CLI wrapper/native identity, shipped
schema and controller fingerprints accompany the receipt. Extraction does not
mean schema, patch, deterministic tests or independent review passed. The
structured schemas and controller scope checks are unchanged. Original failure
9 remains rejected. Original failure 13 remains EVIDENCE_GAP: no original final
bytes exist to replay, and the offline fixture cannot reconstruct them.

The adapter persists bounded private diagnostics before temporary cleanup:
ordered JSONL, final bytes when safely readable, hashes, errors, exit/signal and
availability. Secret-pattern payloads are withheld. Directories are 0700; files
0600; no prompt, credentials or raw stderr are copied. Output is bounded at
2 MB; final at 1 MB; at most 200 events, 32 private receipts and seven days for
finished receipts. Active receipts are never deleted to make space; capacity
fails closed. Disk failure is recorded as NOT_CONFIRMED, never replayable, with
no retry invocation. Recovery reports interrupted evidence, never resumes work.
The browser receives safe status/hash identifiers, not private raw diagnostics.

Official protocol references: [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
and [CLI developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli).
Actual local binary/fixture evidence, not these pages alone, binds compatibility.

## Dynamic localization

Open dialogs use one localization function for text, placeholders, accessible
labels and titles. Locale saves are serialized; async insertion localizes using
the current locale. Import boundary, classifications/reasons, manifest and
installed-state copy are bound in place. Candidate/update confirmation retains
the shared language/close shell. Original content, hashes, input values, source
selections, plan/approval data and output language are not translated.
Native file-picker chrome is owned by macOS and excluded from product wording.

## Regression investigation limits

See VOL20_R2_OFFLINE_REGRESSION_PROTOCOL.md for bounded rounds declared before
execution. The original 101.17 complete result remains 1430/5/1 FAIL.
Archived preflight timestamps show workspace preparation finishing 4.93–5.43s
after queueing: the five-second POST-based assertion included preparation and
could trigger teardown before the boundary reads under test. A controlled
preparation stall and cancellation test separately exercises that condition.
The corrected measurement has a bounded ten-second preparation wait followed
by the unchanged five-second terminal assertion. The existing one-second child
execution timeout still begins at actual launch. Tests assert normal terminal
writes and worker joins before teardown, and late work after cancellation may
not launch a process. Runtime timeout or permissions have not been relaxed.

Both archived browser marker failures lack exit/output-stage diagnostics;
their exact historical root cause is UNKNOWN. Current quiescent geometry cases
pass, and future failures now preserve bounded complete stdout/stderr, signal,
profile, measurement/marker time and termination method. An observed Chrome
SIGABRT under the tool's restricted sandbox is a distinct captured condition,
not proof of the historical cause. Do not claim the old browser stability gap
is resolved merely from a fresh green run.

## Handoff boundary

Build 101.18 is reserved for one internal OFFLINE_FIXTURE candidate, subject to
actual build receipts. It is not an Owner installation handoff. Final packaged
GUI, full-suite outcome and outstanding gates are reported in private evidence;
this document does not predeclare their outcomes. No public Push, tag, release,
notarization, private-source egress or original Owner business action is allowed.
