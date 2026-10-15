# R2 delivery contract traceability

Status: IMPLEMENTATION UNDER ENGINEERING VALIDATION. No Owner acceptance or GA grant.
R2 is the only active implementation contract. The HTML prototype is a visual reference,
never a source of real project data, approval, model results, backup or install receipts.

| Requirement | Implementation | Verification / outstanding evidence |
| --- | --- | --- |
| English default, explicit Chinese, content unchanged | Shared fixed locale preference, paired catalogs, native environment chooser and project UI | Locale/API immutability and resource fingerprints covered; packaged native and full EN/ZH journeys pending |
| Independent fresh environment | Native generated environment ID, separate data/runtime/log/projects, original environment retained | Path-isolation tests; normal packaged GUI create/relaunch pending |
| Three distinct projects | Owned ProjectSpace/source/work/activity storage; optional LDD/Dashu/Development starting points | API tests create all three with different IDs; real journeys pending |
| Ordinary work ends with usable documents | Canonical task body, source hash selection, deterministic plan, approval, explicit model start, durable output/export | Substitute execution and error/cancel/idempotency tests; real model/document evidence pending |
| Safe actual LDD import | Bounded ZIP/text preview, CRC, root transfer manifest, selected source confirmation and receipts | Exact candidate SHA and 301 payloads checked locally; GUI exact import and useful report pending |
| Dashu nonclinical planning | Separate project and human-gate metadata; pending human review in output receipts | No patient input or clinical authority; real nonclinical result pending |
| Truthful AI roles | Explicit executable identity and model IDs; configured versus actual evidence; single-model disclosure; capped existing-plan requests | Passive discovery, missing-tool and substitute tests; real calls pending |
| Same-page self-iteration | Target preview/confirm, actual source clone, planner/executor/readonly-review phases and persistent thread | Isolated substitute boundary test passes; real product-controlled source change pending |
| Current/target/candidate separation | Protect controller/data roots; no source remote; exact two-file/one-key first scope; independent checks | Scope checks and code review; packaged sandbox and real child build pending |
| Separate candidate, installed and accepted states | Reviewed author-bound local commit, explicit child build, consistent backup, OWNER_GUI_DMG handoff and identity check | Actual child install/return/rollback pending; Owner acceptance always separate |
| Preserve legacy work and authority | Additive tables; no legacy Task/Run/Commit/Push rewrites; restore epoch binds future plans | Owner baseline privately snapshotted via SQLite backup; old App readback and final fingerprints pending |
| No automatic/external authority | No external Push/Tag/Release, broker or clinical APIs, no runtime auto-approval | Tests and final side-effect audit pending |

First controlled source iteration supports one deliberately narrow capability:
`static_cockpit/project_first/catalog.json` key `noSourcesDesc` in both locales,
plus `tests/test_vol20_r2_empty_guidance.py`. The UI displays this scope before
confirmation. It does not claim arbitrary self-modification or automatic installation.

Request fee boundary confirmed by Owner: existing ChatGPT/Codex plan only,
no purchases or extra paid quota. Engineering ledger must count every real attempt,
including failures, under the aggregate maximum of ten. Test substitutes are separate.

Full validation is required after code freeze. Intermediate test counts cannot certify
later edits. Any uncompleted real model/build/install gate remains BLOCKED in final output.
