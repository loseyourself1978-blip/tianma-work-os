# Vol.19 19.4 Security Audit v0.1

Status: IMPLEMENTED / OWNER ACCEPTANCE PENDING. Automated evidence is recorded
in the [implementation gate](VOL19_19_4_SECURITY_RELEASE_HARDENING_IMPLEMENTATION_GATE_v0.1.md).
Two independent read-only auditors inspected auth/web and filesystem/process
boundaries. The primary reconciled every finding and owns all corrections/tests.
No password, hash, token or temporary acceptance path is recorded here.

## Findings and dispositions

| ID | Severity | Boundary / concrete evidence | Correction | Regression / final disposition |
| --- | --- | --- | --- | --- |
| SEC-01 | MEDIUM | Bootstrap PID opened O_TRUNC before file validation; PID/log/lock accepted hardlinks | Reject multiply linked controls before write/chmod; private atomic PID publication | hardlink target bytes/modes preserved; corrected, validation in gate |
| SEC-02 | MEDIUM | self_hosting Git inherited GIT_DIR/WORK_TREE/INDEX/config and unrelated secrets | Minimal local Git environment for metadata, Commit and raw diff paths; no external diff/textconv/fsmonitor | two-repository redirect and environment tests; corrected |
| SEC-03 | MEDIUM | Apply create/replace prepared temporary material outside parent-fd finally | Include preparation in fd-owned try/finally | injected ENOSPC in both helpers; target unchanged/fd closed; corrected |
| SEC-04 | MEDIUM | Legacy runs/schedules list and schedule JSON/object IDs bypassed Task owner scope | Scope collections and create/update/run_now through Task ownership; preserve ownerless legacy policy | foreign-object denial/no mutation; corrected |
| SEC-05 | MEDIUM | Auth selected Bearer first; logout selected cookie first | Logout selects the same active Bearer-first credential | mixed credential replay denial; corrected |
| SEC-06 | MEDIUM | Maintenance accepted existing sessions despite corrupt Owner password record | Canonical Owner-record validation; return only public account fields | invalid hash/username denial in normal/standalone maintenance; corrected |
| SEC-07 | MEDIUM | Codex discovery/catalogue inherited all environment | Existing projected Codex child environment on those paths | sentinel secret/injection absence; corrected |
| SEC-08 | MEDIUM | Catalogue cleanup only stopped parent and did not close stdout | Own session/process group and close/reap catalogue pipes/processes | descendant cleanup test; corrected |
| SEC-09 | MEDIUM | Empty newly spawned Codex identity called identity-bound termination with empty identity and ignored failure | Reap unpublished exact Popen child; close pipes; report cleanup failure truthfully | injected missing child identity/no survivor; corrected |
| SEC-10 | LOW | No separate Host/Origin allowlist or CSRF token | Retain supported localhost-only boundary; host-only HttpOnly SameSite Strict cookies, JSON bodies, setup authorization, no CORS authority | No demonstrated hostile-site auth bypass; documented defense-in-depth follow-up, nonblocking |
| SEC-11 | INFORMATIONAL | Trusted local PATH/tools, configured Commit hooks and same-user filesystem trust | Owner guide explains trust boundary; do not suppress accepted explicit Commit hooks | Existing hook failure/no-Push test retained; documented |
| SEC-12 | INFORMATIONAL | Tracked tests and historical acceptance helper contain public synthetic credential-shaped literals; UI contains password validation text | Exact path/match-hash false-positive dispositions; fixtures excluded, UI text retained; unknown matches fail build | secret insertion and final artifact inspection tests; documented |
| SEC-13 | INFORMATIONAL | Requirements resolve version ranges; no signed archive or encrypted backup | Document dependency/publisher/backup boundaries | Source-byte reproducibility only; nonblocking within approved source distribution |
| SEC-14 | HIGH | New inspector trusted the manifest prefix before checking full member paths | Validate a single safe artifact basename, full archive paths and source SHA before use | malformed prefix/traversal regressions; corrected |
| SEC-15 | MEDIUM | Initial release scanner missed quoted JSON credential keys | Match JSON/assignment password, token, API and client-secret forms; exact reviewed exceptions only | JSON credential rejection without value leakage; corrected |
| SEC-16 | MEDIUM | Git replacement refs or export-ignore/subst attributes could undermine exact committed content inspection | Disable replacement objects/fsmonitor; enumerate exact tree and batch-read every committed blob instead of Git archive | replacement-ref/fsmonitor and hidden tracked secret regressions; corrected |
| SEC-17 | MEDIUM | Initial inspector compared only SHA/name between metadata copies | Require embedded source metadata and compare every field against external manifest | version/schema/time/platform/limitations tamper rejection; corrected |
| SEC-18 | MEDIUM | Release Git helper removed Git overrides but inherited unrelated secret/injection environment | Minimal OS/tool environment plus fixed Git isolation controls | inherited secret/Python/Node/dynamic-loader/Git sentinel absence; corrected |
| SEC-19 | MEDIUM | Edited Commit message reactivated Review while old proposal approval remained clickable | Disable and guard approval/Commit until current message is reviewed; block while review is pending | actual availability branch and action-handler regressions; corrected |

