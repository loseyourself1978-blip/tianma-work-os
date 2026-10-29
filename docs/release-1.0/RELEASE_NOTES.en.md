# TWOS 1.0.2 / 101.50 — R2 candidate notes

**R2 candidate documentation — not a release/GUI PASS receipt.** Native and synthetic regression evidence is recorded separately. Actual provider round trips, attachments and final packaged interface checks remain pending until the matching receipt records them.

## R2 incremental operations

This candidate is TWOS 1.0.2 / build 101.50 with Nyra 1.0.1 / build 101. Do not replace a running app. Existing accepted work, login stores, folder permissions, drafts and completed debates remain intact; nothing resumes an old debate automatically.

### Manual transfer in either direction

1. Select the intended service **and conversation** in each pane. Use a new non-sensitive engineering chat for new checks; do not replay accepted business tasks.
2. Wait for the source reply to finish. The top **Send to [service]** sends explicitly selected reply text, or the latest complete reply if no text is selected. The saved receipt's **Send reply to the other pane** sends that exact complete recorded reply back to its original source conversation.
3. **Handoff history** reads the local receipt. **Check delivery** inspects the bound destination and shows checking/result/error without sending again. **View result** displays the recorded answer. **Send reply to the other pane** is the distinct action that actually submits it. A successful inspection is not a reverse send.
4. If reopening leaves different pages visible, select the receipt in **Handoff history** and click **Open bound conversations**. This only opens the two recorded conversations; it sends nothing. Active generation or a website text/file draft blocks navigation. Once loaded, click **Check delivery**.
5. Review visible target/draft/login/challenge errors in place. Existing drafts are preserved. Unknown delivery is reconciled; never repeatedly click to force it through. Historical receipts keep their original target even after changing panes.

### Automatic exchange — off by default

Open **Automatic exchange** at the top. Check the two bound conversations, enter each participant's role and the first instruction, choose the round-trip and time budgets, review the exact file list, then click **Start automatic exchange** once. A round trip is two directional transfers. Normal complete answers pass to the other participant automatically; no per-turn handoff/check click is required.

**Pause** prevents the next submission; the provider may finish its already submitted request. **Continue** first reconciles the pending receipt. **Stop future exchanges** permanently stops this local session's future submissions; it does not claim to cancel remote generation. An app restart restores the exchange as paused. Restore both bound conversations before continuing. A manual handoff while automatic exchange is active pauses it and asks you to review before sending.

Target changes, login/challenge, service limits, missing files, duplicate answers and uncertain delivery pause the session. The optional terminal rule accepts only an explicit standalone final concession or `STATUS: CONCEDE` / `STATUS: STALEMATE`; quoted/code examples do not end a debate. Outputs cannot change participants, permissions, files or budgets. This mode grants no file execution, shell, approval or Git rights.

### Exact attachments, not paths

The pane's **Attachments** picker selects TXT/Markdown, PNG/JPEG or a simple text-layer PDF: at most 8 files, 8,000,000 bytes each and 12,000,000 bytes total. Selection makes a private local snapshot; it does not upload. **Remove selection** clears the selection without modifying the website draft. The receipt binds name, type, bytes, SHA-256, source and destination. Web handoff transmits original bytes through the site's supported file control; Codex's separate document extraction rules remain unchanged.

Upload completion, message receipt and model content readability are separate evidence. Unsupported controls, changed bytes, existing website attachments or unconfirmed uploads block sending with a reason. A filename or `file://` string is never upload evidence. Actual per-provider coverage is recorded in the release receipt, not inferred from the picker. For a provider-generated file, use its real download/export action, save through the native save panel, then explicitly select that saved file for the opposite pane. No fabricated download bytes or automatic project sharing.

### Nyra and both panes

Click the distinct lower-right hover **Stage** arrow once to enter/leave the transparent character stage. The ruler grip and wheel resize; the stage arrow does not. The same action is available from **＋** and the menu. Essential return/action/pose/sound/hide/quit controls sit in the top visible safe area, accounting for the actual Dock and menu area. Blank regions remain click-through. Exit restores placement, scale and outfit.

Fresh left-only, right-only or simultaneous activity displays the corresponding working state. One side finishing does not idle the pet while the other is working. Direct webpage generation is observed too. Reading history or checking a receipt is not work. Between automatic exchanges, scheduling is labelled waiting/queued. Unknown connection is neutral, not fake idle/work; unverified, partial, failed and cancelled outcomes do not celebrate. A short hover/drag/manual preview returns to the current real base state.

The bundled helper connects to this exact TWOS. For a separately running compatible new Nyra, **Nyra status** offers one explicit **Connect** action; only minimal read-only status is shared after both live peer signatures are checked. An older visibility-only Nyra may need a normal upgrade for the new connection. Do not disable signature checks or copy endpoint files manually.

**Upgrade end point:** check only the new hover entry/top toolbar, symmetric transfer/automatic controls, exact attachments and both-pane activity. Do not remake travel/LDD pages or repeat previously accepted Open/View/Save/Finder checks.
