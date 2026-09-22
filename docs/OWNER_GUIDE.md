# TWOS Owner Guide

Start here to operate TWOS 1.0.0, schema vol19.005. You decide whether a result
is acceptable; a successful technical check is not Owner Acceptance.

## 1. What TWOS is

TWOS helps you describe a development Task, authorize a precise instruction
Pack, run Codex in an isolated workspace, inspect its Result, and deliver only
the changes you approve. It records each separate decision. Research documents
in the repository describe ambitions beyond this local candidate.

## 2. Supported platform and release identity

This local 1.0.0 candidate is a **source-based macOS distribution**, requiring Python 3.11–3.13
and trusted local Git for development workspaces. Codex is optional until Run.
A signed/notarized DMG, App Store release, and Windows/Linux acceptance are not
established. TWOS does not install system tools or accept their licenses for you.

The archive name includes `1.0.0` and the 12-character release-preparation commit prefix. The included
`RELEASE_SOURCE.json` gives the full Git SHA. The adjacent `.manifest.json`
records the SHA-256, included files, platform and limitations. Compare the
archive hash with the Owner-approved report before extracting. A hash detects
change; it does not authenticate the publisher of an untrusted download.

## 3. Fresh installation

This release supports **fresh installation only**, plus backup/restore within
1.0.0. Do not reuse a 0.17.0 data directory or restore a 0.17.0 backup. Old-version
upgrades and cross-version restore are outside this release scope and have not
been validated. Existing installation-version and incompatible-backup checks
remain enforced. Keep old installations and their data intact. If you already
have TWOS data, supply new empty `--data-root`, `--runtime-root` and `--log-root`
directories for this installation; never point these options at old Owner data.

1. Verify the received archive and retain its adjacent manifest.
2. Extract it with Archive Utility into a folder you own.
3. Open Terminal in the extracted `twos-1.0.0-…` folder.
4. Run `./start-twos`.
5. Wait for the healthy `http://127.0.0.1:…/twos` URL and open it if the browser does not open.

The first launch creates a private Python environment and installs dependencies
from `requirements.txt`. It needs the configured Python package service; it
never uses sudo or installs globally. Installation and First Run do not require
any Codex/provider request. Keep the initiating terminal open.

## 4. First Owner creation

First Run applies only to an installation with **zero Owners**. Select **Start
Setup**, confirm the installation, and create your username and unique
password (at least 8 characters). Enter the one-time setup authorization code
printed in the initiating terminal. Keep it private. After creation, use
**Log in** on this installation. First Run cannot replace an existing Owner.

## 5. Workspace authorization

Choose an exact, dedicated local folder you own and review its path. For Git
projects, authorize the repository root. Do not select your whole Home, TWOS
source/data/runtime, an overly broad parent folder or a symlink. Traversal,
symlink boundaries and incompatible nested Git roots are rejected. Project
source files are separate from the TWOS database and backups.

## 6. Guided Codex Tool Setup

You may skip optional tools in First Run and create a Task first. Later open
Tool Setup, select the trusted installed Codex executable, exact supported
model and reasoning. Sign in using Codex's own supported authentication when
required. TWOS does not copy its credential store or ask you to paste provider
secrets into ordinary UI. Local discovery is different from provider readiness.

### Configure independent Verification before Guided First Delivery

Guided First Delivery requires an Owner-reviewed deterministic local verifier,
separate from Codex Coding. It checks the resulting files against the approved
task; Coding success alone cannot establish Verification success. First Run and
Task creation remain available without this optional execution prerequisite.

Supply the verifier when starting TWOS in Terminal. Replace both example paths
with absolute paths to your trusted Python executable and read-only verifier:

```sh
TWOS_LOCAL_VERIFICATION_COMMAND_JSON='["/absolute/path/to/python3", "/absolute/path/to/trusted-verifiers/verify_first_delivery.py"]' ./start-twos
```

This is a JSON array of 1–32 nonempty strings, each at most 4096 UTF-8 bytes and
containing no NUL. The first string must identify an existing executable by its
absolute path. Use absolute paths for verifier scripts as well; keep the
executable and scripts outside the authorized source workspace and TWOS Run/spool
directories. Guided readiness also rejects control characters in arguments and
binds the exact command and file identities. JSON double quotes preserve paths
with spaces; shell expansion, pipes and redirection are not performed inside the
array. This setting authorizes no shell fallback or automatic Run.

