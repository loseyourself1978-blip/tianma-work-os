# TWOS 1.0 · Installation and use

**Applies to application 1.0.1 / build 101.49, TWOS + Nyra 1.0 joint candidate.** [中文指南](OWNER_GUIDE.md) · [Actual delivery and validation status](CURRENT_DELIVERY.md)

**Candidate instructions: installation, engineering validation and delivery status are defined by the accompanying `START_HERE.md` and validation receipt. Do not replace the installed app before delivery.**
Discuss on the official ChatGPT website in the left pane, execute with the local Codex service in the right pane, and return results to the original discussion. The right pane is TWOS's own client for the official App Server protocol; it does not embed the entire official Codex macOS interface.

**Choose one scenario and stop at its end point.** Upgrading does not require following the first-task scenario afterward. Existing accepted work does not need to be recreated.

## Installation entry

After the final delivery receipt identifies the installer, double-click the DMG and drag **Tianma Work OS** into **Applications**. Before replacing an older copy, let active work reach a safe terminal state and quit normally. Eject the disk image and open TWOS from Applications. Use the normal macOS launch prompt; do not disable system protections. See the [complete installation guide](release-1.0/INSTALL.en.md) for first-use account and model connections.

## A · Incremental upgrade checks

**Entry condition:** You already use TWOS. This joint 1.0 candidate introduces Nyra 1.0 and corrects its reactive playback. Prior GPT→Claude, Show Nyra, daily outfit switching, business artifacts and Open/View/Save/Finder acceptances are preserved.

1. Finish active work safely, save drafts and quit TWOS normally. Install only the final signed candidate named in the delivery receipt. Replace the whole App from its DMG; never edit a running app's contents or disable macOS protection.
2. Reopen the original workbench. **Show Nyra** uses the bundled companion; no second installer, development path, Python, Node, Pets plugin or artwork download is needed. A compatible independently running Nyra is reused; visibility alone does not prove a task-status binding.
3. With no active task, observe idle. Enter the visible character once, drag left/right, then release. Use **＋ → Actions** and the transparent stage's **Actions** to verify actual playback. These are previews, not business success. After a preview the current real state returns.
4. In the stage, select Black & purple, Office or Gala and **Pose**. All three have reclining runtime art. A run/jump uses matching-outfit rise → action → lower frames. Blank stage areas pass through to underlying windows. **Desktop/Back** or Esc while the stage is focused restores the saved desktop size, position and outfit.
5. During the next task you genuinely intend to run, the read-only state can show queued, working and waiting. PARTIAL/failed/cancelled/unverified results do not celebrate. A separate optional **Confirm checked result** records only your explicit check of that exact result, preserves the original executor report and does not start work or accept the whole project. Do not create a duplicate business task just for this check.
6. Hidden Nyra stops animation and audio; a normal quit preserves preferences. Reopen or use Show Nyra to restore it. Audio defaults to mute for new users; existing preferences are respected. No automatic login item is added.

**Stop here:** check only the new reactive companion and affected result-status path. Do not repeat Claude login, travel, plan-manager, LDD or accepted save tests. Completing A does not lead into B. Full engineering, public-release and Owner-acceptance status remain distinct in the delivery receipt.

**Website boundary:** only selected content is handed off, with the current provider/target binding. A website returning code is not proof of a local file. Website handoff attachments remain “none”; Codex attachments and permissions keep their separate supported path.

## B · First task

**Entry condition:** You actually need a new execution conversation. For an existing one use C.

1. Sign into the existing ChatGPT account on the left and choose **Connect local Codex** on the right. It uses the official local tool's existing login. The integrated workbench does not require TWOS registration or an iCloud mail password. Old accounts/projects remain under **Original TWOS projects**.
2. Select **New task / conversation**, then a folder mode:

| Mode | Supported action | Boundary |
| --- | --- | --- |
| **Independent task: empty folder** | Select an existing empty folder, or create one in the system chooser | A new folder is not mandatory; no Git initialization |
| **Existing project: existing folder** | Explicitly select an existing nonempty project | Contents are preserved, never cleared or moved |

