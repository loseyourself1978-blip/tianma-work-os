# R2 implementation and migration boundary

The new primary page is `/projects`; `/twos` remains the legacy advanced workbench.
The App launches the new primary page. Source installation is still an advanced path.

Existing `vol20.001` tables and business identities remain unchanged. Additive `r2_*`
tables hold project context, import previews, selected immutable source copies,
canonical tasks, execution inputs/results, decisions and preferences. The extension
identifier is `project-first.1`. This is not a claim that older applications understand
R2 objects. App-only rollback can expose legacy objects, while R2 objects remain on disk.
Final upgrade/rollback evidence is still required before Owner handoff.

A new environment is created only through explicit native choice. Its generated ID
selects private storage; it never copies an account, database or credential. Shared
native/web locale preference contains an enum only. No model is contacted during setup,
language switching, import preview, configuration display or history viewing.

New document outputs are project-managed records. They never modify source material or
require a Git commit. Plan approval binds exact task revision, sources, output language,
team/tool configuration and recovery authority. Each explicit request is reserved once
before process start; restart interrupts unfinished work and never auto-replays it.

The model adapter uses the existing officially authenticated local Codex CLI with user
configuration/plugins/multi-agent/shell disabled and an explicit read-only or isolated
workspace sandbox. Raw stderr, authorization data and credential files are not copied.
CLI model selection and returned evidence are recorded honestly: this adapter does not
invent a provider-attested model field absent from CLI output. Missing executable or
changed identity blocks new execution while sources and previous results remain readable.

The child-candidate builder executes fixed controller-owned build steps. Candidate
regression runs in a separate read-only/no-network process sandbox. A candidate may
replace only the approved catalog resource; all other packaged input hashes must match
its exact source baseline. Commit, build and install confirmation are separate actions.
No live App is rewritten and no public signing/publication claim is made.
