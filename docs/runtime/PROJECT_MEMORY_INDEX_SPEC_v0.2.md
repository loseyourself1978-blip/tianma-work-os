# Project Memory & Index Spec v0.2

Status: Draft for Vol.3 Runtime MVP

## Purpose

Project Memory keeps Tianma Work OS coherent across long-running work. It records what happened, why it happened, what remains open, and which runtime records belong together.

## Runtime Role

In Vol.3, Project Memory is implemented as a schema and example-compatible record format, not as a database.

## Record Types

Supported record types:

- `session_summary`
- `decision`
- `requirement`
- `task`
- `file_index`
- `sync_block`
- `trigger_rule`
- `strategy_state`
- `validation_result`

## Required Record Fields

Every project memory record should include:

- `record_id`
- `project_id`
- `record_type`
- `source`
- `timestamp`
- `title`
- `summary`
- `tags`

Optional linking fields:

- `related_issue_ids`
- `related_files`
- `related_records`
- `links`

## Indexing Principles

The index should support:

- Lookup by project.
- Lookup by issue ID.
- Lookup by runtime chain step.
- Lookup by asset or strategy for LDD pilot records.
- Lookup by decision or command.

## Memory Layers

### Human-Visible Layer

Human-readable markdown summaries, issue references, and runtime docs.

### Structured Runtime Layer

JSON records validated by schema.

### Future Retrieval Layer

Future search and context restoration. This is not implemented in Vol.3.

## Deferred Behavior

Project-aware reminder routing remains backlog architecture for now. Vol.3 records routing hints but does not deliver reminders or operate background jobs.

