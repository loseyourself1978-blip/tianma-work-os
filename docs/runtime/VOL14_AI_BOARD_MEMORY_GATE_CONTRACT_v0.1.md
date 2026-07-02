# Vol.14 AI Board Memory Gate Contract v0.1

| Field | Value |
|---|---|
| Scope | Minimal docs-only record for AI Board Memory Gate and Cross-Project DUXD Control |
| Baseline | Vol.13 / Vol.14 gate logic is treated as accepted baseline |
| Decision Posture | Do not reopen prior gate decisions |
| Execution Boundary | No UI, homepage, schema, validator, fixture, backend, API, scheduler, live execution, or dashboard work |

## Memory Admission Contract

| Admission Question | Required Standard | Result |
|---|---|---|
| Is this memory operationally useful for future Codex work? | Must affect routing, safety, scope control, or execution quality | Admit only if yes |
| Is it already captured elsewhere? | Must not duplicate a current durable rule, active checkpoint, or canonical runtime record | Reject or compress |
| Is it project-specific? | Must carry a clear project tag, phase, and decision boundary | Admit with project scope |
| Is it cross-project DUXD logic? | Must describe a reusable control pattern without importing project noise | Admit as DUXD control |
| Is it historical only? | Must not crowd active memory unless it changes current behavior | Archive instead of admit |

## Anti-Duplication Table

| Duplicate Pattern | Gate Rule | Required Action |
|---|---|---|
| Repeated phase summary | Keep latest active checkpoint only | Supersede older summaries |
| Same decision in different wording | Preserve canonical decision record | Link or reference, do not restate |
| Runtime note copied from report | Prefer the report as source of truth | Keep memory as short pointer only |
| Project detail inside DUXD memory | Separate local project fact from reusable method | Strip project-only detail |
| Long protocol repetition | Keep compact contract language | Replace with table entry |

## Cross-Project Filter

| Candidate Content | Keep In Project Memory | Promote To DUXD Control | Exclude |
|---|---:|---:|---:|
| Local phase status | Yes | No | No |
| Commander verdict format | No | Yes | No |
| Product-specific fixture or schema detail | Yes | No | Yes, if outside requested scope |
| General anti-duplication rule | No | Yes | No |
| Implementation task request | Yes | No | Yes, if forbidden by scope |

## Before-Codex Checklist

| Check | Pass Condition |
|---|---|
| Scope | Task is explicitly docs-only or implementation scope is authorized |
| Memory | New memory is compact, non-duplicative, and tagged to the correct project or DUXD layer |
| Baseline | Vol.13 / Vol.14 gate logic is referenced only as accepted baseline |
| Forbidden Work | No UI, homepage, schema, validator, fixture, backend, API, scheduler, live execution, or dashboard work is started |
| Output | Changed files match the allowed file list before final response |

## Commander Verdict Standard

| Verdict | Meaning | Required Response |
|---|---|---|
| Final Pass | Scope is accepted and may proceed within stated limits | Execute only the allowed work |
| Final Pass With Hard Limits | Scope is accepted but all expansions are blocked | Keep changes minimal and verify file boundary |
| Hold | Decision is not yet executable | Ask for clarification or stop |
| Fail | Scope violates gate or duplicates settled logic | Do not implement; report the violation |
