# TWOS Xcode project

Open `TWOS.xcodeproj`. The TWOS target uses the same six Swift source files as the direct-download product. The target has its own `com.tianma.workos` bundle identifier and Team BZJWQJ352K. Do not edit another application's identifier to prepare TWOS.

Two shared schemes exist:
- **TWOS Sandbox Engineering**: native debug build with App Sandbox enabled. It requires `TWOS_PREPARED_APP` to point to the matching complete TWOS development build, with its frozen runtime, pinned Nyra and source receipt. The staging phase verifies hashes. This is a developer input path and is never used by the shipped application at runtime.
- **TWOS Mac App Store**: the actual native target's Store configuration. Packaging currently stops with `STORE_NOT_READY`. No Store archive, validation, upload, or submission has passed. Selecting a team or compiling Swift does not close these gates.

The current direct-download distribution stays on its existing Developer ID pipeline. No existing app, browser profile, signing credential, or Apple project is changed by generating this project. Regenerate with `python3 scripts/generate_xcode_project.py`.

## Current unresolved Store requirements

The product currently authorizes workspace paths by path/device/inode; it does not yet persist security-scoped directory bookmarks. The local executor resolves a separately installed Codex App Server. Nyra currently uses authenticated local endpoints whose directory and lifecycle must be validated across sandbox containers. The bundled Python subprocess and every nested executable require a Store-compatible signing and sandbox strategy. These are existing core features; this project does not silently remove them or claim that entitlements alone adapt them.

Provider website automation permission is not verified. The Owner confirmed no prior permission application. The planned price is free, with no in-app purchases, for the US and Canada. The public publisher is Jing Huang. App Store Connect application identity, review access and privacy declarations still require verification.

The engineering sandbox currently requests networking and user-selected file access only. No broad filesystem exception, Apple Events permission, application group, or private entitlement is invented. Microphone/camera sandbox access must be reconciled with the optional website features before submission.

See the current work-order record for evidence. No Owner action in CoinBounce is needed.
