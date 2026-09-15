# Vol.19 19.3 Backup / Restore / Migration / Failure Recovery Contract v0.1

Status: IMPLEMENTED / OWNER ACCEPTANCE PENDING. Only the Owner may declare
19.3 Owner Acceptance PASS. Application version remains 0.17.0 and schema
remains vol19.005. The accepted 19.1 and 19.2 gates are preserved.

## Installation and migration audit

The authoritative starting worktree is main at
`8e91c2b37f592192bfbf4e3e6a24a65cfee7a509`, seven commits ahead and zero behind
`origin/main` at `3cf914b6c5667059923ab209f8e9008b33a05cef`.

`config.py`, `first_run.py`, `db.py` and `app.py` define the installation.
SQLite owns accounts, Tasks, immutable Packs, Runs, Verification, Results,
approvals, delivery evidence and tool configuration. Fresh Install also binds
an installation UUID and a machine-local data root, database, runtime, logs,
loopback endpoint and authorized workspace identity. Runtime environment,
source repositories, Run worktrees and provider credentials are distinct from
logical account data. Legacy installations without an Installation row receive
a private persistent logical UUID at their first explicit backup.

Ordinary startup already invoked an ordered additive migration engine. Fresh
Install rejects existing foreign/older databases before initialization; this
accepted one-time First Owner and startup contract is unchanged. The ordinary
engine now snapshots and stages structural migration before atomic activation.
A startup-engine intent is recorded as EXISTING_STARTUP_ENGINE, never as Owner
approval. An interrupted/failed migration is not automatically retried.

The public historical migration matrix is accepted vol19.003 (19.1) and
vol19.004 (19.2A) to vol19.005. Earlier or partial schemas retain the existing
low-level engine compatibility behind the same recovery envelope; this is not
an additional Owner-accepted migration matrix. A failed unsupported engine-era
migration requires the prior compatible runtime/operator recovery. No new
multi-Owner administration or legacy Task ownership adoption is introduced.

## Versioned backup

TWOS_BACKUP_V1 is a sealed local directory ending in `.twos-backup`. The exact
Owner-visible destination is private storage beside the active database,
under its dedicated maintenance directory. Directories are 0700 and files
0600. The UI warns that backups contain sensitive TWOS content. Encryption,
cloud storage and scheduled backups are outside 19.3.

The manifest records format, app/schema versions, creation time, source logical
installation identity, logical components, every file size/SHA-256, a canonical
manifest digest and SEALED completion. Only a partial directory is written
until its database and exact material are validated, manifest sealed and final
rename/fsync completed. Incomplete artifacts are never valid backup choices.
Hashes detect corruption; they are not a signature or authentication service.

Included: SQLite logical records and audit evidence, account password hashes
and salts, application-managed/tool configuration records, immutable Result and
Verification evidence, Apply before/after material and delivery receipts. Exact
attributed Result postimages are archived as inert evidence, including Results
not yet Applied. Every archived byte is bound to Result path/hash/size and the
immutable Run workspace identity or canonical Apply journal. Rebackup after
restore can use that inert archive without accessing an old source worktree.

Excluded: active login sessions and setup tokens, plaintext passwords, Codex
credentials/auth files, provider secrets, cookies, external Git credentials,
source repository contents, arbitrary workspace/filesystem contents, .git,
virtualenv/Python/Codex installations, shell files, transient sockets/PID files,
spools and temporary logs. Credential-like persisted content fails closed
without exposing its value; immutable evidence is not silently redacted.
Historical path/PID fields remain evidence only, never executable authority.

Backup checks active Run admission/execution, terminal Result settlement, Apply,
Revert, unresolved Stage, Commit and Push. Another request, worker, pool or
runtime connection blocks exclusive maintenance with an exact next action.
Both ORM connections and API inspection requests hold shared cross-process
leases. Mutation requires exclusive storage admission and stopped background
services. Terminal historical evidence is allowed.

## Explicit restore

