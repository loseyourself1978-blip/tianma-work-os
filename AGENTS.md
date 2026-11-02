# TWOS engineering and closeout

## Routing and ownership

Default to SINGLE_PRIMARY. Emit a routing receipt before substantial engineering.
The primary owns edits, integration, full validation, local Commit preparation,
Push preparation and final reconciliation. Preserve Owner-approved dirty work.
Never reset, clean, amend, force-push or discard it.

Read-only auditors are appropriate only for at least two independent evidence
domains, without timing-sensitive test interference. Use at most two; they must
not edit files or run the complete suite. Multiple writers require separate clean
worktrees and explicit Owner approval before they are started. When uncertain,
remain SINGLE_PRIMARY. Run complete diagnostic and final suites serially.

## Completion guard

Maintain the existing work order's checkpoint; do not create another job to
replace unfinished work. Distinguish implementation, actual GUI verification,
Owner business acceptance, Owner product acceptance and public release.

An unresolved Owner report about the product is implementation work, not merely
"Owner acceptance pending". Inspect the actual affected interface when available,
compare the reported behavior with the agreed requirements, and either fix and
verify the gap or record concrete evidence that explains the behavior. A button
existing in code, a matching hash or a green protocol suite is not proof that the
product interaction is discoverable and usable. Verify visible state as well as
correct identity and side effects for a UI regression.

Before a final response, reconcile every open feedback item with its requirement,
actual change or evidence, validation scope, and remaining action. Do not end
with "can fix next" while authorized implementation or executable verification
remains. Continue without another "continue" request. Stop only when the scoped
engineering work is complete with an exact handoff, the Owner explicitly pauses,
or a concrete permission/input/external blocker prevents further meaningful work.
Complete unaffected work before handing off a blocker; do not repeatedly retry it.

Implementation PASS requires the applicable complete green gate. Reuse unchanged
valid evidence when authorized, but never combine partial runs into a complete
PASS or use an accepted business artifact to close unresolved product feedback.
Only the Owner grants Owner Acceptance; Push and Tag need their own explicit
authorization. No routing or test result broadens a Phase Gate or release rights.

Do not hot-patch the running Owner App, replay accepted business tasks, mutate
their browser storage, or overwrite original failure/PARTIAL evidence for a UI fix.

## Test temporary storage

Cleanup and resource monitoring are mandatory development SOP, not an optional
Owner reminder. Before builds and long tests, record actual free bytes, CPU/load,
memory pressure and swap activity; repeat during long runs and at completion.
Distinguish immediately free disk space from macOS purgeable capacity. Reuse the
current gate's real storage requirement rather than treating Finder's combined
available figure as already free. Keep this routine quiet unless action is needed.

If sustained contention, memory pressure, rapid swapping or space exhaustion
would invalidate testing or destabilize the host, promptly tell the Owner and
defer new heavy work; continue independent lightweight work. Do not terminate
unrelated processes. Before a necessary reboot, save the exact checkpoint,
results and pending actions, safely stop only this job's owned processes, and
explicitly confirm restart readiness. Resume by reconciliation, never task replay.

Check available disk space before long validation runs. Use a dedicated,
uniquely owned test temporary directory and pytest's `tmp_path_retention_policy=failed`
so passed test fixtures do not accumulate. After each run, preserve its results
and the minimal evidence needed to investigate failures, then remove that run's
disposable temporary files. Record cleanup and remaining space. Never treat
Owner data, source changes, candidate packages, or unidentified directories as
test cache, and do not discard original failure records to free space.

Owner has also authorized timely cleanup of obsolete local installers. After
verifying a replacement and checking that no process uses the old files, retain
the current exact installer and one latest published rollback installer per
product; remove only identified superseded local installation copies. Preserve
source, hashes, provenance, notarization receipts and original validation/failure
records. Never apply this local retention policy to historical GitHub assets,
installed Owner apps, browser profiles or unidentified directories. Record the
exact removed paths and available space; no broad wildcard or Git clean.
