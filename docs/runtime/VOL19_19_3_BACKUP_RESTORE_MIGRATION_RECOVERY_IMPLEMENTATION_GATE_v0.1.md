# Vol.19 19.3 Implementation Gate v0.1

Status: IMPLEMENTED / OWNER ACCEPTANCE PENDING.
Automated implementation validation: PASS. No Owner Acceptance PASS is claimed.

## Baseline and routing

main started clean at `8e91c2b37f592192bfbf4e3e6a24a65cfee7a509`;
origin/main remains `3cf914b6c5667059923ab209f8e9008b33a05cef` (7 ahead / 0 behind).
Application 0.17.0, schema vol19.005. The primary is the sole writer, integrator,
full-suite runner and commit creator. Two read-only auditors reviewed migration
architecture and runtime/delivery recovery boundaries. No write agent was used.

## Implementation

`maintenance.py` owns the sealed backup format, compatibility/integrity checks,
exclusive database lease, exact Result material archive, staged restore,
recovery points, durable journal/receipts and recovery authority.
`maintenance_api.py` provides Owner-only maintenance, explicit review/approval/
confirmation, request admission and recovered-object action gates. `db.py`
wraps the existing migration engine and `app.py` reconciles maintenance before
ordinary runtime recovery. `guided_delivery.py` binds future configurations to
the recovery epoch. The account menu opens the separate responsive maintenance
surface; accepted 19.2B Review Commit button behavior is unchanged.

See VOL19_19_3_BACKUP_RESTORE_MIGRATION_RECOVERY_CONTRACT_v0.1.md for the format,
state machine, startup compatibility and security boundaries.

## Historical migration matrix

| Authentic source | Schema | Target | Preserved representative evidence |
| --- | --- | --- | --- |
| `3cf914b6c5667059923ab209f8e9008b33a05cef` | vol19.003 | vol19.005 | Owner, Task, approved Pack, deterministic Run, independent Verification, Result, Candidate, Apply, post-Apply validation, Commit and exact local bare-remote Push SHA |
| `e51e1c4cd092fd992749c69f83999f994f7faeb4` | vol19.004 | vol19.005 | Same complete delivery chain plus canonical Fresh Install, one-time Owner and workspace evidence |

Each fixture executes modules from a read-only Git archive of the accepted
commit in an isolated directory; the active worktree and parent checkout are
not switched or modified. The current migration engine advances a staged copy.
Old Task.owner_user_id becomes NULL and absent Guided Tool Setup stays absent.
Repeated initialization is idempotent. Pre-19.1/partial-engine compatibility
has separate recovery tests and is not presented as a new public migration
acceptance matrix.

## Automated evidence

The primary ran the following gates serially. The final complete run includes
all accepted regressions and the final workspace-binding correction.

| Gate | Passed | Failed / skipped / xfail | Pytest duration |
| --- | ---: | --- | --- |
| Focused 19.3, including migration, failure recovery, security and UI | 93 | 0 / 0 / 0 | 120.26 s |
| 19.2B | 64 | 0 / 0 / 0 | 189.34 s |
| 19.2A | 54 | 0 / 0 / 0 | 153.22 s |
| Accepted 19.1 delivery/runtime regressions | 177 | 0 / 0 / 0 | 826.10 s |
| Self-hosting and TWOS runtime | 71 | 0 / 0 / 0 | 310.25 s |
| Owner acceptance runtime and lifecycle/settlement regressions | 35 | 0 / 0 / 0 | 76.66 s |
| Complete repository: `.venv/bin/python -m pytest -q` | **1092** | **0 / 0 / 0** | **3416.16 s** |

The runtime groups total 106 passing tests. Each gate reports only the existing
Starlette TestClient/httpx deprecation warning. No new skip or xfail was added.
The host's existing fallback Git executable was used because system Git is
blocked by the Xcode license prompt; no license, dependency or installation was
changed to run validation.

`node --check`, Python `compileall` and `git diff --check` pass. The focused
tests prove fresh database initialization, restart persistence, sealed backup
hashes, restored logical state, authentic historical migration, process
interruption recovery, credential exclusion and filesystem containment.
Real browser geometry passes at 1280px and 390px with long Advanced paths.

Final process reconciliation found no remaining validation process. All 70
maintenance journals in the completed full-suite fixture tree were terminal
before cleanup, with no unresolved journal or partial artifact. Both authentic
historical fixture identities were verified before removing this run's isolated
temporary tree. Test logs remain as validation evidence. File-handle checks
assert recovery before teardown, including repeated rejected DBAPI admission;
no SQLite/file-descriptor growth remains. Unrelated runtimes were untouched.

Test files:

- test_vol19_maintenance.py: explicit current backup/restore, fresh initialization,
  restart, faults/interruption, corrupt sources, path/secret isolation, Owner gates,
  leases, no replay, unapplied Result material, independent reconstructed-Settings
  workspace restart/revalidation and file-handle reconciliation (including
  rejected connection admission).
- test_vol19_maintenance_migration.py: authentic .003/.004 migrations and delivery,
  migration failure/interruption/restart, data preservation, safe defaults,
  current backup/restore of accepted evidence, actual public-ID action gates,
  material completeness and existing partial-engine recovery.
- test_vol19_maintenance_ui.py: passive page load, explicit ordered primary
  actions, duplicate suppression and real 1280px/390px browser geometry.

No live Codex/provider capacity is used. Source/remote fixtures are local-only.
No accepted 19.1/19.2A/19.2B tests are weakened or changed.

## Owner Acceptance boundary

Prepare isolated current, authentic legacy and corrupt-backup scenarios from
the implementation commit, with temporary accounts and exact current paths
reported outside repository documentation. Do not record passwords, tokens or
obsolete acceptance paths here. Owner must explicitly create Backup, approve
and confirm Restore/Migration, inspect the corrupt source rejection, and verify
refresh/restart persistence. Only the Owner may close 19.3.

No source Push, tag, amend, 19.4 implementation or 19.2B follow-up correction is
part of this gate. TWOS 1.0 RC remains NOT COMPLETE and 1.0.0 NOT RELEASED.