The example assumes you already have a trusted verifier for the dedicated
`first_delivery.txt` task. It must inspect files without modifying them and emit
the existing TWOS JSONL Verification protocol: `thread.started`, `turn.started`,
an `item.completed` agent message containing a `twos.verification.v1` result,
then `turn.completed`. The result reports `verdict`, `changed_files_checked`,
`unexpected_files`, `exact_content`, `tests`, `git_boundary` and `remote_boundary`
truthfully. A command that merely exits zero, such as `true`, is not a verifier.
At Verification execution TWOS runs the exact argv in the isolated Run workspace;
it does not install or generate a verifier for you.

Use the same environment assignment on every restart, including with custom
`--data-root`, `--runtime-root` and `--log-root` options. It is not saved as an
installation setting. After restarting, open Guided Tool Setup, choose the
model/reasoning, explicitly **Check Codex Readiness**, then **Save Tool Setup**
only after Ready. Checking binds the verifier but does not execute it or start
delivery. Changing the verifier requires a new check and any required new Pack
approval; later Owner gates remain separate.

If the setting is absent or blank, readiness returns
`Configure an independent local Verification command for First Delivery.`
before any provider check or delivery execution. Malformed JSON, a non-array,
an invalid argument or an invalid array length prevents startup: the launcher
reports `BLOCKED` and the private `runtime.log` identifies
`TWOS_LOCAL_VERIFICATION_COMMAND_JSON` and the parser error. Find this log under
your `--log-root`, or by default at
`~/Library/Logs/Tianma Work OS/<installation-id>/runtime.log`. Correct the value
and explicitly relaunch. A parseable but unavailable/non-absolute executable or
unsafe verifier binding is instead rejected by Guided readiness with its
specific diagnostic. Neither case substitutes another command or starts delivery.

## 7. Readiness versus Save Tool Setup

**Check readiness** is explicit and may contact the provider using your Codex
sign-in. Opening a page does not perform that check. A successful check does
not save your choices: select **Save Tool Setup** for the exact checked setup.
Changes to executable, model, reasoning, verifier or workspace can invalidate
readiness and future eligibility. Recheck and save when requested. Fallback is
disclosed; do not assume a different model silently fulfilled your selection.

## 8. Create Task

For the first Task, enter **Task title** and the complete task body in **Goal or
objective**, including exact files, expected output and boundaries. The authorized
workspace supplies Project; keep the initial **General task** Workflow. Select
**Save Task**. The saved body is then labelled **Development task**. Task creation
does not start Codex. Derived Task details refer to that complete body; review them
if you need to add constraints. Guided Delivery shows the current next action.

## 9. Prepare, review and approve Pack

After **Check Codex Readiness** and **Save Tool Setup**, select **Prepare First
Delivery**. This configures the development workflow and binds the saved tools to
this Task and Pack. Tool readiness alone does not make a Task executable, and an
approved ordinary Pack is not a Guided configuration binding. Follow the specific
Run blocker and its next action if preparation is still required.

Select **Review Instruction Pack** to review objective, files, restrictions,
workspace identity and tools, then explicitly **Approve Instruction Pack**.
**Review Pack** also opens a read-only view of the current Pack; it does not approve
or execute anything. Correct the Task and prepare again if needed. Approve only
the exact intended Pack. An old approval cannot authorize a materially changed
version.

## 10. Explicit Run

Select **Start Codex Run**, review the confirmation for the approved Pack, then
select **Confirm Start Codex Run** once.
Watch persisted Coding and Verification states. Pending actions block duplicate
submission. If a page stalls, refresh and inspect recorded status before retrying.

## 11. Verification and Result

Coding completion and Verification success are separate. Read both, then the
captured Result and changed-file evidence. A captured Result does not itself
mean Verification passed or delivery is safe. Resolve the displayed blocker.

## 12. Accept for Delivery

Review the exact Result and Candidate, then select Accept for Delivery if they
meet your intent. Acceptance records your decision; it does not Apply, Commit
or Push.

## 13. Apply

