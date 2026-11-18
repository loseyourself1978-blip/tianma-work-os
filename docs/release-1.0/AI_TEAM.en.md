# AI Team group chats on Mac

## Start a team

Choose **AI Team** in the TWOS toolbar. Enter a task goal, select a CSV and choose an existing, writable destination folder. The supported task template produces a regional sales report. Use the synthetic example or a UTF-8 CSV with the header `region,amount` or `区域,金额`, up to 200 rows and non-negative amounts with at most two decimal places.

Select **View recommended team**. Rename the Planner, Builder and Reviewer and choose Codex, ChatGPT, Claude or DeepSeek for each role. Codex lists models returned by the connected local service. For a web member, open that member’s official chat, choose a model and refresh the team roster. A site that only exposes a mode or cannot confirm the selected model shows a pending selection. Choose at least two suppliers and different models for the Builder and Reviewer. ChatGPT and Codex both count as OpenAI.

Confirm the roster, destination, data scope and included-quota setting, then choose **Approve and open group chat**. TWOS names the conversation after the goal. The Planner defines assignments, the Builder submits a report and the Reviewer checks the frozen revision in an independent conversation. The approved limits are seven dispatches, two revisions, ten minutes per dispatch and 45 minutes overall. Additional paid budget is zero.

You can change Claude’s thinking effort in its official conversation. Changing Opus 5.5 from Extra high to Medium keeps the group running. The new setting applies to future dispatches. Previously sent work keeps its recorded selection. Select the roster message to see current member settings, or a dispatched message to see that operation’s settings. A changed or unidentifiable model requires reconciliation.

## Read the chat and inspect a task

- **Left · Team chats.** Choose **New task** above the search field to open the task form. Finish or stop the current run before starting another. Search by task name. Opening earlier chats leaves the current execution target intact. **Load earlier preview chats** imports saved engineering acceptance and R1 preview chats as read-only snapshots in the standard app. The acceptance copy takes precedence when both previews contain the same chat. Repeated imports preserve existing local records. Account data and control authority stay with the original profile.
- **Center · Group conversation.** The chat shows the goal, roster, assignments, published results, review and status changes. **Save note** records a message in this chat. **Send to upcoming members** includes a clarification within the original scope on future dispatches. Existing deliveries preserve their original instructions. After closure, new messages are local notes.
- **Right · Task details.** Select a planning, building or review message to inspect that operation’s model, timing, observed progress, result and receipt. Detail depends on what the provider publishes. **Delivery & files** pins the destination, files and selected review snapshot. On narrow screens use **Chats** and **Details** in the toolbar.
- **Back to workspace** returns to the existing pair of conversations. Team chats remain searchable across relaunches. An interrupted dispatch pauses for reconciliation. **Stop dispatches** blocks subsequent assignments first and tracks the current operation through its actual terminal receipt.

## Find the files

Each new chat publishes its four final files together in **Delivery-<task ID>**. Several tasks can share a destination that already contains files. Each role works in its own private subfolder under the task’s hidden workspace. The final path appears in **Delivery & files**. Use the chat inspector to locate a particular revision. Older chats preserve their original paths.

| Final file | Contents |
|---|---|
| dashboard.html | Offline bilingual report with regional counts and totals |
| summary.md | Bilingual summary, calculation basis and grand total |
| review.md | Independent findings bound to each reviewed digest |
| delivery.json | Version, hashes, validation, model evidence and Owner decision |

Final delivery requires the review verdict, independent data checks and attributable model receipts. Frozen reports and review findings remain accessible while identity is pending. **Check original model receipts** reads the existing operations. Accepting or requesting changes updates the same delivery manifest. Altered files fail validation and the application preserves the user’s edits.

## Product acceptance

1. Exchange the Builder and Reviewer services and edit the names. Verify the exact roster, available models and recipients before approving. An unconfirmed model must prevent dispatch.
2. Run the synthetic sample. Select two different chat messages. The inspector should track the selected operation, version and real result.
3. Save a note, return to the paired workspace and reopen AI Team. After relaunch, find the named task and inspect the note and files. Browsing an older chat should initiate zero dispatches.
4. Check East has two sales totaling 3,200.00, South one totaling 1,800.00, and all three total 5,000.00. A revised report needs a new review. The task’s final delivery folder contains the four files listed above.
5. Check stop, restart reconciliation and Owner acceptance. Missing per-operation model evidence must remain visible alongside the available report and actual review.
