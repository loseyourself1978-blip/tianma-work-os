# Tianma Work OS 1.0

[简体中文](README.zh-CN.md) · [Install](docs/release-1.0/INSTALL.en.md) · [User guide](docs/release-1.0/USER_GUIDE.en.md) · [Current release status](docs/CURRENT_DELIVERY.md)

Discuss a goal and execute it in one macOS workspace. TWOS pairs official ChatGPT, DeepSeek or Claude webpages with a local Codex client, binds handoffs to the selected destination, and brings results back to the discussion.

- Confirm the task folder; use an empty directory or preserve an existing project.
- Send selected instructions and attachments. Continue with Steer or an editable Queue; inspect real tool activity, diffs, errors and permission requests.
- Open a produced webpage, view a file, save a copy, or reveal the original in Finder.
- See service-provided quota windows and separately labelled local task usage, elapsed time, plan progress and evidence-based estimates.
- Show **Nyra**, the bundled local companion, with three outfits, standing/reclining animation and a transparent stage. Nyra observes minimal read-only state; it cannot execute or approve tasks.

## Download and first use

The joint **TWOS 1.0.1 / build 101.49** candidate is being verified. Use only a release whose receipt records the exact source, signed/notarized DMG, hash and checks. [GitHub Releases](https://github.com/loseyourself1978-blip/tianma-work-os/releases) is the publication location. Historical v1.0.0 is a source distribution; it is not this desktop installer. Existing tags and releases are preserved.

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

[Actual candidate screenshots and recording / 真实候选截图与录像](docs/release-1.0/MEDIA.en.md)

![ Actual 1.0.1 / 101.49 candidate: first workspace with bundled Nyra. ](docs/release-1.0/images/twos-first-workspace.png)

Actual 1.0.1 / 101.49 candidate: first workspace with bundled Nyra.
