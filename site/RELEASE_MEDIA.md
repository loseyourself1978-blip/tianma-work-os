# Product-page media: required for every release

Owner requirement recorded November 6, 2026: every TWOS version must include its actual current interface and all five Nyra outfits on the public product page.

Before publishing or closing an iteration:

1. Capture the final candidate's real TWOS window in an isolated, non-sensitive session. Inspect the saved image. Exclude account details, private conversations, tokens, personal paths and unrelated windows. Do not fabricate UI or use an old screenshot with a new version caption.
2. Copy the five exact runtime outfit portraits from the Nyra version pinned into that TWOS candidate. Include Black & purple, Office, Gala, White blouse and Ruby gown; preserve transparency and aspect ratio. Clearly identify portraits as still artwork, not animation or GUI-test evidence. Unchanged artwork may be reused only after a hash comparison with the candidate resources.
3. Update `assets/product/media-manifest.json`: versions, builds, source commits, image hashes, dimensions, capture status and privacy review. Update visible captions together. Keep a candidate preview explicitly separate from the latest public download until a release is actually published and verified.
4. Run `python3 site/verify_media.py --interface-version VERSION --interface-build BUILD`. Run before deployment; a missing outfit, broken reference, hash mismatch or mismatched screenshot version blocks website closeout.
5. Inspect the page in a real browser at desktop and narrow widths. Check full-size image links, captions, light/dark readability, mobile overflow and all five looks. Record actual GUI coverage separately from static checks.
6. Reconcile the existing Pages branch and custom-domain settings. Deploy only approved site files using a fast-forward update; preserve unrelated support/privacy content. Do not deploy private engineering evidence. Verify anonymous HTTPS 200 and byte hashes for the page, CSS and images after deployment.
7. Record deployed commit, public URL and verification time. Retain provenance; remove superseded local capture scratch and compiler/test caches after confirming no active references. Keep the current public imagery and any explicitly labelled candidate preview.

This is a release SOP, not a background automation. Website publication does not authorize a binary release, replace acceptance evidence, or grant Owner Acceptance.

## Current capture

Current download: TWOS 1.0.11 / 101.59, including Nyra 1.0.8 / 108. All six starting-state screenshots were newly captured from the final signed package on November 17, 2026, source 4f29264ea9d156a671ef4d512f22430d3f875c19. Each saved window was visually inspected. The isolated profiles were signed out, Codex disconnected, and no model task or login was performed for marketing. English app and process locale were used; actual provider welcome/consent UI is retained. All five unchanged outfit portraits match the final pinned Nyra runtime by SHA-256. See the current media manifest and outfit-reuse-1.0.11.json; prior media provenance remains in Git and the history manifest.

## Supported-service combinations — required from November 7, 2026

Keep the public product page English-only. Capture actual supported combinations, including ChatGPT/DeepSeek, ChatGPT/Claude, DeepSeek/Codex and Claude/Codex; retain a current ChatGPT/Codex view and the five verified Nyra outfits. Do not manufacture conversations, quotas or successful runs for marketing. A signed-out/disconnected image must be labelled as a starting state. Inspect each saved window image before publication.

Bind every combination to the exact candidate source, version, build, dimensions and image hash in the media manifest. Explain website reply exchange separately from authorized local Codex execution. Do not imply that all arbitrary models/websites support automatic exchange. Provider pages may contain their own untranslated legal labels; do not alter captured UI to conceal them.

Current combination images show real signed-out/disconnected starting states. Original source, date and image hashes remain in the manifest. No model turn, login, task dispatch or authentication-data copy was performed for marketing.


## Release, website and local artifact consistency — mandatory closeout

Owner policy updated November 7, 2026. For each authorized release, reconcile
the published GitHub Release, product-page download button text and destination,
visible version/build, current bilingual documentation, media manifest and the
retained local installer. They must identify the same version, build, source and
exact artifact SHA-256. Never rename an old binary or point a new button at an old
or nonexistent download. Keep a pending candidate visibly separate until its
release assets have been uploaded, downloaded and hash-verified, then published.
Verify the deployed page and its links anonymously over HTTPS. Record the result
before declaring closeout complete. Owner installation/acceptance is separate;
do not replace the running Owner app automatically.

Final handoffs use the public product page and GitHub download/release links,
not local DMG paths. Keep only one latest verified local installer per product.
Before removing an older local installer, verify its exact source commit, complete
resources, dependency locks, build scripts/configuration and usable restoration
materials; retain an uncertain item and record the reason. Source-based rollback
does not promise byte-identical signatures or notarization on a rebuilt DMG.
Preserve Git history/tags, historical GitHub assets, unique receipts and acceptance
evidence. Check active process and mount references before exact-path removal.
After each iteration remove confirmed disposable staging, download verification
copies and test/compiler caches, recording exact paths and actual free bytes.
Do not treat browser profiles, credentials, business data, the standard builder,
or unidentified directories as cache. This supersedes the previous requirement
to keep one older local rollback DMG when its rebuild materials are verified.
