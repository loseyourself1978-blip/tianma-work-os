# Memory Capacity And Retention Management v0.1

Status: Draft for Vol.3 Phase 4.2 / TWOS-045

## Purpose

Tianma Work OS needs a memory lifecycle layer so users do not have to manually delete stale project memories one by one.

This layer does not directly modify ChatGPT saved memory, delete user data, or automate cleanup. It classifies memory, preserves critical context, archives detailed historical snapshots, and generates human-readable cleanup recommendations.

## 1. Background And DUXD Sample

During real LDD usage, ChatGPT saved memory became full. The user had to manually delete old 2026-05 LDD snapshot memories one by one.

This exposed a product gap:

- Project memory can accumulate many stale snapshots.
- Old account snapshots can crowd out active project context.
- Manual deletion is tedious and error-prone.
- Durable rules must not be deleted accidentally.

A mature AI project operating system should help classify, compact, archive, supersede, and recommend memory cleanup while preserving user-visible control.

## 2. Memory Classes

Supported memory classes:

- `durable_rule`
- `current_checkpoint`
- `historical_snapshot`
- `archived_record`
- `superseded_memory`
- `active_memory`
- `project_report`
- `temporary_instruction`
- `pending_command_memory`

## 3. Retention Principles

```text
Keep durable rules.
Keep latest valid checkpoint.
Archive historical snapshots.
Mark superseded snapshots.
Summarize old details into reports.
Recommend batch cleanup.
Never silently delete critical user context.
Keep user-visible control.
```

The system should recommend cleanup, not perform invisible deletion.

## 4. LDD Example

Old 2026-05 LDD account snapshot memories should become historical snapshots once newer runtime records and reports exist.

Newer durable archive locations:

```text
records/ldd/
reports/ldd/
```

Recommended behavior:

- Keep durable LDD rules in active memory.
- Keep the latest valid LDD checkpoint in active memory.
- Archive detailed 2026-05 account snapshots into records or reports.
- Mark old snapshots as superseded when 2026-06 records exist.
- Recommend batch removal from active saved memory only after details are preserved.

## 5. Relationship To Existing Modules

Memory retention strengthens:

- TWOS-005 Project Memory & Index.
- TWOS-038 Runtime Continuity.
- TWOS-044 Command Intelligence.
- Runtime Query & Report Layer.
- LDD Sync Block Versioning / Delta Sync Protocol.

Command Intelligence needs clean memory to avoid stale command drafts. Runtime continuity needs checkpoints that survive context compression. Query reports provide compact active summaries while detailed records remain archived.

## 6. Future Implementation Idea

```text
records/reports become durable archive.
active memory stores only project rules and latest checkpoint.
cleanup report recommends what can be safely removed from active memory.
```

Possible lifecycle:

```text
Raw snapshot memory
-> classified memory item
-> active checkpoint or historical snapshot
-> archived record/report
-> cleanup recommendation
-> user-approved memory removal
```

## Safety Rules

- Do not silently delete critical user context.
- Do not delete durable project rules.
- Do not remove the latest active checkpoint.
- Do not remove pending command memory that has not been executed, cancelled, or superseded.
- Always show rationale and source records before cleanup.

## Non-Goals

Phase 4.2 does not implement:

- Direct ChatGPT memory modification.
- Automated deletion.
- UI.
- External API integration.
- GitHub Projects.
- Trading or account automation.
