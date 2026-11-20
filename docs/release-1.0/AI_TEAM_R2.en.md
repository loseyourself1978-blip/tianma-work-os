# AI Team in TWOS 1.0.13 · user guide

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

## Installation and rollback

For product acceptance, download the DMG from [GitHub v1.0.13](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.13), compare it with SHA256SUMS, and open the installer. You can keep the second copy in a separate folder. To roll back, quit 1.0.13 and launch a retained 1.0.12 installation or download the [v1.0.12 installer](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.12). Keep the profile and output folders. R2 stores its rooms in `team-r2`. R1 reads `team-r1`.