No confirmed RELEASE_BLOCKER or HIGH remains after these corrections. This is a bounded source/behavior
audit, not a claim of vulnerability-free software or third-party penetration testing.

The five release-tool findings were identified during review of the
new implementation, before a final Owner artifact was produced. They remain
visible here rather than being omitted as development-time issues.

## Architecture evidence and executable coverage

A. security.py uses PBKDF2-HMAC-SHA256 with 240000 rounds, random 24-byte salt,
constant-time comparison and random session tokens stored only as hashes.
first_run.py serializes one-time Owner creation and binds local setup authorization;
idempotent replay does not mint a new session. Main APIs require authenticated
Owner context and exact object ownership where supported. owner_auth, first_run,
guided_delivery and new security regressions exercise these boundaries. Recovery
removes sessions; normal and maintenance authentication share record validation.

B. canonical bootstrap reserves and inherits a 127.0.0.1 socket; fresh settings
reject other bind hosts. Real HTTP bootstrap/artifact tests verify localhost,
health, private installation/data and no provider execution.

C. first_run validates exact workspace authorization and rejects traversal,
symlink/dangling components and source/data/home overlaps. Apply uses normalized
paths, no-follow directory descriptors, bounded material, target rechecks and
atomic replacement. Maintenance rejects special/hardlinked files, exact bundle
members and future/corrupt formats. Backup bundles are directories; source-release
archives independently reject traversal and link members. Private data directories
are 0700, sensitive control/data files 0600. Same-user malicious code is outside
this local OS-account boundary; no world-writable shared installation is supported.

D. All process calls use explicit argv. Bootstrap runs Python/version/venv/pip,
then fixed uvicorn against a reserved socket. Owner fields never become shell
strings. Codex executable identity is checked/bound in Guided Setup/Run; argv/cwd
and minimized env are ticket-bound. Git metadata/worktree helpers scrub inherited
redirection and credentials. Stage/Commit and Push retain independent environment,
exact paths, immutable bindings and process identity/cleanup guards. Local
verification argv is operator configuration, never arbitrary Owner UI input.
Maintenance invokes no subprocess. ps process-identity probes use fixed argv.
Dependency installation intentionally accesses package infrastructure; provider
requests require separate explicit readiness/Run authority. Secrets are not argv.

E. Accepted Run/Result/Apply/Commit/Push tests prove separate explicit authorities,
changed immutable binding rejection, exact applied/verified files and no Force/tag.
Review status is passive; it creates no proposal/approval/execution. New review
versions cannot reuse approval of a materially different proposal. Explicit
Commit hooks remain supported and may execute repository-owned programs.

F. provider_gateway is metadata-only; page load does not probe readiness. Guided
Check and Save are distinct. No credential store is copied; the readiness probe
uses the existing auth reference. Credentials are not persisted in plaintext or
returned through normal UI. Exact model selection/fallback disclosure and Tool
Setup changes are covered by accepted tests.

G. 19.3 tests preserve external credential exclusion, corrupt/hash/future rejection,
private staging and atomic activation, protected recovery points, fresh authority
epoch, workspace reauthorization, no historical replay and no migration retry.
Exclusive database admission and durable terminal journals remain fail-closed.

H. Active command-center and Maintenance scripts render Owner text, paths,
objectives, diagnostics and logs through textContent; commit messages use input
value. No innerHTML/outerHTML/insertAdjacentHTML/document.write/eval sinks are
used. Focused tests pass hostile-looking text and inspect rendering without
executing it. UI framework is preserved.

I. Release scanning examines committed paths/blobs before selecting the runtime
allowlist. Exact reviewed fixture hashes avoid blindly deleting tests. Unknown
secret-shaped matches, SQLite magic, credential/private state paths, links and
cache/output paths fail the build. Tests and historical acceptance helpers never
ship. Final independent archive inspection checks all content hashes and sensitive
exclusions; Owner-specific paths/credentials remain outside tracked docs/artifacts.