Review the Apply Plan, included/excluded files and drift warnings. Approve the
exact Plan, then separately confirm Apply. Inspect its state. Conflicts and
material drift block execution; unrelated Owner changes remain excluded.
Revert Applied Changes is a separate guarded recovery action, never permission
to erase later work.

## 14. Validate Applied Changes

When Apply is APPLIED, select Validate Applied Changes. This checks the delivered
source separately from Run Verification. Wait for PASSED before Review Commit.
An earlier coding success cannot substitute for this check.

## 15. Commit

Enter subject/body, select Review Commit, and inspect paths, branch, parent
revision, author and exclusions. Successful review shows a neutral disabled
**Review completed**. Material dependency or message changes require review
again when prerequisites permit it; resolve Apply/Validation blockers first.
Approve the exact proposal, then separately confirm Local Commit. Exact-path
staging occurs only within that authorized confirmation. Configure the local
Git author first. Configured Commit hooks run: trust your repository and hooks.
Hook failure is Commit failure, never permission to Push. Local Commit does not Push.

## 16. Push

Review the separate Push Plan, exact Commit, `origin/main`, remote base and
warnings. Approve it, then explicitly confirm Push. Verify the receipt's remote
SHA. Reconcile remote movement instead of forcing it. Local bare-remote acceptance
is established; credentialed external Git-host Push acceptance is not established.
Force, tags, release publication, pull requests and deployment are outside this
accepted delivery permission.

## 17. Backup

Open the account menu, then **Backup & Recovery**. From **Maintenance action**
choose **Create a backup**. One action is displayed at a time. Select Create
Backup and inspect the sealed path/integrity evidence in Advanced. The bundle
contains sensitive account password verifiers, Tasks and delivery evidence;
it excludes external credentials and copied sessions. It does not back up your
project source files. Protect those using your repository/file backup practices.

## 18. Restore

In Maintenance action choose **Inspect and restore a backup**. Enter the exact
sealed `.twos-backup` directory. Select Inspect Backup, then Review Restore Plan.
Read the replacement consequences and protected prior recovery point. Approve
the Plan, type the displayed confirmation, then Confirm Restore. Log in again
using the restored account. Only 1.0.0 backups with the supported schema are
eligible. Corrupt, future-format, incompatible-application-version or incompatible-schema bundles
are rejected. Do not modify bundle members to bypass rejection. Acceptance tests
must use isolated data, never your normal installation.

## 19. Migration

The existing schema-maintenance mechanism described here is retained; it is not
a 0.17.0-to-1.0.0 upgrade path or a cross-version compatibility claim. This
release supports fresh installation only. Older supported schemas within a
compatible application installation open a Maintenance boundary. Choose **Migrate an older
installation**. Review the plan and prior recovery point, approve, then separately
confirm. Accepted sources are vol19.003/vol19.004 to vol19.005. Migration does not
run or retry automatically. Future schemas stay blocked. Repeated restarts do
not grant permission to force a migration.

## 20. Workspace reauthorization after recovery

Restore/migration preserves history while withdrawing executable authority.
Log in, choose **Reauthorize workspace after recovery**, review and authorize
the exact current workspace. Recheck Tool Setup as required before new work.
Historical Run/Apply/Commit/Push records and approvals cannot authorize replay.

## 21. Failure recovery

Read the persisted failure/blocker before acting. Refresh if needed. Unresolved
maintenance journals prevent ordinary writes. Preserve sealed backups and the
prior recovery point. Do not edit SQLite, delete journals or replay historical
external actions. Seek technical help with sanitized error codes/version, never
passwords or tokens. Canonical startup opens Maintenance for supported old schemas.

## 22. Security model

Canonical startup binds only to **127.0.0.1**. This is a local single-Owner app,
not an internet service. Do not expose it with a public bind, forwarding or proxy.
Cookies are HttpOnly and SameSite Strict. Logout revokes the presented active
session; recovery invalidates old sessions. Passwords use salted derivation;
session tokens are stored as hashes. Protect your macOS account and disk: TWOS
is not a sandbox against malicious code already running as your OS user,
compromised tools, malicious Git hooks or modified Python dependencies.

## 23. What TWOS never does automatically

