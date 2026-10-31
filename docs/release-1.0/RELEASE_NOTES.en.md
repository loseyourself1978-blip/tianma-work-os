# TWOS 1.0.3 / 101.51 — R3 release notes

Signed, notarized patch with 1791 passing tests, 1 explicitly retained historical skip and 38 actual Safari measurements in one matched complete gate. [Exact artifact receipt](release.json) · [Verification and limits](R3_VERIFICATION.en.md) · [Incremental guide](OWNER_REGRESSION_R3.en.md). Publication is recorded by the linked GitHub Release; engineering does not grant Owner acceptance.

Changes: ordinary complete replies retain message-level target actions; canonical composer/message detection preserves truthful unknown states; automatic exchange starts from the selected first complete reply, stops future dispatch from either native Stop or host Stop, and retains stopped state across restart. Nyra separates authenticated connection, per-pane activity/freshness and actual clip/frame progress. Old snapshots after producer changes are labelled stale.

The failed Owner retest is preserved. New isolated ChatGPT/Claude work verified three real round trips, both native stops, late replies, direct left/right/both activity and advancing Nyra frames. No old Owner debate or accepted business artifact was replayed.

An additional isolated regression exposed a 1.0.2 upgrade compatibility omission. Bootstrap and runtime now explicitly preserve schema-compatible 1.0.1/1.0.2/1.0.3 identity records. Nine focused retention checks plus the final complete gate passed; no Owner data was read or migrated.

Current distribution: macOS arm64 only. Windows is in development with no downloadable version. Existing outfits, transparent stage and audio scope are retained. New Owner differential acceptance remains pending.

---

## Historical R2 release record (unchanged)

# TWOS 1.0.2 / 101.50 — R2 candidate notes

The matching complete main gate passed 1782 tests, skipped 1 retained historical-installer case and had zero failures, including 38 actual Safari measurements. App and DMG are newly notarized bytes; see the [release receipt](release.json) for signatures and hashes. Owner differential acceptance remains PENDING; original failures and PARTIAL receipts are preserved.

**R2 verification scope.** The signed TWOS 1.0.2 / 101.50 candidate completed one explicitly started three-round-trip exchange between real ChatGPT and Claude webpages: six submissions and six matched complete replies, with no manual per-turn send or check. Reopening preserved the completed exchange without replay. TXT, PNG and simple text-layer PDF readability was observed in both directions; native/synthetic boundary checks are recorded separately. The matching complete main regression and new notarization are recorded in the release receipt; the linked GitHub Release records publication. These observations do not grant Owner acceptance.

## R2 incremental operations

This version is TWOS 1.0.2 / build 101.50 with Nyra 1.0.1 / build 101. Do not replace a running app. Existing accepted work, login stores, folder permissions, drafts and completed debates remain intact; nothing resumes an old debate automatically.

### Manual transfer in either direction

1. Select the intended service **and conversation** in each pane. Use a new non-sensitive engineering chat for new checks; do not replay accepted business tasks.
2. Wait for the source reply to finish. The top **Send to [service]** sends explicitly selected reply text, or the latest complete reply if no text is selected. The saved receipt's **Send reply to the other pane** sends that exact complete recorded reply back to its original source conversation.
3. **Handoff history** reads the local receipt. **Check delivery** inspects the bound destination and shows checking/result/error without sending again. **View result** displays the recorded answer. **Send reply to the other pane** is the distinct action that actually submits it. A successful inspection is not a reverse send.
4. If reopening leaves different pages visible, select the receipt in **Handoff history** and click **Open bound conversations**. This only opens the two recorded conversations; it sends nothing. Active generation or a website text/file draft blocks navigation. Once loaded, click **Check delivery**.
5. Review visible target/draft/login/challenge errors in place. Existing drafts are preserved. Unknown delivery is reconciled; never repeatedly click to force it through. Historical receipts keep their original target even after changing panes.

### Automatic exchange — off by default

Open **Automatic exchange** at the top. Check the two bound conversations, enter each participant's role and the first instruction, choose the round-trip and time budgets, review the exact file list, then click **Start automatic exchange** once. A round trip is two directional transfers. Normal complete answers pass to the other participant automatically; no per-turn handoff/check click is required.

**Pause** prevents the next submission; the provider may finish its already submitted request. **Continue** first reconciles the pending receipt. **Stop future exchanges** permanently stops this local session's future submissions; it does not claim to cancel remote generation. An app restart restores an unfinished exchange as paused; completed/stopped exchanges keep their terminal state and do not replay. Restore both bound conversations before continuing. A manual handoff while automatic exchange is active pauses it and asks you to review before sending.

Target changes, login/challenge, service limits, missing files, duplicate answers and uncertain delivery pause the session. The optional terminal rule accepts only an explicit standalone final concession or `STATUS: CONCEDE` / `STATUS: STALEMATE`; quoted/code examples do not end a debate. Outputs cannot change participants, permissions, files or budgets. This mode grants no file execution, shell, approval or Git rights.

### Exact attachments, not paths

The pane's **Attachments** picker selects TXT/Markdown, PNG/JPEG or a simple text-layer PDF: at most 8 files, 8,000,000 bytes each and 12,000,000 bytes total. Selection makes a private local snapshot; it does not upload. **Remove selection** clears the selection without modifying the website draft. The receipt binds name, type, bytes, SHA-256, source and destination. Web handoff transmits original bytes through the site's supported file control; Codex's separate document extraction rules remain unchanged.

Upload completion, message receipt and model content readability are separate evidence. Unsupported controls, changed bytes, existing website attachments or unconfirmed uploads block sending with a reason. A filename or `file://` string is never upload evidence. Actual per-provider coverage is recorded in the release receipt, not inferred from the picker. For a provider-generated file, use its real download/export action, save through the native save panel, then explicitly select that saved file for the opposite pane. No fabricated download bytes or automatic project sharing.

### Nyra and both panes

Click the distinct lower-right hover **Stage** arrow once to enter/leave the transparent character stage. The ruler grip and wheel resize; the stage arrow does not. The same action is available from **＋** and the menu. Essential return/action/pose/sound/hide/quit controls sit in the top visible safe area, accounting for the actual Dock and menu area. Blank regions remain click-through. Exit restores placement, scale and outfit.

Fresh left-only, right-only or simultaneous activity displays the corresponding working state. One side finishing does not idle the pet while the other is working. Direct webpage generation is observed too. Reading history or checking a receipt is not work. Between automatic exchanges, scheduling is labelled waiting/queued. Unknown connection is neutral, not fake idle/work; unverified, partial, failed and cancelled outcomes do not celebrate. A short hover/drag/manual preview returns to the current real base state.

The bundled helper connects to this exact TWOS. For a separately running compatible new Nyra, **Nyra status** offers one explicit **Connect** action; only minimal read-only status is shared after both live peer signatures are checked. An older visibility-only Nyra may need a normal upgrade for the new connection. Do not disable signature checks or copy endpoint files manually.

**Upgrade end point:** check only the new hover entry/top toolbar, symmetric transfer/automatic controls, exact attachments and both-pane activity. Do not remake travel/LDD pages or repeat previously accepted Open/View/Save/Finder checks.


R3 additionally fixes editing a selected first reply: stale seed identity is revoked while active exchange scope stays frozen. Final binaries and validation are identified in the matching release receipt.
