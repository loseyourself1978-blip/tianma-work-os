# Tianma Work OS — ChatGPT + local Codex workbench

TWOS brings an official ChatGPT discussion and an existing local Codex conversation into **one macOS app window**. Review an instruction, hand it to the chosen Codex conversation, see real execution output, and bring the result back to the original discussion.

Start with the **[101.38 Owner Guide](https://github.com/loseyourself1978-blip/tianma-work-os/blob/codex/workbench-r2-10138-public-sync/docs/v20_2_workbench_r2/OWNER_GUIDE_10138.md)** and the **[current delivery status](https://github.com/loseyourself1978-blip/tianma-work-os/blob/codex/workbench-r2-10138-public-sync/docs/CURRENT_DELIVERY.md)**. Historical design documents describe their own phase; they are not evidence that every proposed feature is delivered.

## What is implemented

- The ChatGPT pane uses the official website, account, models and history.
- The Codex pane uses the installed official local app-server protocol, the selected existing conversation ID and its working directory. It displays real messages, public reasoning summaries, commands, file changes and approval requests.
- Explicit handoff transfers selected text or the latest visible ChatGPT reply. Return places the completed result into the originating discussion's composer, preserving its draft; the website's Send action stays under user control.
- Both contexts, drafts and result origins can resume after restart. An unconfirmed execution is not automatically submitted again.

The Codex pane is a TWOS renderer of the official protocol, not an embedded copy of the Codex App's native window. Existing conversations are view-only while the Codex App is running; quit that app before continuing the same conversation in TWOS. This avoids relying on an unverified cross-process execution status. The TWOS connection uses a workspace-scoped execution profile; plugins, MCP services, multi-agent settings and automatic network/Git write permissions are not inherited. Explicit workspace-permission expansion is not supported in this candidate.

## Delivery maturity

| Evidence | Status |
| --- | --- |
| 20.1 / build 101.26 | Owner accepted and closed for the documented local macOS/Safari scope |
| 20.2 / build 101.38 | Engineering candidate; see the current validation receipt |
| 101.38 Owner Acceptance | Pending; engineering tests do not grant it |
| Public signed/notarized GA desktop release | Not established |
| Claude, DeepSeek and other website pairings | Pane presets exist; authenticated collaboration is not verified |

101.38 uses the existing official account allowance and adds no TWOS model-call quota. It does not purchase credits, automatically share whole conversations, authorize trading or clinical work, or publish generated products. Original local TWOS projects remain accessible through **Original TWOS projects**; their earlier accounts and mail configuration are retained.

## Installation and source

The current candidate is an Apple Silicon macOS local validation build. Its ad-hoc signature is not Apple notarization or public Gatekeeper acceptance. Use the exact candidate and SHA256 listed in the delivery receipt; do not bypass macOS security prompts. The integrated path requires the official Codex App to be installed and already signed in. Browser-login persistence requires macOS 14 or newer; the tested system and exact CLI version are recorded in the receipt, rather than inferred from the minimum bundle version.

The immutable [v1.0.0 source release](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.0) remains historical. See [Advanced Source Installation](docs/ADVANCED_INSTALLATION.md) and the [legacy Owner Guide](docs/OWNER_GUIDE.md) for that workflow. Source uploads, local GUI candidates, local Owner acceptance and a public GA release are separate states.
