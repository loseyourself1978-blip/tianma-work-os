> 历史操作指南：适用于原有 TWOS 项目入口。新的单窗口工作台请使用 [Owner Guide](OWNER_GUIDE.md)。下文保留原版本流程和验收边界，不是新版首次使用步骤。

# TWOS Owner Guide

Operate the Tianma Work OS **1.0.1 desktop candidate**, schema vol20.001.
The installer requires public signing, notarization and your manual acceptance
before GA. Technical tests do not declare Owner Acceptance.

## 1. What TWOS is

TWOS turns a Task into reviewed, explicitly approved work. You create a Project,
choose a tool and model, review its proposed instructions, and inspect results.
Apply, Commit and Push remain separate decisions.

## 2. Supported platform and release identity

The desktop candidate targets **Apple Silicon Macs running macOS 26 or later**.
Intel, Windows and Linux desktop installation are not accepted in this candidate.
The primary distribution is **Tianma-Work-OS-1.0.1.dmg** containing
**Tianma Work OS.app** with its own runtime and dependencies.

Use the publisher's [official Releases](https://github.com/loseyourself1978-blip/tianma-work-os/releases).
**The 1.0.1 visual candidate is not yet publicly released.** Wait for its signed,
notarized installer and release receipt; do not use an unsigned engineering copy
or disable macOS security. The receipt identifies the version, source commit,
architecture, installer SHA-256 and notarization. macOS checks the signed,
notarized app on first open. Maintainer checksum verification remains available
in [Advanced Source Installation](ADVANCED_INSTALLATION.md).
The historical [v1.0.0 source release](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.0)
remains immutable and is an advanced engineering distribution.

## 3. Fresh installation

1. Download **Tianma-Work-OS-1.0.1.dmg** from the official release once available.
2. Double-click the downloaded installer.
3. Drag **Tianma Work OS** to **Applications** in the installer window.
4. Open **Applications → Tianma Work OS** (or use Launchpad).
5. Follow the progress window and browser First Run.

The app carries its runtime; no programming tools or package commands are part
of this installation. If Git is missing, choose **Install Apple Command Line
Tools**, complete Apple's visual installer, then **Retry**. If an Apple license
needs acceptance, choose **Open Xcode**, review it there, then **Retry**.
TWOS never accepts a system license for you. The desktop creates separate private
storage and preserves existing source installations and Owner data.

## 4. First Owner creation

Choose **Start Setup**, confirm initialization, then choose your username and a
unique password. The desktop supplies the one-time setup authorization privately.
After account creation you are signed in; on later visits use **Log in** if your
session expired. Existing Owners cannot be replaced by First Run.

## 5. Workspace authorization

Choose **Create and Authorize My First Project**. This explicitly creates a
private directory, initializes its local project history and authorizes that
exact directory. No Run or remote action starts.
For another Project, enter its name and unique Project ID, select **Create Project**,
then **Create and Authorize Managed Workspace** for that Project. Creating a
Project alone grants no execution permission. Repeating authorization is safe.
Advanced users may instead authorize an existing standalone repository.

## 6. Guided Codex Tool Setup

You may skip optional tools in First Run and create a Task first. Later open
the desktop window’s **Set up Codex** button. Install the official desktop app
if needed, then select **Sign in through browser**. In your Project, open
**Guided Tool Setup** and select the exact supported model and reasoning.
The desktop discovers the installed tool automatically. TWOS does not copy its credential store or ask you to paste provider
secrets into ordinary UI. Local discovery is different from provider readiness.

### Configure Artifact Verification

The supported first-delivery preset includes a read-only verifier shipped with
TWOS. No hidden acceptance tool or custom script is needed. On the selected Task,
open **Configure Artifact Verification**, enter one relative artifact path and
its exact expected UTF-8 text, then **Save Verification**. Include any final
newline in the expected text. Use a small, non-secret output (contract limit:
2800 UTF-8 bytes). The verifier checks exact bytes, unexpected files (including
ignored additions), unchanged Git HEAD/index/remotes and a clean source baseline.
It does not run project code or decide technical, medical or Owner acceptance.

Managed workspaces already have the required initial history baseline. Existing
repositories must have a clean committed baseline; their maintainer can use the
advanced installation guide. Create a Task instructing Codex to write
`first_delivery.txt` containing exactly `TWOS FIRST DELIVERY PASS` and a newline,
without modifying other files. Enter the same filename and text (including its
newline) in **Configure Artifact Verification**. After an applied delivery,
review the separate Commit gate before preparing another exact-artifact delivery.

Saving or changing the contract invalidates affected Pack approvals. Review the
sealed file/text contract in the new Pack; only an explicit Run starts Coding.
The existing advanced Generate Pack action uses this same binding in a fresh
installation. Merely opening Tool Setup or Verification performs no provider
request and runs no verifier.

