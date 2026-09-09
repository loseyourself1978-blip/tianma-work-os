# Tianma Work OS

## Fresh source start (macOS, Vol.19 19.2A)

From a clean source copy, run:

```sh
./start-twos
```

TWOS selects a supported Python 3.11–3.13 interpreter, creates a private isolated runtime and data root outside the source tree, installs dependencies into that runtime only, binds to `127.0.0.1`, waits for a healthy database-backed runtime, prints the one-time First Run authorization code in the initiating terminal, and opens the browser. It does not use `sudo`, install packages globally, import another TWOS database, or start Codex/providers automatically.

Keep the launcher terminal open while using TWOS; press Control-C there for a graceful shutdown. Run `./start-twos` again to reopen the same installation. If `requirements.txt` changes or the isolated environment fails its integrity check, use the explicit `./start-twos --refresh-dependencies` repair. The active phase contract is [Vol.19 19.2 Fresh Install + First Run Contract](docs/runtime/VOL19_19_2_FRESH_INSTALL_FIRST_RUN_CONTRACT_v0.1.md).

> **You own the strategy. AI handles the execution.**

Tianma Work OS is a multi-model AI team command system that helps users turn goals, problems, documents, decisions, and projects into structured execution.

It is not a chatbot, not a generic agent builder, and not a standard workflow automation tool.

The core thesis is simple:

> **AI must move from answering questions to executing goals.**

## Core Modules

- Project Cockpit
- AI Board Mode
- Project Memory and Index System
- Decision Protocol and Decision Log
- DUXD Requirement Pool
- Asset Library
- Domain-Specific Cockpits

## DUXD

DUXD stands for **Deep User Experience Development**.

```text
Real Scenario
→ Deep Usage
→ Pain Point Discovery
→ Product Abstraction
→ Requirement Generation
→ Product Iteration
→ Real Scenario Again
```

## Seed Battlefield

LLM Daredevil Desk is the first seed battlefield for Tianma Work OS. It stress-tests source-of-truth hierarchy, risk review, forecast scoring, account state tracking, net exposure mapping, and cross-project feedback.

## Documentation

Start with [INDEX.md](INDEX.md).
