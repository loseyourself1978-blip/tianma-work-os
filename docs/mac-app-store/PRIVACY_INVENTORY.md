# Privacy inventory — November 5, 2026

This records current direct-download data flows. Final Store privacy labels are NOT_COMPLETED. No “Data Not Collected” claim is made.

| Data path | Actual behavior and destination | Control / remaining Store determination |
| --- | --- | --- |
| Selected prompts/replies | Provider websites receive selected content; automatic relay shares complete replies with the bound pair | Explicit handoff/opt-in, either-side Stop; already submitted data cannot be retracted locally. Provider retention/linkage and Apple's final label categories require review. |
| Attachments | Chosen file snapshots remain in local profile and may upload to the selected provider when sent | More → Remove selection prevents future selection use; does not erase prior provider uploads or original files. |
| Provider sessions | WKWebView official pages process account/session data, network information and website storage | Sign out/delete remotely through the provider. TWOS does not extract cookies or API credentials. Local preference deletion is not complete WebKit erasure. |
| Local workbench | Settings, scoped authorizations, drafts, receipts, relay state and snapshots persist locally | Quit/back up, then deliberately remove TWOS-owned profile records; no universal retention period. Business folders are separate. |
| Codex execution | Existing official local connection receives task content and can operate within approved file/command scope | Existing service authentication and approvals remain. The Store execution path is unresolved. |
| Nyra | Only versioned minimal state, side, opaque IDs and freshness pass to authenticated local consumer | No chat, code, account or attachment body; no task/approval authority. |
| Voice | Fixed bundled Chinese recordings and installed local speech voice; private imports stay local | No task narration, microphone recording or runtime TTS upload by ordinary pet audio. Website voice is a separate provider feature. |
| Diagnostics | Local operational records can include paths; no automatic publisher upload was added | Inspect and redact before voluntary support sharing. Required-reason API and dependency manifest audit remains open. |
| Support | Public GitHub Issues receives user's account identity and submitted content | Do not post private files; request a private contact path without the private details. GitHub controls retention/deletion. |
| Public website | Static GitHub Pages, no added analytics/form/remote font/site cookies | Hosting can log requests. Hosting/provider processing cannot be equated with on-device-only data. |

Public privacy page: https://loseyourself1978-blip.github.io/tianma-work-os/privacy/ . Marketing, Privacy and Support returned HTTPS 200 with deployed byte matches on November 5, 2026. Site describes published 1.0.5; update it only when the new shipped data flow is fixed. Anonymous visual review is still distinct from HTTP verification.

Provider data policies, third-party service permission, tracking classification, linked identities and final retention/consent wording must be resolved for the actual Store app. This inventory is not a legal or Apple certification.
