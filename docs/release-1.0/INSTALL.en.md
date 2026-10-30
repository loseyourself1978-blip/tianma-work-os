# Install Tianma Work OS 1.0.2

R3 candidate: normal-reply handoff, explicit stop and separate Nyra transport/activity/rendering. Final package and release evidence pending. [R3 incremental guide / R3 差量指南](OWNER_REGRESSION_R3.en.md).


**R2 verification scope.** The signed TWOS 1.0.2 / 101.50 candidate completed one explicitly started three-round-trip exchange between real ChatGPT and Claude webpages: six submissions and six matched complete replies, with no manual per-turn send or check. Reopening preserved the completed exchange without replay. TXT, PNG and simple text-layer PDF readability was observed in both directions; native/synthetic boundary checks are recorded separately. The matching complete main regression and new notarization are recorded in the release receipt; the linked GitHub Release records publication. These observations do not grant Owner acceptance.

[R2 incremental instructions and exact boundaries](BIDIRECTIONAL_R2.en.md).


This guide applies to the joint TWOS/Nyra candidate, build 101.50. Its release receipt is the authority for publication, signatures and tested platforms. A local candidate is not a published release.

Currently supports macOS only. A Windows version is in development; no downloadable build is available yet. The current TWOS package is Apple Silicon. Engineering testing uses macOS 27.0.1 / Safari 27.0.1. A binary deployment target does not prove testing on every older system; consult the release support matrix before installing elsewhere.

1. Download the TWOS DMG from the matching GitHub Release. Do not use the work-order ZIP or an automatic source archive as an installer. Keep its manifest and SHA256SUMS.
2. Open the DMG and drag **Tianma Work OS** into **Applications**. For an upgrade, finish active work and quit the old TWOS normally before replacing the app. Your local environments are separate from the app bundle.
3. Eject the DMG, then open TWOS from Applications. Follow the normal macOS first-launch prompt. A security/signature failure is a reason to stop and consult Troubleshooting, not to disable Gatekeeper.
4. The paired workbench opens. If the launcher appears, choose **Window → ChatGPT + Codex**. Select **语言 / Language → English** for TWOS controls. This does not change the provider website's account language.
5. Sign into ChatGPT, DeepSeek or Claude directly on the chosen provider's official webpage. TWOS ships no provider accounts or credentials. A provider may require you to complete ordinary login or a human challenge.
6. For local execution choose Codex on the right and **Connect local Codex**. Install and sign into the official local Codex application beforehand; TWOS uses its supported App Server connection. Account/model availability and charges follow your provider plan.
7. Choose **New task / conversation**. Select **Independent task: empty folder** or **Existing project: preserve folder contents**. Choose/create the intended directory, review its canonical path and access scope, then confirm. Selecting a folder alone does not run a model.
8. Discuss a small non-sensitive goal on the left. Review its complete instruction and intended target. Click **Send to Codex** to deliver it to the bound conversation. Address real permission requests in the right pane. Existing conversations with valid bindings can be resumed without creating another folder.
9. Inspect the returned result and file cards. **Open webpage**, **View file**, **Save as…**, and **Show in Finder** have different purposes. Opening a file does not certify its function.
10. Click **Show Nyra** at the top. Nyra and its resources are already inside TWOS; no second installer, Pets plugin, Python, Node or artwork download is required. Audio starts muted. Read [Nyra operations](USER_GUIDE.en.md).

**End point:** your chosen model connection works, one intended task is visible, and you can find its result. Do not repeat an accepted business task for this guide.

## Optional original local project service

**Original TWOS projects** opens the retained local project/account service. It is not a prerequisite for the paired workbench. On its first setup, use the local Owner setup shown by the launcher, authorize a separate workspace, and create the local account. When email delivery is configured for that environment, use **Register**, receive the verification message in your own mailbox, complete verification, then **Log in** with that account. Existing Owners can bind their email without replacing projects. If mail is unavailable, stop the email flow and ask the environment maintainer to configure its approved sender; provider website login is separate. No developer SMTP password is included. [Existing local-project instructions](../LEGACY_OWNER_GUIDE.md) apply only to that mode.

Advanced checksum check: run `shasum -a 256 -c SHA256SUMS` in the download folder. Ordinary installation does not require a terminal.

[English / 简体中文](INSTALL.zh-CN.md)
