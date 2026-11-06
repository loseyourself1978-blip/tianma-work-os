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

TWOS 1.0.7 / 101.55 is a clearly labelled candidate preview. The current download remains published TWOS 1.0.6 / 101.54. Nyra's five assets are byte-identical to published 1.0.5 / 105 and the 1.0.6 / 106 candidate. The capture shows signed-out ChatGPT and disconnected Codex; no model run was started to make this image.
