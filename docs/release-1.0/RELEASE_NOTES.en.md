# TWOS 1.0.3 / 101.51 · R3

## Patch upgrade compatibility

Validation also caught an actual upgrade defect: deriving the compatible set from the current version dropped 1.0.2 when advancing to 1.0.3. The launcher and runtime now retain an explicit schema-compatible patch history (1.0.1, 1.0.2, 1.0.3). Existing installation identity, configuration bytes and stored source-version metadata are preserved; unrelated versions remain rejected. Isolated tests cover source launch, desktop launch and retained database identity. No Owner data was opened or migrated for this check.


R3 candidate: normal-reply handoff, explicit stop and separate Nyra transport/activity/rendering. Final package and release evidence pending. [R3 incremental guide / R3 差量指南](OWNER_REGRESSION_R3.en.md).


**Candidate scope: TWOS 1.0.3 / 101.51 with Nyra 1.0.2 / 102. Final packaged validation, notarization and publication are pending. This document is not an acceptance receipt.**

The Owner reported a missing inline action on a normal reply, a new topic paired with an older response, and an inactive companion despite a connected status. That failed Owner retest remains recorded. Earlier engineering passes and accepted business artifacts remain separate; no old debate is replayed.

## A · Upgrade checks only

1. After the new candidate is available, normally quit the old app and replace it using the matching DMG. Keep the existing profile and website sign-ins. Do not clear website storage or recreate accepted tasks.
2. In the chosen two conversations, a complete ordinary reply has **Send to Claude / Send to ChatGPT**, matching the opposite pane. Headings, prose, lists, tables and code are supported. **View selected content** shows this exact reply. If completion is uncertain, the entry stays visible with a reason and **Check reply readiness**; it does not send a partial answer. A stopped latest turn never falls back to an earlier topic. Earlier complete replies retain their own identity when explicitly chosen.
3. For automatic exchange, select **Use latest complete reply from the left** or enter a new first instruction. Check both conversations, roles and the exact selected files. Choose bounded rounds/time or **Until you stop · no round or time limit**, then click **Start automatic exchange** once. No manual warm-up exchange is required. Unknown delivery, login, verification, service limits or changed targets pause rather than blindly retry.
4. A website's native Stop on either side stops subsequent automatic dispatch first. Each pane also has **Stop automatic exchange**, and the exchange window has **Stop future exchanges**. Host Stop does not claim to cancel a generation already running at the provider. In-flight delivery stays recorded; a native interrupted reply is not forwarded as a complete reply. **Check delivery** is read-only. Restart preserves stopped state; continuing requires an explicit action.
5. **Nyra status** separates the exact visible consumer's transport connection, each pane's activity/reason/freshness, and actual animation clip/frame progress. Connected with unknown activity is an observation problem, not a transport disconnect. Either active pane keeps working animation; both fresh and idle are required for idle. Short hover/drag animations return to the true base state. Unverified website replies never trigger success celebration.

**End here after the incremental checks.** Do not repeat travel, LDD, saved files or earlier Open/View/Save/Finder acceptance. The new Owner differential result is separate from implementation and public release.

## B · First use

Use the existing installation and first-task guide. Confirm the intended service and conversation, sign in normally, and select only the instructions/files to share. Website answers do not grant local filesystem, command, approval or Git permissions. Nyra is bundled with TWOS; an additional pet installation is unnecessary.

## C · Continue a saved task

Open the existing conversations and retained receipt. Inspect uncertain delivery before any new submission. Completed or stopped exchange history is not a new start request. A new latest user question cannot be answered by silently substituting an older response from the other pane.

## Diagnosis and evidence boundaries

An isolated real ChatGPT page exposed bilingual speaker headings (`你说：You`, `ChatGPT 说：ChatGPT`) without the older message IDs. The old exact-heading rule grouped multiple rendered replies as one. R3 uses the same canonical composer/message boundary for cards, selection and reconciliation. Hidden compatibility inputs and nested editors no longer create false ambiguity; genuinely independent composers remain unknown with an explanatory card. This live mechanism and synthetic ambiguity case are not a claim that every detail of the Owner's original page was captured.

Native ChatGPT stopped-thinking and Claude interrupted-reply UI are terminal evidence only within the matched turn. Quoted text in an answer is not a stop command. Receipt delivery, completed response, business verification and Owner acceptance remain distinct.

Nyra v3 adds only side state, bounded observation reason and freshness to the authenticated minimal protocol. Consumer instance, last snapshot receipt, last state change, actual clip and advancing frame counter are independently observable. Same-value snapshots refresh liveness without restarting the first animation frame. Signature and exact peer checks remain enforced. No chat, attachment bytes, paths, code, account information or credentials are sent to Nyra.

Currently macOS only. Windows is in development; no downloadable Windows version exists. Existing artwork, outfits, transparent stage, top safe-area controls and sound scope are retained. See the matching release receipt for actual tested platform, final source, signatures and hashes.


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
