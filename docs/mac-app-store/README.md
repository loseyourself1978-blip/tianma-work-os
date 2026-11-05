# Mac App Store preparation

Status: NOT_SUBMISSION_READY. No Archive, validation, upload, submission, approval or Store download has occurred. These English materials describe intended capabilities and must be matched to the final sandboxed candidate before use. The existing Developer ID download is a separate distribution.

Publisher: Jing Huang (Owner confirmed). Proposed first release: United States and Canada, English (U.S.), free, no in-app purchases, manual release after Apple approval. No pricing or territory setting has been changed in App Store Connect.

Open `packaging/macos/Xcode/TWOS.xcodeproj`, not the unrelated CoinBounce project. The project shares the six current product Swift sources. `TWOS Sandbox Engineering` verifies the exact prepared runtime/helper before staging. `TWOS Mac App Store` stops with STORE_NOT_READY rather than producing a native-only shell. Xcode 27.2 (27B52), macOS SDK 27.2 and the existing team were observed locally; provisioning for this app has not been verified.

## Unclosed gates

1. Security-scoped selected-directory bookmarks must survive restart while preserving the current path/device/inode and symlink checks.
2. The existing externally installed Codex App Server, Git and bundled Python process paths need a validated sandbox-compatible strategy. No external component may be hidden or silently removed.
3. Nyra helper, authenticated endpoint and container lifecycle need a sandboxed integration test. Current Developer ID peer verification remains intact.
4. Owner reports no known permission application to the providers. Website embedding/automated transfer distribution authorization is NOT_VERIFIED. No private API or alternate paid API has been enabled.
5. App Store Connect app/role/provisioning, lawful reviewer access, required-reason APIs, final privacy labels and age/export declarations remain unverified. No legal agreement has been accepted on the Owner's behalf.

The normal signed DMG fix can proceed independently. The appropriate next Store decision is a permitted sandboxed execution/integration path and provider distribution rights, not editing another app's signing team or renaming a DMG.

## Materials

- `metadata.en-US.json`: confirmed decisions, real public URLs and explicit nulls for unverified Store identity.
- `description.en-US.txt`: prepared listing; not an approved or submitted listing.
- `PRIVACY_INVENTORY.md`: actual observed data paths, not a completed Apple privacy label.
- `REVIEW_NOTES.md`: implementation and access boundaries.
- Screenshots: final Store candidate NOT_BUILT; six 2880×1800 English screenshots and an optional 15–30 second 1920×1080 preview therefore NOT_CAPTURED. Engineering DMG screenshots must not impersonate Store evidence.