Select → Inspect → Verify integrity/compatibility → Review Restore Plan →
Approve Plan → literal Confirm Restore → private staging → verify → atomic
activation → verify active state → durable receipt.

The plan binds the installation Owner, active logical digest, backup integrity,
from/to schema, recovery point and consequences. Login session churn alone
does not stale a plan. All other logical changes require a new review. The
backup must belong to this logical installation and Owner. Restore does not
silently replace a different installation or provision an unrelated account.

Only enumerated regular files are admitted. Traversal, symbolic links,
hardlinked/special files, unknown components, missing database/material,
unsupported versions and mismatched hashes are rejected before activation.
Required Result material is cross-checked against database lineage, not merely
the manifest's own file list. Approved bytes are copied into private staging
and reverified so source changes after review cannot change the activation.

The prior healthy database remains a verified recovery point. Restore activates
only a fully checked staged database under the exclusive lease and durable
journal. Current installation machine paths are rebound from the current
installation record, not blindly trusted from the backup. Source files are
outside backup/restore and never changed by maintenance.

After restore, sessions are revoked, schedules paused, tools require explicit
readiness and configuration confirmation, and workspace reauthorization is
mandatory. Paths are rechecked by the canonical authorization validator;
missing/moved/symlink/escaping paths do not authorize themselves. Reauthorization
persists path, device/inode, canonical workspace identity and local data-directory
context. Startup reconstructs that verified binding even when old operator
settings still name another source path; drift requires reauthorization. Each
reauthorization rotates the configuration epoch and freezes preceding execution
authority. Restored Packs,
Runs, drafts and delivery objects remain immutable historical evidence. Real
public IDs and numeric compatibility IDs are checked before old actions can
be used. Future work requires a new approved Pack bound to the recovery epoch.
No worker, Run, Verification process, Apply, Stage, Commit, Push or provider
request is replayed.

## Migration and interrupted operations

The migration engine itself remains ordered and canonical. Real accepted
historical source trees create isolated fixtures through account, Task, Pack,
approval, deterministic Run, independent Verification, Result, Apply, post-Apply
validation, Commit and local-only Push APIs. Tests do not insert terminal rows.
Existing data/columns are compared with the real pre-migration recovery point;
new Task ownership remains NULL and missing tools do not become configured.

The durable journal lives outside the replaceable database. It distinguishes
started/staged/activating/activated/complete/failed and RECOVERY_REQUIRED or
RECOVERY_COMPLETE states. Receipts, recovery-point hashes and the authority
epoch are durable. Startup reconciles an unfinished journal before normal
migration, Run recovery or Apply reconciliation.

Incomplete backup: remove its partial artifact and preserve the installation.
Restore before activation: discard staging and retain/restore the verified prior.
Interruption around activation: compare the active file with the staged hash;
finalize only a verified activated state, otherwise restore the verified prior.
Migration failure: preserve or restore prior, expose failure and require an
explicit supported plan or prior-compatible-runtime recovery. No migration
retry or external action occurs automatically. If neither healthy state can
be established, normal APIs and background services stay blocked immediately,
including shutdown reconciliation; exact recovery evidence remains available.

## Owner interface and phase boundary

Backup & Recovery is available from the account menu and as a maintenance-only
startup surface with TWOS_MAINTENANCE_MODE. Page load reads local status/data
only. The Owner sees app/schema, readiness/recovery, sensitive-data warning,
baseline Tasks and one current primary action. Inspection, plan approval and
final confirmation remain separate. Hashes, paths, manifests and journals are
under Advanced; exact backup path remains visible/copyable. Long values wrap
at desktop and narrow mobile widths.

19.3 does not establish Owner Acceptance, signed packaging, 19.4, 19.5,
external credentialed Git-host Push, cloud/encrypted backup, live multi-model
aggregation, email/calendar, TWOS 1.0 RC or version 1.0.0.
VOL19-19.2B-UI-01 remains OPEN / NON_BLOCKING / MUST_CLOSE_BEFORE_19.5, targeted
for 19.4. This phase does not change that Review Commit button.