3. Use **Choose folder** or **New folder**. The native chooser supports selecting an existing folder and creating a new one. Cancel creates no conversation and starts no model. Selecting a folder does not send all its contents.
4. Review the canonical absolute path, read/write boundary, model and reasoning level. Click **Confirm folder and create task**. The selected conversation and directory appear; no business instructions have been sent. Nonempty-folder mode conflicts, access failures and changed identities are reported separately.
5. Discuss on the left and produce complete instructions. Click **Send to Codex** beneath that reply. On the first handoff or with new attachments, review instructions, target, folder, model and attachments in the inline panel, then **Send and start**. An already-confirmed target without new attachments dispatches directly. A busy target queues the new work. Do not send a manual duplicate.
6. Watch the real process in the right pane. The result returns to the original discussion when safe. If that discussion is generating, has a draft or is no longer selected, return waits rather than overwriting content.

**End point:** This task has a readable result, explicit remaining work and actual artifact actions. An execution ending is not business verification or Owner acceptance.

An empty ordinary folder can hold a webpage task without git init. **Open workspace** opens Finder; it does not switch or authorize directories. A different directory needs a new binding, while old tasks and approvals remain. If the service rejects reading an ancestor AGENTS.md, inspect whether the folder is nested under a restricted engineering path. Do not bypass the permission boundary with prompt wording.

## C · Resume an existing task

**Entry condition:** The original discussion and Codex conversation already exist.

1. Reopen normally, connect local Codex, select the original visible conversation name and check its displayed directory. Valid bindings are reused without choosing a folder again.
2. For ambiguous names, use **Conversation details → Technical identifiers** to verify thread/turn. Do not infer identity from list position or an identical folder.
3. Inspect the current task, draft and queued inputs. Use **Refresh run status** or connection verification when control is uncertain. Official Codex and TWOS may read shared history without sharing active execution control; do not start the same work from both clients.
4. Keep typing in the persistent composer. **Enter sends; Shift+Enter adds a line.** Enter during Chinese IME composition must not send. **Steer** supplements the current turn without stopping/restarting it. **Queue** waits for the preceding turn; pending inputs can be edited or deleted. Changing model/reasoning affects the next turn, never silently changes the active turn or directory.
5. Use the separate **Stop** button when necessary. Stopping is confirmed only by the corresponding terminal evidence. Reconcile unknown delivery before retrying. Review saved inputs before resuming a paused queue.

**End point:** The original task continues or reaches a clear terminal state, with no duplicate Run and no cross-conversation drafts, results or directories.

## Attachments

Use **＋ / Add files or images**, file drop, or image paste. Selection and local parsing do not send a model request. Cards identify filenames, size and parsing coverage and allow individual removal. Only the explicitly selected contents are sent on confirmation; their parent folder is not authorized by attachment selection.

| Format | Content sent through the supported input path | Limitations |
| --- | --- | --- |
| Text/code, Markdown, JSON, CSV, HTML | UTF-8 or BOM-marked UTF-16 text | No code/HTML execution; invalid encoding, empty and oversized content rejected |
| PNG / JPEG | Native image input | Structure and pixel bounds checked; selection is not proof of complete image interpretation |
| PDF | PDFKit text layer, with page coverage | No OCR, scanned images or layout; encrypted/image-only files rejected |
| DOCX | Main document paragraphs and table text | No images, comments, headers/footers or embedded objects |
| XLSX | Cell text, shared strings, cached values and formula text | No formula or macro execution; no chart/style interpretation |
| PPTX | Slide text | No images, notes, animations or layout |

Limits: 8,000,000 bytes per source file, 12,000,000 combined source bytes per message, and 200,000 extracted text bytes per file. Additional page, archive-entry, expansion and parsing-time bounds apply. No silent truncation, cloud conversion, macro execution or arbitrary archive expansion. **Attached** is distinct from **sent**; actual model or execution receipts establish content delivery. See the engineering record for the tested format scope.

