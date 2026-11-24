# AI Team in TWOS 1.0.16 · user guide

AI Team keeps a website default for future turns and checks the observed selection again before each send. Older ChatGPT rooms can continue when an effort such as Medium was stored as a model. An explicit model mismatch shows both choices. Use the displayed website choice to update future turns, then continue the queued message. Reopening a member uses the last confirmed conversation for that group.

In a Claude Code project with a selected discussion, auto-send uses its identified editor and message area. The two checkboxes control one exchange. The project draft and replies in other discussions stay separate. If the discussion cannot be identified, open the intended conversation on its own before continuing.

### Resume the first queued message

If the chat pauses, the notice names the member and service. Choose **Refresh connection** to check that member’s window. If prompted, sign in there, then click **Back to chat · Check connection**. When the notice says **Connection ready**, select **Continue queued message**. The check itself does not send anything. If an earlier version queued consecutive identical messages, **Continue once · skip duplicate copies** retains their history and sends one. Choose **Keep and send all** only if you intended separate assignments. A message with an uncertain delivery receipt is reconciled against its original operation before any further dispatch.


Open **AI Team** in the workbench toolbar, then choose **New task** in the chat list. Describe an outcome in your own words. For a first try, ask the team to explain a paragraph or turn a short meeting note into a checklist. A text conversation can finish in the chat. For file work, choose an existing output folder in **Files**. It may already contain your own documents.

## Work in a group chat

- The initial coordinator inherits the observed selection in the left pane when you create the chat. Open **Members** to change names, providers, available models, effort and responsibilities. For a website member, open their connection, make the selection on the official site, then choose **Use current website selection**. Changes apply to future assignments. The output-language control belongs to this chat.
- Start with three people. Add up to three more through **Members**. Each person may hold several responsibilities. An independent review requires a separate reviewer and evidence of different models. The activity view distinguishes requested and reported identities.
- Send a normal message to the coordinator. Use **@** to pick one or more specific people. Attach files with **＋**, drop a file, or paste an image. The chat retains the recipients, submitted file versions and the assignment receipt. An unsupported attachment stays unresolved and the app identifies the problem.
- During execution, a compatible message can steer the exact active local Codex turn. A message for another member or a channel without live steering waits for dispatch. Open the activity beside a member's message to see progress and the reply. **Stop** applies to this chat. The other chats have independent queues.
- Choose another chat or **New task** while work continues. Your draft stays in its original chat. After a restart, open the chat and choose **Reconcile** if delivery is unclear. An existing request is checked before further dispatch.
- Ask a question after completion to discuss the result. Request a specific revision to start further work. After you explicitly stop a task, clearly ask to resume when you want more production. Earlier chat records can be continued, and earlier preview profiles can be included with **Load earlier chats**. Private historical notes remain outside provider prompts.

## Inspect the deliverable

Open **Files** to see the output directory and files. Use **Preview**, **Open**, or **Show in Finder**. A generated document appears directly under the selected directory or the project's normal subfolder. The app keeps versioned review material in its own profile. If someone changes a file, or a different chat already owns that filename, the app reports the conflict. Inspect the original and choose a suitable location for the new result.

A reviewer inspects the frozen content. A blocking finding must cite a requirement, location, evidence and correction. Useful revisions can continue beyond the second attempt. If the same concrete defect persists after a strategy change, the team posts a decision question. Owner acceptance refers to a checked version. If the provider omits per-turn model identity, the activity records the gap and formal independent approval stays pending.

## Verify your download

1. Install the DMG from the matching GitHub Release. Open AI Team and start a text chat.
2. Attach a short, non-sensitive note. Mention two members and ask a question that can only be answered from the note. Compare their answers with the source.
3. Reopen that chat and ask a follow-up. For a file task, choose an existing folder and use Show in Finder to check the result. A request to revise the file creates a new revision in the same chat.

## Recover a website draft

If the group shows “Draft · not sent”, choose **Check original conversation**. A matching draft can be sent once with **Send verified draft**. If you already sent it on the website, return to the group and check to collect its receipt. If the original composer is empty, inspect the member conversation before choosing **I have not sent it · restore draft**. Restoring fills the composer. Sending requires a separate click.

If a member has already received a message, the group waits for its reply while the website opens the conversation. A timeout during local file production keeps the finished plan. Once the original interruption is verified, **Retry production with this plan** requests a new production turn in the same chat. It uses your existing Codex allowance.

A completed local result is delivered even when the provider omits the model identity. If a previous timeout captured the completed result, **Recover files and continue to review** verifies its stored receipt and hash, then hands those same files to the reviewer. Optional root Git ignore rules are delivered as **gitignore.example**.

For a previous attempt marked **Delivery unconfirmed**, open the original member conversation and choose **Check original conversation**. The check looks for a matching sent message and reports the state of the composer. It leaves the original receipt intact.

## Resume the team's work

After signing in, choose **Back to chat · Check connection**. TWOS returns an idle member window to this group's assigned conversation. A new group starts in a fresh conversation. If the window contains a draft, attachments or an active reply, finish or save that work first. If the site only exposes its default model, choose **Use website default for future turns** to apply it to later assignments.

For an earlier send, choose **Check original conversation**. TWOS opens the recorded destination and checks the matching user turn, expanding a folded message when available. If the original planning request remains unconfirmed and a distinct instruction is already queued, **Keep original unconfirmed · check next instruction** lets you continue with that instruction. The original receipt remains in the chat.

For long ChatGPT and Claude team instructions without other attachments, TWOS uploads a UTF-8 file and includes its SHA-256 in the short accompanying message. TWOS verifies the original bytes before upload and checks the file and message in the same user turn before associating the reply. An older unsent draft can use this format when its original composer is empty and you explicitly restore it.

After 30 minutes of local production, TWOS checks recent activity on that exact submission, thread and turn. An active build can continue for up to 90 minutes total. A saved completion can be recovered through the original receipt.

## Installation and rollback

Download the installer from [GitHub v1.0.16](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.16) and check SHA256SUMS before opening it. Finish active tasks and quit TWOS before upgrading. To roll back, quit 1.0.16 and use the [v1.0.15 installer](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.15). Keep the existing chat profile and output folders.
