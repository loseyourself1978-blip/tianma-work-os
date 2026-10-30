# Tianma Work OS 1.0

**TWOS 1.0.3 / build 101.51** · [Download and verify](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.3) · [R3 incremental guide](docs/release-1.0/OWNER_REGRESSION_R3.en.md). The matching Release assets and receipts identify source, SHA-256, Developer ID, Apple notarization and actual verification. Publication does not grant Owner acceptance.

This patch addresses the failed Owner retest: ordinary reply actions and exact first-message routing, native and host Stop, and separate Nyra transport/activity/rendering. Dedicated real ChatGPT/Claude engineering conversations completed three round trips; no Owner debate or accepted business task was replayed. See the scope and original-failure boundaries in the R3 guide.

[简体中文](README.zh-CN.md) · [Install](docs/release-1.0/INSTALL.en.md) · [User guide](docs/release-1.0/USER_GUIDE.en.md) · [Current release status](docs/CURRENT_DELIVERY.md)

Discuss a goal and execute it in one macOS workspace. TWOS pairs official ChatGPT, DeepSeek or Claude webpages with a local Codex client, binds handoffs to the selected destination, and brings results back to the discussion.

- Confirm the task folder; use an empty directory or preserve an existing project.
- Send selected instructions and attachments. Continue with Steer or an editable Queue; inspect real tool activity, diffs, errors and permission requests.
- Open a produced webpage, view a file, save a copy, or reveal the original in Finder.
- See service-provided quota windows and separately labelled local task usage, elapsed time, plan progress and evidence-based estimates.
- Show **Nyra**, the bundled local companion, with three outfits, standing/reclining animation and a transparent stage. Nyra observes minimal read-only state; it cannot execute or approve tasks.

## Download and first use

Download TWOS v1.0.3 using the link above. Verify SHA256SUMS before opening its DMG. The matching receipt binds source, signatures, notarization and artifact hashes. Historical v1.0.1 and v1.0.0 remain unchanged.

Open the matching DMG, drag TWOS into Applications and open it. Sign into the chosen official provider website, connect your already installed/logged-in local Codex, then create or resume one folder-bound task. Nyra is inside the same app; no separate pet installer or first-run artwork download is required. Ordinary installation needs no Python, Node or terminal.

Currently supports macOS only. A Windows version is in development; no downloadable build is available yet. The TWOS package is Apple Silicon; engineering testing is macOS 27.0.1 / Safari 27.0.1. Consult the final receipt for platform coverage and signing status.

## Boundaries

TWOS implements a client using the official Codex App Server protocol; it does not embed the entire official macOS Codex UI. Provider webpages retain their own sign-in, model availability, usage and terms. Returned website code is not a local file until a separately authorized file-writing task creates it. No silent API billing switch or automatic purchase occurs.

Only explicitly selected handoff content goes to its bound destination. Directory selection is not blanket permission to read every file. Nyra receives state/opaque IDs, not chats, code, accounts or credentials. Executor completion, business verification and Owner acceptance are separate facts.

[Privacy and permissions](docs/release-1.0/PRIVACY_AND_PERMISSIONS.en.md) · [Troubleshooting](docs/release-1.0/TROUBLESHOOTING.en.md) · [Upgrade/uninstall](docs/release-1.0/UPGRADE_AND_UNINSTALL.en.md) · [Release notes](docs/release-1.0/RELEASE_NOTES.en.md) · [Licensing](LICENSE) · [Resources and voice](ASSET_AND_VOICE_PROVENANCE.md)

The independent companion is maintained in [Nyra](https://github.com/loseyourself1978-blip/Nyra). Final-candidate screenshots and recording availability are tracked with the release media receipt; historical images are not used as evidence for new features.

<details><summary>Advanced and historical documentation</summary>

[Detailed Owner Guide](docs/OWNER_GUIDE_EN.md) · [Repository map](docs/REPOSITORY_MAP.md) · [Original local projects](docs/LEGACY_OWNER_GUIDE.md) · [Advanced source installation](docs/ADVANCED_INSTALLATION.md). Historical designs and stage records do not describe the current installer or establish current acceptance.

</details>
