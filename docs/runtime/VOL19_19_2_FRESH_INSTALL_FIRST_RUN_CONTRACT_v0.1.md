# Vol.19 19.2 Fresh Install + First Run Contract v0.1

| Field | Value |
| --- | --- |
| Version | `v0.1` |
| Status | `ACTIVE` |
| Phase | Vol.19 19.2A |
| Supported acceptance platform | Current macOS development and acceptance platform |

## Contract

A **Fresh Install** begins with a clean TWOS source distribution and no TWOS database, Owner account, configuration, data directory, project, task, or assumed project-local virtual environment. The supported source-distribution entry point is `./start-twos`. It selects a supported Python 3.11–3.13 interpreter, creates a private isolated virtual environment, installs the repository dependency manifest into that environment only, initializes an explicit external data root, binds only to `127.0.0.1`, waits for installation-bound health, and then opens the First Run page. It never requires root, `sudo`, a global package installation, or manual environment-variable editing.

**First Run** is the persisted Owner-guided sequence:

Fresh source → local bootstrap → isolated runtime and data root → Welcome → installation confirmation → first Owner → authorized workspace → optional tool readiness → explicit Finish Setup → first saved task → refresh/restart persistence.

No old TWOS data is imported. A nonempty unrelated data root, an incompatible or newer database, an unsafe path, an unavailable configured port, a duplicate runtime, or failed health blocks truthfully; TWOS does not fall back to another database, workspace, or published port.

## Trust boundaries

- Source, runtime environment, application data, logs, temporary process state, and the authorized Owner workspace are separate boundaries. Runtime bytecode, databases, logs, and process files are not written into the source distribution.
- The installation configuration binds one installation identity, source version, data root, database, runtime environment, log directory, loopback host, selected port, and persisted First Run state. Private files are user-only where appropriate.
- First-owner creation requires a locally generated, time-bounded, single-use setup authorization. Only its digest is stored in SQLite. Owner passwords use the canonical production password-hashing path; sessions use the existing opaque server-side session boundary. One installation admits one first Owner.
- A workspace must be an explicit, writable local directory. Traversal, symbolic-link boundaries, special files, the whole home directory, TWOS source/data/runtime/log/process roots, and a Git subdirectory whose effective repository root is broader than the authorized path are rejected. Authorization records the path and filesystem identity without modifying existing workspace files.
- Optional Codex readiness begins as `Not checked` and may be `Skipped` or `Needs setup`. Automatic page refresh is passive. CLI inspection and provider connectivity remain separate explicit Owner actions; First Run never contacts a provider or starts a Codex Run.
- Finishing setup and saving the first task do not generate a Codex Pack, start a Run, Apply, Revert, Stage, Commit, Push, send email, create calendar events, or invoke a connector.

## Interruption, restart, and failure truth

Each completed browser step is committed before the next effect becomes available. Refresh and restart resume the persisted incomplete step. An expired unused setup authorization is rotated locally while preserving the current step. Completed setup remains complete when browser cookies are cleared; normal Owner login is then required. Workspace identity and installation/database bindings are revalidated on restart. Startup has a bounded health gate and a nonzero blocked exit; no endless Starting or generic success state is permitted.

A rejected workspace or subsequent setup validation records a failed state, a sanitized reason, and the previous safe step. Refresh does not retry it. The Owner must correct the blocker and explicitly resubmit; earlier account creation remains intact. Replaying an already-consumed Owner-creation request never creates another account or session. If the original browser session was lost, normal login resumes setup.

The authoritative dependency manifest is `requirements.txt`. It currently provides bounded version ranges, not a lock file; first installation requires package-download access. The launcher records the manifest and installed-environment fingerprints, checks them on restart, and requires explicit `--refresh-dependencies` after drift. This phase does not claim reproducible locked release packaging.

## Phase exclusions

This contract does not add migration from an older installation, backup/restore (Vol.19 19.3), signed packaging, a DMG or app bundle, release archives or release channels (Vol.19 19.4), Windows/Linux acceptance, live multi-provider setup, live hosting-provider credentials, email/calendar setup, auto-update, TWOS 1.0 RC status, or version 1.0.0.

Vol.19 19.2A remains open until the Owner completes the browser acceptance flow and explicitly declares PASS.