Real permission and user-input requests appear inline with their reason, command and scope. Allow once, reject, stop or answer, then wait for service confirmation. Model text is not user authorization.

## Reading usage, time and activity

**Usage & Limits** keeps service account/workspace windows separate from this thread's observations. Window duration, reset time and Credits come from service data; missing is neither zero nor unlimited. Cumulative token snapshots replace old snapshots, without adding cached/reasoning subcounts twice. “Last” means the last model request, not an entire task. Request count remains unknown if the protocol does not enumerate it. There is no cost or remaining-run conversion. Multiple clients are not assumed to create multiple pools, and ordinary ChatGPT usage is not automatically merged.

Read-only refresh is throttled. Offline values retain timestamps and stale labels. A local reset countdown reaching zero does not prove replenishment; a new service snapshot is required. Capacity, rate limit, exhausted quota, authentication and network failures are distinct. TWOS does not buy credits, upgrade, consume reset coupons or silently change models/providers.

**Run Activity** follows real events. Submission is not actual start; without start evidence it says start is not confirmed. Observed execution/wait intervals use monotonic timing; unobserved sleep/offline intervals are identified, and terminal time freezes. This is neither billing time nor pure model compute time. Parallel child durations are not added to parent wall time.

**TWOS estimate** uses at least two observed completed plan-step durations in the current run, their median/longest duration and remaining step count (only when the longest observed step is at most three times the shortest) to produce a range. Insufficient samples, unknown remaining work, approval/input waits, disconnection and stale activity have explicit reasons. Overruns trigger reassessment. It is not official ETA; completed-step proportion is not elapsed-time proportion.

Expand real process rows for public summaries, plans, commands/cwd/output, file diffs and errors. Hidden reasoning is not collected. **Full execution receipt** preserves the original result; ordinary replies retain Markdown. Channel completion, business result, verification, result return and Owner acceptance remain separate.

## Artifact actions

Artifact count follows the task and actual files. **A single-file webpage task correctly produces only `index.html`.** Do not create extra files to match an example. Multi-file reports/JSON receipts belong to their own task requirements.

**Workspace files** exposes the first three existing directory entries as shortcuts, not a requirement to deliver three files. Use **All files** or **Files** for the rest.

| Action | Result |
| --- | --- |
| **Open webpage** | Trusted host validates the exact HTML and authorized folder, then opens Safari; no TWOS session or native bridge is inherited |
| **View file** | Displays supported text/code or images; HTML source does not execute inside TWOS |
| **Save as…** | Native save dialog copies one artifact's original bytes to the chosen location; source remains unchanged; cancel saves nothing |
| **Show in Finder** | Locates the original file; not an export |

Actual Save as success is already Owner-confirmed and does not need repeating. Success shows the actual destination, while errors do not claim success. Existing destination replacement uses system confirmation; the original file cannot be the export target. Artifact text/code/Markdown/JSON/CSV/HTML/PNG/JPEG support remains bounded to 8,000,000 bytes per file. New document attachment parsing does not automatically add every document format to artifact viewing/export. PDF, archive and batch export remain outside this artifact surface.

Opening is separate from functional and refresh-persistence verification. Without a real browser test, record NOT_RUN. Existing Owner business acceptance is not reopened by this UI update. A precise viewport controller is not added in this release; a physical phone test is not required by this work order.

## Maintenance and acceptance

This engineering candidate is not yet a public release; use the final signed release receipt when publication is complete. Full 20.2, public GA and later phases are not granted by travel or Save as acceptance. The limited 20.1 / 101.26 local acceptance remains closed.

See [Legacy Owner Guide](LEGACY_OWNER_GUIDE.md) and the [repository map](REPOSITORY_MAP.md) for old project backup/maintenance and source installation. Historical procedures are not prerequisites for this workbench and do not authorize replaying accepted tasks.
