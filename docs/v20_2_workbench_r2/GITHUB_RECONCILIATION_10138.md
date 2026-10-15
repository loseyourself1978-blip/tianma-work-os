# Local source / GitHub reconciliation — build 101.38

The Owner requested a public source upload after the current iteration and validation finish. This is source synchronization, not a new product, a replay of accepted work, a Tag, or a public GA declaration.

## Verified baseline

- GitHub API returned `main` at `700786577ab00149afd7e8dd8cfafc50613155ac`, dated 2026-09-23. The local remote-tracking reference matches that response.
- The existing local development branch is `codex/ga-visual-installer-r1`, HEAD `0e1c2e7b80b8ce83762ad57564d7c4536a03cb1f`. It has 56 commits beyond that main; no divergence was found at this baseline.
- Those committed differences affect 169 files, before the additional uncommitted 101.36–101.38 implementation. A GitHub main-only inspection therefore misses substantial local GUI, recovery, email and workbench development.
- 101.26 remains Owner-accepted for its documented local macOS/Safari scope. 101.38 is a separate candidate with Owner Acceptance pending.

## Public snapshot boundary

The upload branch is `codex/workbench-r2-10138-public-sync`. Its public snapshot will be based on the verified GitHub main, with current source and tests plus curated documentation. It does not make the unpublished local engineering history reachable from GitHub. This preserves that history locally without publishing personal mail configuration examples or raw acceptance records contained in older local commits.

All 95 runtime/build inputs in the candidate's source provenance match the prepared public source bytes. The original dirty working directory, HEAD, staging index, accounts and project data are not replaced by this preparation. Owner-only documents and raw provider traces remain local. A private email address is not used for the new public commit identity.

The current README links the latest guide and maturity status. Historical product plans remain historical; they do not assert that multi-provider collaboration, private LDD access, public notarization or Owner Acceptance has passed.

## Upload status

The complete engineering gate has passed. The public synchronization target is the branch named above; its exact upload verification is recorded in the delivery folder and associated pull request. This snapshot does not update main or create a Tag. GitHub API access and the existing account login were verified. Ordinary Git HTTPS fetch failed with a connection timeout, so the final upload may use GitHub's authenticated Git database API with exact tree/commit verification. No credential is copied into a script or document.

If upload cannot finish, the local public snapshot, source archive and explicit terminal command file will be retained. The command must target only the prepared public branch; it must not stage the entire dirty Owner directory, force-push, reset or create a Tag.
