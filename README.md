# Tianma Work OS 1.0

**TWOS 1.0.13 / 101.61 · AI Team conversations and direct file delivery**

Open **AI Team → New task** in the top toolbar. Type a goal or attach a brief. Send a message to the group or mention one or more members by name. Start with three members and add up to three more. Other chats can work in parallel. For file work, choose an existing folder in **Files** and open the finished files there. [Watch Ada and Kai work from the same brief](https://loseyourself1978-blip.github.io/tianma-work-os/#ada-kai-demo).

**TWOS 1.0.13 / 101.61: shared Codex projects/chats and direct Nyra task controls. Includes Nyra 1.0.8 / 108.**

Select Codex on either side for the same project/chat sidebar and current conversation readback. Click Nyra to return to the bound workbench; use its compact task bubble to edit a draft, steer an owned turn, queue a supplement or stop the exact task. The delayed-history dispatch race discovered during final-candidate testing is repaired. Existing private-network navigation and accepted business results remain preserved.

This version includes five standing/reclining outfits, 13 bundled Chinese Tian action recordings and 13 matching offline tiny-voca F2 American English recordings. Sound starts muted; unmute and enable Action voice for eligible transitions, with cooldown and no overlap. Close the panel with Close, Escape or Sound.

**TWOS 1.0.13 / build 101.61** · [Download and verify](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.13) · [This update](docs/release-1.0/AI_TEAM_R2.en.md)

[简体中文](README.zh-CN.md) · [Install](docs/release-1.0/INSTALL.en.md) · [User guide](docs/release-1.0/USER_GUIDE.en.md) · [Current release status](docs/CURRENT_DELIVERY.md) · [AI Team guide](docs/release-1.0/AI_TEAM_R2.en.md)

Discuss a goal and execute it in one macOS workspace. TWOS pairs official ChatGPT, DeepSeek or Claude webpages with a local Codex client, binds handoffs to the selected destination, and brings results back to the discussion.

- Confirm the task folder; use an empty directory or preserve an existing project.
- Send selected instructions and attachments. Continue with Steer or an editable Queue; inspect real tool activity, diffs, errors and permission requests.
- Open a produced webpage, view a file, save a copy, or reveal the original in Finder.
- See service-provided quota windows and separately labelled local task usage, elapsed time, plan progress and evidence-based estimates.
- Show **Nyra**, the bundled local companion, with five outfits, standing/reclining animation and a transparent stage. Nyra observes a read-only status channel. This control-enabled build adds explicit user actions through a separate authenticated TWOS channel; Nyra cannot independently execute or approve tasks.

## Download and first use

Download TWOS v1.0.13 using the link above. Verify SHA256SUMS before opening its DMG. The matching receipt binds source, signatures, notarization and artifact hashes. Historical v1.0.1 and v1.0.0 remain unchanged.

Open the matching DMG, drag TWOS into Applications and open it. Sign into the chosen official provider website, connect your already installed/logged-in local Codex, then create or resume one folder-bound task. Nyra is inside the same app; no separate pet installer or first-run artwork download is required. Ordinary installation needs no Python, Node or terminal.

Currently supports macOS only. A Windows version is in development; no downloadable build is available yet. The TWOS package is Apple Silicon; engineering testing is macOS 27.0.1 / Safari 27.0.1. Consult the final receipt for platform coverage and signing status.

## Boundaries

TWOS implements a client using the official Codex App Server protocol; it does not embed the entire official macOS Codex UI. Provider webpages retain their own sign-in, model availability, usage and terms. Returned website code is not a local file until a separately authorized file-writing task creates it. No silent API billing switch or automatic purchase occurs.

Only explicitly selected handoff content goes to its bound destination. Directory selection is not blanket permission to read every file. The read-only status channel contains minimal state, opaque IDs and bounded active conversation titles, not prompt/response bodies, code, accounts or credentials. Explicit editing and submission carry only the user-selected draft or supplement through the separately authenticated control channel. Executor completion, business verification and Owner acceptance are separate facts.

[Privacy and permissions](docs/release-1.0/PRIVACY_AND_PERMISSIONS.en.md) · [Troubleshooting](docs/release-1.0/TROUBLESHOOTING.en.md) · [Upgrade/uninstall](docs/release-1.0/UPGRADE_AND_UNINSTALL.en.md) · [Release notes](docs/release-1.0/RELEASE_NOTES.en.md) · [Licensing](LICENSE) · [Resources and voice](ASSET_AND_VOICE_PROVENANCE.md)

The independent companion is maintained in [Nyra](https://github.com/loseyourself1978-blip/Nyra). Final-candidate screenshots and recording availability are tracked with the release media receipt; historical images are not used as evidence for new features.

<details><summary>Advanced and historical documentation</summary>

[Detailed Owner Guide](docs/OWNER_GUIDE_EN.md) · [Repository map](docs/REPOSITORY_MAP.md) · [Original local projects](docs/LEGACY_OWNER_GUIDE.md) · [Advanced source installation](docs/ADVANCED_INSTALLATION.md). Historical designs and stage records do not describe the current installer or establish current acceptance.

</details>

[Long-conversation Codex connection repair](docs/release-1.0/CODEX_HISTORY_REPAIR.en.md)

[English action voice: tiny-voca F2](docs/release-1.0/ENGLISH_VOICE.en.md)
