# Local Codex connection and Nyra task labels

Candidate: TWOS 1.0.7 / build 101.55; Nyra 1.0.6 / build 106. These are local candidates, not a published release or Owner acceptance.

## A · Upgrade check — stop here afterward

In TWOS, choose Codex and click **Connect local Codex** once. The connecting stage remains visible and **Cancel connection** works while startup is pending. Model and conversation lists appear after authentication and catalogs are confirmed. A connection does not send a task. Select the intended existing conversation and inspect its folder before any explicit Send. **Disconnect** and a later explicit connection preserve drafts and history; uncertain execution is reconciled, never replayed.

Nyra displays up to two current task labels below the character, for example `ChatGPT: your conversation title` and `Claude: your conversation title`. Only fresh active, queued or waiting panes appear. The title is the selected conversation's visible title, not an AI-generated summary. When unavailable, the label says Current task / Waiting for you. Labels disappear when idle or stale.

Use Nyra's **Show current tasks** menu item (also the text-bubble control in the expanded control ring) to show or hide labels. The preference survives restart. Click the character without dragging, or click its label, to return to the freshly authenticated, already-running TWOS app. Dragging still moves Nyra and does not activate TWOS. The click does not send, approve, stop or restart a task. A missing/stale host gives a reconnect explanation instead of opening an arbitrary app.

Do not repeat accepted travel pages, debates, wardrobe or audio tests. This upgrade check ends here; first use and continuing a task remain separate guide scenarios.

## Troubleshooting and boundaries

Missing Codex: install or repair the official local Codex desktop app. Authentication required: sign in normally in that app, then reconnect explicitly. A timeout, malformed output or child exit returns an actionable error; retry only after that owned child closes. Do not resend an uncertain task. Canceling the connection does not terminate another Codex app or process.

Transport launch, reads, writes, JSONL framing and JSON decoding run away from the main UI queue. Deadlines, bounded buffers and generation checks protect cancellation, reconnect and duplicate clicks. This does not promise network or model latency.

Nyra receives existing minimal activity metadata plus at most two bounded (90-character) active conversation titles over the authenticated local read-only socket. No prompt, response, attachment, path, account, credential or code is included. Titles stay in memory and are not written to playback/visibility diagnostics. Hiding labels hides their display; disconnecting the companion stops reads. Clicking the pet independently verifies the same signed running host; the status socket gains no command or execution permission.

macOS only; Windows remains in development with no download. Existing installed apps and rollback installers remain unchanged. Signature/notarization and final packaged GUI results are reported by the hotfix receipt, separately from automated fixtures and Owner acceptance.