Technical operators who need a custom verifier can consult
[Advanced Source Installation](ADVANCED_INSTALLATION.md). The desktop's supported
built-in preset does not require custom scripts or environment settings.

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
workspace supplies the initial Project; select the intended Project for additional
projects and keep the initial **General task** Workflow. Select
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
staging occurs only within that authorized confirmation. If Commit says **NEEDS
SETUP**, choose **Set Commit identity** beside the blocker or in **Owner Commit**.
Check the displayed Project, Task and authorized repository, enter your own
**Commit author name** and **Commit author email**, then choose **Save identity**.
These fields enter commit history; they are not a login password. They apply only
to this repository. Nothing is prefilled from another account or global settings.
After saving, inspect any remaining blockers. Identity changes require a new
Commit review and approval; they do not repeat Run or Apply. Configured Commit
hooks run: trust your repository and hooks.
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
using the restored account. Only 1.0.1 backups with the supported schema are
eligible. Corrupt, future-format, incompatible-application-version or incompatible-schema bundles
are rejected. Do not modify bundle members to bypass rejection. Acceptance tests
must use isolated data, never your normal installation.

## 19. Migration

The existing schema-maintenance mechanism described here is retained; it is not
a 0.17.0-to-1.0.0 upgrade path or a cross-version compatibility claim. This
release supports fresh installation only. Older supported schemas within a
compatible application installation open a Maintenance boundary. Choose **Migrate an older
installation**. Review the plan and prior recovery point, approve, then separately
confirm. Accepted schema sources are vol19.003/vol19.004/vol19.005 to vol20.001;
application-version compatibility is still enforced. Migration does not
run or retry automatically. Future schemas stay blocked. Repeated restarts do
not grant permission to force a migration.

## 20. Workspace reauthorization after recovery

Restore/migration preserves history while withdrawing executable authority.
Log in, choose **Reauthorize workspace after recovery**, review and authorize
the exact current workspace. Recheck Tool Setup as required before new work.
Historical Run/Apply/Commit/Push records and approvals cannot authorize replay.

## 21. Failure recovery

For a rejected local login, use the password for the selected environment.
If it still fails, do not create a new account or delete data. Build101.21 adds
**Recover local account…** in the native App window. Finish active work, normally
quit and reopen TWOS, select the original environment, then use that entry before
opening the environment. Complete macOS identity verification and personally
enter/confirm a new password. The exact account and installation are shown before
confirmation; a private consistent snapshot is required, the original account ID
and saved work remain, and prior login sessions are revoked. Sign in again and
read the preserved history without repeating business actions. See
[local account recovery](VOL20_LOCAL_ACCOUNT_RECOVERY.md) for bilingual steps,
failure handling and the existing one-time recovery limit.

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
| Bundled runtime unavailable | Choose Open Diagnostics. Download a fresh official installer and replace the app in Applications; keep your saved data. |
| Git unavailable | Choose Install Apple Command Line Tools, complete Apple's visual installer, then Retry. |
| Xcode license error | Choose Open Xcode and review Apple's license/first-launch setup yourself, then Retry. |
| Startup failure | Read the displayed error code, choose Open Diagnostics, then Retry. Reinstall the official app if the error repeats. |
| Already running or local connection occupied | Return to the existing TWOS window. Quit the other TWOS instance before Retry; saved data is preserved. |
| Log in fails | Check installation/username; do not replace existing data with First Run. |
| Readiness passed, Run blocked | Save Tool Setup, then review current Pack/blocker. |
| Review Commit unavailable | Confirm APPLIED and PASSED. For NEEDS SETUP choose Set Commit identity, enter your name/email and Save identity; inspect remaining blockers before Review Commit. |
| Recovery rejected | Preserve sealed input/recovery point and resolve the shown error. |
| Browser disconnect | Reload persisted status before submitting another action. |

## 25. Stop and restart

Finish active deliveries, then choose **Tianma Work OS → Quit** and confirm.
Reopen **Tianma Work OS** from Applications. Owner, Project, Task, configuration
and saved results remain. A detached execution interrupted during shutdown may
need reconciliation on return; do not interpret closing the browser as stopping
the app. Never delete data to repair startup.

## 26. Where data lives

TWOS chooses private storage automatically. **Open Diagnostics** opens its local
status folder. Owner data stays outside the application, so replacing the app
never requires deleting project data. Existing source installations remain
separate. Codex manages its own credentials; they are excluded from TWOS backups.

## 27. Protect backups

Backups are integrity-checked, **not encrypted by TWOS**. Keep them private to
your OS account and use encrypted storage for transfer/retention. Never email,
publish, commit or package them. Preserve the whole sealed directory/manifest;
do not distribute database files or live runtime internals.

## 28. Known limitations

The 1.0.1 desktop candidate requires Developer ID signing, Apple notarization,
Gatekeeper verification and Owner manual acceptance before public GA.
Only fresh installation and same-version recovery are supported; automatic
migration from source installations and cross-version restore are not supplied.
Intel macOS, external credentialed Git-host Push acceptance, live multi-model
aggregation and email/calendar integration are not established. LDD broker
execution and medical decisions are not authorized. Owner acceptance is required.

## Advanced Installation

Developers and technical operators may use [Advanced Source Installation](ADVANCED_INSTALLATION.md).
The source launcher and source archives remain supported as an advanced path.
They do not replace the mandatory visual installation gate.
