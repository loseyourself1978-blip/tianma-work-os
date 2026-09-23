# Vol.19 19.4 Release Package Manifest Contract v0.1

> Historical Vol.19 record. For current download identity, installation and schema, see the [Owner Guide](../OWNER_GUIDE.md). Status statements below describe this record's original gate.

Status: 19.4 historical RC contract retained; 19.6 local 1.0.0 preparation
extension authorized by `TWOS-V19.6-LOCAL-RELEASE-PREP-V1`. 1.0.0 NOT RELEASED.

Current output names are `twos-1.0.0-<12-char-SHA>.tar.gz` and the matching
`.manifest.json`, both tied to one clean, exact release-preparation commit.
Internal directory, external manifest and embedded provenance use that same
identity. Inspection also retains the historical RC naming contract below.
The current application is 1.0.0, schema vol19.005; macOS source distribution
supports fresh installation and same-version backup/restore only. Reusing
0.17.0 data, upgrading old installations and cross-version restore are outside
scope. Version rejection remains enforced. Local validation is not publication;
source Push, tags, uploads and distribution require separate Owner authority.

Run `python3 scripts/build_release.py --output /absolute/empty/release-folder`
from the final clean implementation commit. No package is assembled from the
working directory's arbitrary contents. The builder checks clean tracked/index
state, reads the exact HEAD tree and blob objects, validates all tracked names/content,
stages a selected allowlist, then writes and independently inspects a deterministic
USTAR/gzip archive. Member order, modes, owner IDs, gzip header and times are fixed.
Build time uses the exact commit timestamp; repeated builds have identical bytes.

Historical 19.4 output names: `twos-0.17.0-rc19.4-<12-char-SHA>.tar.gz` and corresponding
`.manifest.json`. Embedded `RELEASE_SOURCE.json` records the full source SHA,
application 0.17.0, schema vol19.005, artifact identity, commit-derived build time,
platform and limitations. The adjacent manifest additionally records final
SHA-256, included top-level components, every file's mode/size/SHA, and reviewed
scan exceptions with an explicit included/excluded flag. It is intentionally external: a manifest
cannot contain the hash of the archive that contains that same manifest.

The final SHA and artifact hash are reported in the private Owner Acceptance
report/manifest after the single implementation commit. This tracked document
is the stable manifest contract, avoiding a self-referential source-commit hash.

Included components: README, start-twos, requirements, scripts (bootstrap,
release inspector and exact scan dispositions), twos_runtime, static_cockpit,
docs/OWNER_GUIDE.md and the four 19.4 technical records. Historical acceptance
helpers, tests/fixtures, research/records/reports and unrelated developer files
are excluded by allowlist. All source names are checked before selection.

Prohibited: .git, worktrees, .venv, databases, backups, auth stores, .env,
credentials, caches, PID/log/temp files and acceptance/runtime roots. Links and
special archive members are rejected. Independent inspection rejects duplicate,
absolute/traversing/unexpected members and verifies manifest/content/archive hashes.
Publication is exclusive and never overwrites an existing release artifact.

Inspection: `python3 scripts/build_release.py --inspect ARTIFACT --manifest MANIFEST`.
A SHA match is integrity evidence, not publisher authentication or a signature.
A fresh artifact install must separately exercise canonical bootstrap, First Run,
workspace/Task and restart persistence without contacting providers or starting Run.

Known limits: macOS source distribution only; no signed/notarized DMG, no Windows/
Linux acceptance, dependencies are downloaded within supported ranges, external
credentialed Git-host Push acceptance not established, no live multi-model
aggregation or email/calendar integration, LDD broker execution unauthorized.
TWOS 1.0.0 NOT RELEASED. 19.1–19.5 remain OWNER ACCEPTED / CLOSED; 19.6
final release remains pending. FIXED_WORKFLOW_UI / STABLE_ACTION_LOCATION
remains non-blocking POST_1.0_BACKLOG.