Opening a page does not request provider readiness or start a Codex Run.
**Accept != Apply != Stage != Commit != Push.** Each delivery action requires
its own authority. Materially changed bindings do not inherit approval. No
automatic Force, tag, publication, migration retry or recovered action replay
is authorized. Legacy explicitly configured schedules perform local
`compact_sync` bookkeeping; they do not authorize Codex or delivery actions.

## 24. Troubleshooting

| Symptom | Action |
| --- | --- |
| Python unavailable | Install trusted Python 3.11–3.13, then relaunch. |
| Git/Xcode license error | Resolve the system tool/license yourself; TWOS cannot accept legal terms. |
| Dependency failure | Check private logs/connectivity; run `./start-twos --refresh-dependencies`. |
| Already running | Open the existing URL; stop that installation before another launch. |
| Log in fails | Check installation/username; do not replace existing data with First Run. |
| Readiness passed, Run blocked | Save Tool Setup, then review current Pack/blocker. |
| Review Commit unavailable | Confirm APPLIED and PASSED; inspect drift/author blockers. |
| Recovery rejected | Preserve sealed input/recovery point and resolve the shown error. |
| Browser disconnect | Reload persisted status before submitting another action. |

## 25. Stop and restart

Press **Control-C in the original launcher terminal** and wait for shutdown.
Run `./start-twos` from the same source folder to restart. Reuse custom path
options if provided. Accounts/Tasks persist. Never delete data to fix startup.

## 26. Where data lives

Default logical data is `~/Library/Application Support/Tianma Work OS`.
The launcher prints exact data/runtime/log locations; `installation.json`
records installation identity/port. By default the environment is under
`~/Library/Caches/Tianma Work OS/<installation-id>/venv` and the private log is
`~/Library/Logs/Tianma Work OS/<installation-id>/runtime.log`. Both live outside source.
Use printed paths instead of guessing. Codex credentials remain in Codex's own
location, outside TWOS backups.

## 27. Protect backups

Backups are integrity-checked, **not encrypted by TWOS**. Keep them private to
your OS account and use encrypted storage for transfer/retention. Never email,
publish, commit or package them. Preserve the whole sealed directory/manifest;
do not distribute database files or live runtime internals.

## 28. Known limitations

TWOS 1.0.0 is NOT RELEASED. The Owner accepted and closed 19.5 on 2026-09-22.
19.6 local release preparation is authorized; final release, source Push, tags,
upload and distribution require separate authorization. The accepted 0.17.0 RC
remains unchanged. This candidate supports fresh installation and 1.0.0
same-version backup/restore; old-version upgrades and cross-version restore
are outside scope. Distribution remains macOS source; signing,
notarization and self-contained dependency packaging are not established.
Dependencies resolve supported ranges, not a locked reproducible binary environment.
External credentialed Git-host Push acceptance, live multi-model aggregation
and email/calendar integration are not established. LDD live broker execution
is not authorized. Only the Owner can declare Owner Acceptance PASS.

## Advanced / technical operations

Replace the capitalized placeholders with actual paths:

```sh
shasum -a 256 ARTIFACT.tar.gz
python3 scripts/build_release.py --inspect ARTIFACT.tar.gz --manifest MANIFEST.json
```

Maintainers with a clean Git checkout can run
`python3 scripts/build_release.py --output /absolute/empty/release-folder`.
It scans committed HEAD blobs, stages only approved components, rejects prohibited
content, creates deterministic bytes, hashes them, and independently inspects the
archive. Build time is source commit time for reproducibility.

Launcher options include `--data-root`, `--runtime-root`, `--log-root`, `--port`,
`--no-browser`, `--detach`, `--check`, `--refresh-dependencies`. Use isolated roots
for tests. For detached runtimes, verify that the PID belongs to the printed
installation before SIGTERM, then repeat the identical launcher command. Never
kill an unrelated process using a stale PID.

Technical records: [contract](runtime/VOL19_19_4_SECURITY_RELEASE_HARDENING_CONTRACT_v0.1.md),
[security audit](runtime/VOL19_19_4_SECURITY_AUDIT_v0.1.md),
[package manifest](runtime/VOL19_19_4_RELEASE_PACKAGE_MANIFEST_v0.1.md),
[implementation gate](runtime/VOL19_19_4_SECURITY_RELEASE_HARDENING_IMPLEMENTATION_GATE_v0.1.md).
