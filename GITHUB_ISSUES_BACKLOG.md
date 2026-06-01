# GITHUB_ISSUES_BACKLOG.md v0.1.7

Status: Draft — v0.1.7 updated with Agent Resource / Quota-Aware Execution Scheduler, Multi-Dimensional Progress Continuity, Rule-Based Execution Review, Volatility-Aware Execution Splitter, DUXD Spiral Improvement Loop, Account Structure Quality Score, Trigger-to-Execution Rule Ledger, and Profit Surge Protection for Strategy-State Risk Monitor.
Repository: `loseyourself1978-blip/tianma-work-os`  
Latest baseline commit: `e3e15d7 Add Tianma Work OS product blueprint documents`  
Generated from: Tianma Work OS Vol.1 → Vol.2 handoff, LDD Sync Blocks, Signal Command Layer, Codex/GitHub execution recovery, Project-Preserving Model Switching UX discovery, Cross-Workstream Coordination, Strategy-State Risk Monitor discovery, and post-quota runtime continuity updates.
Primary next step: Add this backlog to GitHub, update INDEX.md, then review the next backlog items. The first 8 trunk issues have been created. Do not create GitHub Projects yet.

---

## 1. Purpose

This document converts the current Tianma Work OS product blueprint into a GitHub-ready issue backlog.

Tianma Work OS is a multi-model AI team command system.

Core slogan:

> You own the strategy. AI handles the execution.

The backlog follows the DUXD methodology:

> Real Scenario → Deep Usage → Pain Point Discovery → Product Abstraction → Requirement Generation → Product Iteration → Real Scenario Again

The current seed battlefield is **LLM Daredevil Desk**, which continuously stress-tests the product through real trading-analysis, portfolio-review, multi-role decision-making, and project-memory workflows.

This version also introduces the **Signal Command Layer**, which expands Tianma Work OS from project memory and task coordination into multi-source intelligence intake, synthesis, decision-making, and outbound command routing.

---

## 2. Issue Creation Policy

Do not create all issues at once.

Use this document as the staging backlog first. Create GitHub Issues only when:

1. The requirement is stable enough.
2. The acceptance criteria are clear.
3. The issue can be executed by a human, Codex, or a future implementation agent.
4. The issue belongs to the current MVP or directly supports MVP clarity.

GitHub Projects should remain delayed until issue priority and MVP scope are stable.

---

## 3. Suggested Labels

### Type Labels

- `type:epic`
- `type:feature`
- `type:architecture`
- `type:doc`
- `type:research`
- `type:ux`
- `type:duxd`
- `type:codex-task`
- `type:risk-control`
- `type:technical-debt`

### Priority Labels

- `priority:p0-critical`
- `priority:p1-high`
- `priority:p2-medium`
- `priority:p3-low`

### Area Labels

- `area:project-memory`
- `area:ai-board`
- `area:codex`
- `area:github-workflow`
- `area:execution-recovery`
- `area:duxd`
- `area:financial-cockpit`
- `area:domain-cockpit`
- `area:docs`
- `area:mvp`
- `area:ux`
- `area:project-continuity`
- `area:model-switching`
- `area:workstream-coordination`
- `area:strategy-health`
- `area:bot-monitoring`
- `area:runtime`
- `area:agent-resource`
- `area:execution-review`
- `area:execution`
- `area:methodology`
- `area:account-quality`
- `area:rule-ledger`
- `area:architecture`
- `area:signal-command`

### Status Labels

- `status:backlog`
- `status:ready`
- `status:in-progress`
- `status:blocked`
- `status:needs-review`
- `status:done`

---

## 4. Priority Definition

### P0 Critical

Required to make Tianma Work OS usable as a real project-command system.  
Without it, the product cannot preserve continuity, avoid confusion, or support real execution.

### P1 High

Required for MVP completeness and credible demonstration.

### P2 Medium

Important for product depth, but can follow after the first working MVP loop.

### P3 Low

Useful polish, future expansion, or optional enhancement.

---

## 5. Milestone Proposal

Do not create a GitHub Projects board yet. Use these milestones only as logical grouping.

### Milestone M0 — Repository & Documentation Foundation

Goal: Make the GitHub repository readable, navigable, and ready for Codex-assisted implementation.

### Milestone M1 — Project Memory & Continuity MVP

Goal: Solve the most painful real-world problem discovered so far: long conversations, slow context, fragmented project memory, and hard retrieval.

### Milestone M2 — AI Board Mode MVP

Goal: Turn multi-role reasoning into a repeatable product workflow.

### Milestone M3 — LLM Daredevil Desk Financial Cockpit MVP

Goal: Use LDD as the first domain-specific cockpit to stress-test Tianma Work OS.

### Milestone M4 — DUXD Feedback Loop & Codex Implementation Workflow

Goal: Make real user pain points continuously become structured product requirements and implementation tasks.

### Milestone M5 — Multi-Source Signal Command Layer MVP

Goal: Build the upstream intelligence layer that collects signals from LDD, Codex, GitHub, users, stakeholders, and external events; classifies and prioritizes them; routes them into AI Board synthesis; and sends precise commands or feedback to the right destination.

---

---

# 5A. LDD Sync Update — 2026-05-27

The latest LLM Daredevil Desk review produced three product implications that should be reflected before Codex sync.

## Product Impact

### 1. TWOS-008 priority upgrade

`Project-Aware Reminder / Record Routing System` should move from P1 to P0 because it affects the core continuity experience of Tianma Work OS.

Reason:

- Reminders, schedules, review triggers, and operational records should appear in the corresponding project’s latest active conversation by default.
- Users should not need to manually locate scattered reminder outputs across unrelated new conversations.
- Project continuity is not a secondary feature; it is part of the core operating-system experience.

### 2. New issue: TWOS-025

Add a `Premarket vs Regular Session Execution Confirmation module`.

Reason:

- LDD frequently generates premarket action plans.
- Premarket signals can change materially after the U.S. regular session opens.
- The system needs an execution-confirmation gate before turning premarket plans into real actions.

### 3. New issue: TWOS-026

Add a dedicated review-log routing issue.

Reason:

- Review logs are operational records, but they are important enough to be tracked explicitly.
- The default destination should be the corresponding project’s latest active thread.
- This supports traceability, review continuity, and long-term project memory.

## LDD Case Inputs

The 2026-05-27 16:37 LDD sync block included:

- U.S. historical positions: GLD, GDXU, GOOG, NVDA, TSLQ, GGLL, INTC, SOXL, UGL.
- SOXS confirmed fully closed.
- LDD U.S. model strategy remains separate and still in cash.
- Current U.S. strategy: avoid new LDD model positions; continue historical risk cleanup.
- Crypto strategy: no new buying; hold BTC/ETH/SOL; no DOGE add; ZEC grid bots continue with defined protection and profit-extraction zones.
- New DUXD requirements:
  - Project-aware Reminder / Record Routing System.
  - Premarket vs Regular Session Execution Confirmation module.
  - Review logs should be written into the corresponding project’s latest active thread by default.

---

# 5B. LDD Sync Update — 2026-05-28

The latest LLM Daredevil Desk review after the 2026-05-27 U.S. regular trading session produced another product implication: trade records must explain **why** a trade was made, not only what was traded.

## Product Impact

### 1. New issue: TWOS-027

Add `Trade Intent Ledger`.

Reason:

- Every trade must record ticker, quantity, price, and P/L.
- This is not enough for a serious financial cockpit.
- The cockpit must also know the intent of each trade:
  - New entry.
  - Historical cleanup.
  - Risk reduction.
  - Leverage-decay exit.
  - Hedge removal.
  - Stop-loss.
  - Take-profit.
  - Bot profit protection.
  - Cash release.
- Without trade intent, the system cannot correctly evaluate whether an action improved the account.

### 2. New issue: TWOS-028

Add `Account Structure Improvement Score`.

Reason:

- A trade can lose money but improve account structure by removing bad risk.
- A trade can make money but worsen account structure by increasing hidden leverage, concentration, or opposite exposure.
- Financial cockpit review should judge account-structure improvement, not only immediate P/L.

### 3. Linkage update

Trade records should connect with:

- `TWOS-015 — Opposite Exposure Detector / Net Exposure Map`
- `TWOS-017 — Position Intent Tagging System`
- `TWOS-019 — Source-of-truth priority system for financial data`
- `TWOS-020 — LDD review scoring and forecast calibration module`

## LDD Case Inputs

The 2026-05-28 morning LDD sync block included:

- Historical TSLQ fully closed.
- Historical SOXS already fully closed.
- GDXU reduced by 20 shares, leaving 20 shares.
- UGL reduced by 20 shares, leaving 10 shares.
- LDD U.S. model strategy remains separate and still in cash.
- These trades were not new model strategy trades; they were historical-position cleanup and risk-reduction actions.
- New DUXD requirement:
  - `Trade Intent Ledger`.
- Tianma Work OS design update:
  - Financial cockpit should judge whether a trade improved account structure, not merely whether it made immediate profit.
  - Trade records should connect to Position Intent Tags and Net Exposure Map.

---

# 5C. Multi-Source Signal Command Update — 2026-05-28

As Tianma Work OS moves from documentation into development, the project is no longer receiving information from a single source.

The system now needs to handle multiple signal streams:

- LDD review feedback.
- Codex task instructions.
- Codex execution reports.
- GitHub repository state.
- Future GitHub Issues, Pull Requests, and comments.
- Future user, customer, supplier, employee, partner, investor, advisor, market, media, regulatory, and international-event inputs.

This changes the product requirement from simple project memory to a broader command-system capability.

## Product Impact

Tianma Work OS needs a new core layer:

# Signal Command Layer

The Signal Command Layer manages:

```text
External / Internal Signals
→ Intake
→ Classification
→ Reliability / Priority Scoring
→ Routing
→ AI Board Synthesis
→ Decision
→ Command Output
→ Feedback Tracking
→ Memory / Ledger Update
```

This layer is responsible for transforming messy real-world information into structured decisions and executable instructions.

## Product Definition Update

Tianma Work OS is not only a task manager or AI assistant.

It is a multi-source intelligence and command operating system that helps humans collect complex signals, synthesize decisions through AI roles, and route precise commands back to people, tools, agents, and projects.

## MVP Scope for Signal Command Layer

The first MVP should not try to support every possible external stakeholder.

The first MVP should support three real signal sources:

1. LDD Sync Blocks.
2. Codex Task / Execution Reports.
3. GitHub Issue / Pull Request / Comment Feedback.

These three sources are enough to validate the architecture:

- LDD represents real business/operational scenario input.
- Codex represents execution-agent input and output.
- GitHub represents development collaboration and external feedback.

After these three are stable, future expansion can add customers, suppliers, employees, investors, partners, advisors, and external market events as additional source types.

## New Issues

This update adds:

- `TWOS-029 — Create Multi-Source Signal Intake System`
- `TWOS-030 — Create Signal Classification & Priority Engine`
- `TWOS-031 — Create Stakeholder / External Resource Registry`
- `TWOS-032 — Create Decision-to-Command Routing System`

---

# 5D. Codex / GitHub Execution Recovery Update — 2026-05-28

During Vol.2 execution, Codex successfully created local commits but the initial GitHub push failed twice over HTTPS due to connection timeouts.

The repository was safe:

- Working tree was clean.
- Local `main` was ahead of `origin/main` by 2 commits.
- No repository files were modified during recovery.
- No GitHub Issues or GitHub Projects board were created.

Diagnostics showed:

- `curl -I https://github.com` returned HTTP/2 200.
- `curl -I https://api.github.com` returned HTTP/2 200.
- No Git proxy was configured.
- SSH reached GitHub but failed at host-key verification, so SSH was not usable in the non-interactive Codex context.
- A verbose HTTPS retry succeeded and pushed `e3e15d7..07ead2c main -> main`.

## Product Impact

This became another DUXD discovery:

> Execution failures are not merely operational trouble. They are opportunities to strengthen Tianma Work OS.

Tianma Work OS needs a standard failure-recovery protocol for Codex, GitHub, and future execution agents.

## New Issue

This update adds:

- `TWOS-033 — Create Codex / GitHub Execution Failure Recovery Protocol`

The protocol should protect completed work, diagnose the failure type, generate safe recovery instructions, and decide whether the task is blocked or can continue.

---

# 5E. Project-Preserving Model Switching UX Update — 2026-05-28

A new DUXD discovery came from ChatGPT project usage itself.

In the Mac app project conversation, the user observed:

- The web-style model selector is not available in the input/composer area.
- The top conversation-title selector can open a model selection page.
- Selecting Thinking can create or jump to a new chat.
- The new chat may not remain inside the current Project.
- This breaks project continuity, context preservation, and record routing.

## Product Impact

This is a direct project-continuity UX issue.

Tianma Work OS depends on stable project context. A user should be able to switch model, role, or reasoning intensity inside a project without losing:

- Project membership.
- Project memory.
- Project files.
- Project instructions.
- Active session context.
- Review logs.
- Decision history.
- Handoff continuity.

## New Issue

This update adds:

- `TWOS-034 — Create Project-Preserving Model Switching`

The system should ensure that model switching or reasoning-depth switching does not scatter records into unrelated new chats.

If a new conversation is technically required, it should default to the current project and carry a structured handoff.

---

# 5F. Cross-Workstream Interruption & Coordination Update — 2026-05-28

After the first 8 GitHub trunk issues were created, the next Codex execution step was intentionally paused because a time-sensitive LDD review was about to start.

This created another DUXD discovery:

> Tianma Work OS must coordinate competing active workstreams without losing the state of either workflow.

The system should not blindly continue a lower-priority execution stream when a higher-priority signal arrives. It should also not destroy or forget the paused workflow.

## Product Impact

This update adds:

- `TWOS-035 — Create Cross-Workstream Interruption & Coordination System`

The system should support:

- Saving the current workstream checkpoint.
- Classifying the incoming signal or workstream.
- Determining whether to continue, pause, switch, or queue.
- Preserving the resume point for the paused workflow.
- Recording why the switch happened.
- Resuming later without losing context.

## Real Case

Current workstream:

- Tianma Work OS / Codex / GitHub Issues creation.
- First 8 GitHub trunk issues were successfully created.
- Repo state was clean.
- No GitHub Projects board was created.

Incoming workstream:

- LDD premarket / crypto risk review.
- ZEC bot profit-protection decision became time-sensitive.

Decision:

- Pause further Codex execution.
- Switch to LDD review.
- Keep GitHub workstream checkpoint clean and resumable.

---

# 5G. Strategy-State Risk Monitor Update — 2026-05-28

LDD produced a new financial-cockpit requirement from ZEC grid-bot management.

The user closed the 600U / 80-grid ZEC bot and selected automatic ZEC selling. One robot order sold about 0.608 ZEC at about 524.61 USDT,成交额 around 318.97 USDT.

After that, only the 500U / 60-grid ZEC bot remained active:

- Asset value: about 601.84 USDT.
- Total return: about +163.93 USDT / +32.78%.
- Grid profit: about +94.67 USDT / +18.93%.
- Floating profit: about +69.26 USDT / +13.85%.

The remaining bot was still profitable, but the return had moved closer to the hard 30% protection threshold.

## Product Impact

This update adds:

- `TWOS-036 — Create Strategy-State Risk Monitor`

The key lesson:

> A strategy can still be profitable but no longer safe.

The financial cockpit should monitor strategy health, profit drawdown, bot deterioration, and action thresholds, not only current P/L.

## Real Case

ZEC bot state:

- 600U bot: closed to lock profit.
- Automatic ZEC selling selected.
- Sold about 0.608 ZEC at about 524.61 USDT.
- Remaining 500U / 60-grid bot:
  - asset value about 601.84 USDT.
  - total return about +32.78%.
  - hard protection threshold: below 30%.
  - health state: `profitable_but_deteriorating`.
  - current instruction: observe, prepare at 31.5%, close and auto-sell below 30%.

---

# 5H. Agent Resource / Quota-Aware Execution Scheduler Update

Codex quota exhaustion showed that execution agents are finite, stateful resources. Tianma Work OS must know when an agent is unavailable, which task types are blocked, and what can still continue safely.

## Product Impact

This update adds:

- `TWOS-037 — Create Agent Resource / Quota-Aware Execution Scheduler`

## Core Principle

If an execution agent is unavailable, Tianma Work OS should preserve checkpoints, avoid stacking risky changes, continue in non-mutating design mode, queue pending tasks, and resume execution from a clean state when capacity returns.

---

# 5I. Multi-Dimensional Progress Continuity Update

A blocked dimension should not freeze the whole project. During Codex pause, LDD review, product architecture, and DUXD discovery continued.

## Product Impact

This update adds:

- `TWOS-038 — Create Multi-Dimensional Progress Continuity & Resume Orchestrator`

## Core Principle

Tianma Work OS must preserve blocked checkpoints, advance unblocked dimensions, and reconcile all progress when the blocked dimension resumes.

---

# 5J. Rule-Based Execution Review Update

LDD discovered that the user sold 5 SOXL at 206 after SOXL broke the 210 protection line. SOXL later rebounded, but the sale was rule-compliant and improved risk structure.

## Product Impact

This update adds:

- `TWOS-039 — Create Rule-Based Execution Review`

## Core Principle

Trade correctness should be judged by rule compliance and account-risk improvement, not by short-term price movement after execution.

---

# 5K. Volatility-Aware Execution Splitter Update

For high-volatility leveraged ETFs, ETNs, crypto, and bot strategies, execution should be staged rather than binary.

## Product Impact

This update adds:

- `TWOS-040 — Create Volatility-Aware Execution Splitter`

## Core Principle

The system should recommend partial exit, confirmation windows, rebound zones, and final stop lines.

---

# 5L. DUXD Spiral Improvement Loop Update

Tianma Work OS and DUXD are mutually reinforcing. Real project execution improves the product, the product structures the method, and the improved method improves future requirement discovery.

## Product Impact

This update adds:

- `TWOS-041 — Create DUXD Spiral Improvement Loop`

## Core Principle

DUXD is not only a requirement discovery method. It is a spiral product evolution mechanism driven by real project execution.

---

# 5M. Account Structure Quality Score Update

After SOXS, TSLQ, GDXU, partial SOXL, partial INTC, and partial GGLL reductions, the account moved from risk-cleanup mode toward account-structure optimization. Cash improved from negative financing pressure to positive cash.

## Product Impact

This update adds:

- `TWOS-042 — Create Account Structure Quality Score`

## Core Principle

A trading cockpit should not only evaluate P/L. It should evaluate account structure quality: cash pressure, exposure clarity, leverage risk, bot health, strategy separation, and redeployment readiness.

---

# 5N. Trigger-to-Execution Rule Ledger Update

LDD discovered that remaining positions now have many trigger conditions and next action lines:

- SOXL: 210 / 205
- GOOG / GGLL: 380 / 374
- GLD / UGL: 405
- NVDA: 208
- INTC: 118 / 114
- BTC: 75,500-76,000 staged buyback
- ZEC bot: 31.5% / 30%

## Product Impact

This update adds:

- `TWOS-043 — Create Trigger-to-Execution Rule Ledger`

## Core Principle

A financial cockpit must remember why a position should be acted on, which trigger fired, what was executed, what remains, and what the next trigger is.

---

# 5O. Profit Surge Protection Update for TWOS-036

As of 2026-06-01 09:01 Singapore/Beijing, the remaining 500U / 60-grid ZEC bot was still running:

- Asset value: about 637.74 USDT.
- Total return: about +199.39 USDT / +39.87%.
- Grid profit: about +98.43 USDT / +19.68%.
- Floating profit: about +100.96 USDT / +20.19%.

The bot is no longer just in normal running mode. It is near a high-profit lock-profit observation zone.

## Product Impact

Update existing `TWOS-036 — Create Strategy-State Risk Monitor` with a sub-module called `Profit Surge Protection`.

## Core Principle

Grid/robot strategies need upside lock-profit monitoring, not only downside stop-loss monitoring.

Suggested states:

- `normal_running`
- `healthy_profit`
- `profit_surge_observation`
- `lock_profit_zone`
- `profit_extraction_recommended`
- `partial_close_recommended`
- `full_close_recommended`
- `downside_protection_triggered`

Suggested fields:

- `current_return_pct`
- `peak_return_pct`
- `profit_surge_threshold`
- `lock_profit_zone`
- `profit_extraction_zone`
- `partial_close_zone`
- `full_close_zone`
- `downside_hard_stop`
- `recommended_action`

Real case:

- Continue running while total return stays above 35%.
- Consider profit extraction or closure if return reaches 40%-42% or ZEC approaches 600-620.
- Prepare to close near 31.5%.
- Close below 30%.

# 6. Backlog Overview

| ID | Title | Type | Priority | Milestone | Area |
|---|---|---:|---:|---|---|
| TWOS-001 | Create issue-ready backlog document | Doc | P0 | M0 | Docs |
| TWOS-002 | Improve README and INDEX navigation for new contributors | Doc | P1 | M0 | Docs |
| TWOS-003 | Define repository directory structure for product, examples, templates, and implementation | Architecture | P1 | M0 | GitHub Workflow |
| TWOS-004 | Create Codex implementation instruction template | Codex Task | P1 | M0 | Codex |
| TWOS-005 | Design Project Memory & Index System v0.1 | Architecture | P0 | M1 | Project Memory |
| TWOS-006 | Create Session Volume / Handoff Protocol | Feature | P0 | M1 | Project Memory |
| TWOS-007 | Design invisible context compression and restoration layer | Architecture | P0 | M1 | Project Memory |
| TWOS-008 | Create Project-Aware Reminder / Record Routing System | Feature | P0 | M1 | Project Memory |
| TWOS-009 | Create searchable decision log format | Feature | P1 | M1 | Project Memory |
| TWOS-010 | Define AI Board Mode v0.1 | Feature | P0 | M2 | AI Board |
| TWOS-011 | Create AI role cards and responsibility boundaries | Feature | P1 | M2 | AI Board |
| TWOS-012 | Create disagreement visualization and final arbitration protocol | Feature | P1 | M2 | AI Board |
| TWOS-013 | Create first-principles decision protocol template | Feature | P1 | M2 | AI Board |
| TWOS-014 | Build LLM Daredevil Desk cockpit information architecture | Feature | P0 | M3 | Financial Cockpit |
| TWOS-015 | Implement Opposite Exposure Detector / Net Exposure Map | Feature | P0 | M3 | Financial Cockpit |
| TWOS-016 | Implement Leveraged ETF Decay Warning System | Risk Control | P0 | M3 | Financial Cockpit |
| TWOS-017 | Implement Position Intent Tagging System | Feature | P0 | M3 | Financial Cockpit |
| TWOS-018 | Implement Multi-account Asset De-duplication System | Feature | P1 | M3 | Financial Cockpit |
| TWOS-019 | Define source-of-truth priority system for financial data | Feature | P0 | M3 | Financial Cockpit |
| TWOS-020 | Create LDD review scoring and forecast calibration module | Feature | P1 | M3 | Financial Cockpit |
| TWOS-021 | Create DUXD requirement intake and abstraction workflow | DUXD | P0 | M4 | DUXD |
| TWOS-022 | Create pain-point-to-product-requirement template | DUXD | P1 | M4 | DUXD |
| TWOS-023 | Create Codex task packaging workflow | Codex Task | P1 | M4 | Codex |
| TWOS-024 | Decide whether to create GitHub Projects board | Research | P2 | M4 | GitHub Workflow |
| TWOS-025 | Create Premarket vs Regular Session Execution Confirmation module | Feature | P0 | M3 | Financial Cockpit |
| TWOS-026 | Route review logs to the latest active project thread | Feature | P0 | M1 | Project Memory |
| TWOS-027 | Create Trade Intent Ledger | Feature | P0 | M3 | Financial Cockpit |
| TWOS-028 | Create Account Structure Improvement Score | Feature | P1 | M3 | Financial Cockpit |
| TWOS-029 | Create Multi-Source Signal Intake System | Feature | P0 | M5 | Signal Command |
| TWOS-030 | Create Signal Classification & Priority Engine | Feature | P0 | M5 | Signal Command |
| TWOS-031 | Create Stakeholder / External Resource Registry | Feature | P1 | M5 | Signal Command |
| TWOS-032 | Create Decision-to-Command Routing System | Feature | P0 | M5 | Signal Command |
| TWOS-033 | Create Codex / GitHub Execution Failure Recovery Protocol | Feature | P1 | M4 | Codex / GitHub Workflow |
| TWOS-034 | Create Project-Preserving Model Switching | Feature | P0 | M1 | Project Continuity UX |
| TWOS-035 | Create Cross-Workstream Interruption & Coordination System | Feature | P0 | M5 | Signal Command / Workstream Coordination |
| TWOS-036 | Create Strategy-State Risk Monitor | Feature | P0 | M3 | Financial Cockpit / Strategy Health |
| TWOS-037 | Create Agent Resource / Quota-Aware Execution Scheduler | Feature | P0 | M5 | Runtime / Agent Resource |
| TWOS-038 | Create Multi-Dimensional Progress Continuity & Resume Orchestrator | Feature | P0 | M5 | Runtime / Continuity |
| TWOS-039 | Create Rule-Based Execution Review | Feature | P0 | M3 | Financial Cockpit / Execution Review |
| TWOS-040 | Create Volatility-Aware Execution Splitter | Feature | P0 | M3 | Financial Cockpit / Execution |
| TWOS-041 | Create DUXD Spiral Improvement Loop | DUXD | P1 | M4 | DUXD / Methodology |
| TWOS-042 | Create Account Structure Quality Score | Feature | P0 | M3 | Financial Cockpit / Account Quality |
| TWOS-043 | Create Trigger-to-Execution Rule Ledger | Feature | P0 | M3 | Financial Cockpit / Rule Ledger |

---

# 7. Issue Drafts

## TWOS-001 — Create issue-ready backlog document

Type: `type:doc`  
Priority: `priority:p0-critical`  
Milestone: `M0 — Repository & Documentation Foundation`  
Labels: `area:docs`, `area:github-workflow`, `status:backlog`

### Background

The repository already contains the initial product blueprint. The next step is to convert strategy documents into executable GitHub Issues.

### Requirement

Create `GITHUB_ISSUES_BACKLOG.md` as the staging backlog before opening individual GitHub Issues.

### Acceptance Criteria

- A Markdown backlog file exists in the repository root.
- The file includes issue IDs, titles, priorities, suggested labels, milestones, and acceptance criteria.
- The file separates documentation, architecture, AI Board, project memory, LDD cockpit, DUXD, and Codex implementation work.
- The file explicitly states that GitHub Projects should not be created yet.

---

## TWOS-002 — Improve README and INDEX navigation for new contributors

Type: `type:doc`  
Priority: `priority:p1-high`  
Milestone: `M0 — Repository & Documentation Foundation`  
Labels: `area:docs`, `area:github-workflow`, `status:backlog`

### Background

The repository now contains many documents. New contributors, Codex, and future AI agents need a clear entry path.

### Requirement

Improve `README.md` and `INDEX.md` so readers can quickly understand:

- What Tianma Work OS is.
- Why it exists.
- Which document to read first.
- How DUXD connects to product development.
- How LLM Daredevil Desk acts as the seed battlefield.
- How to contribute or implement next steps.

### Acceptance Criteria

- `README.md` has a concise product introduction.
- `INDEX.md` groups documents by function.
- A “Start Here” section exists.
- A “Current Status” section references the latest baseline commit and current next step.
- A “Recommended Reading Order” exists.

---

## TWOS-003 — Define repository directory structure for product, examples, templates, and implementation

Type: `type:architecture`  
Priority: `priority:p1-high`  
Milestone: `M0 — Repository & Documentation Foundation`  
Labels: `area:architecture`, `area:github-workflow`, `status:backlog`

### Background

The current repository is document-first. Before implementation expands, the directory structure should remain clear.

### Requirement

Define and document a stable repository structure.

Suggested structure:

```text
/
├── README.md
├── INDEX.md
├── product/
├── architecture/
├── duxd/
├── examples/
│   └── llm-daredevil-desk/
├── templates/
├── codex/
├── implementation/
└── archive/
```

### Acceptance Criteria

- A proposed directory structure is documented.
- Existing documents are mapped into the structure.
- The structure supports both human reading and Codex execution.
- The structure avoids over-engineering before the MVP is stable.

---

## TWOS-004 — Create Codex implementation instruction template

Type: `type:codex-task`  
Priority: `priority:p1-high`  
Milestone: `M0 — Repository & Documentation Foundation`  
Labels: `area:codex`, `area:github-workflow`, `status:backlog`

### Background

Codex can sync documents to GitHub and later help implement product prototypes. It needs precise task packets.

### Requirement

Create a reusable Codex instruction template for repository updates.

### Acceptance Criteria

The template includes:

- Task goal.
- Files to create or modify.
- Exact folder paths.
- Constraints.
- Commit message suggestion.
- Verification steps.
- Expected final report format.

---

## TWOS-005 — Design Project Memory & Index System v0.1

Type: `type:architecture`  
Priority: `priority:p0-critical`  
Milestone: `M1 — Project Memory & Continuity MVP`  
Labels: `area:project-memory`, `area:architecture`, `area:mvp`, `status:backlog`

### Background

The first major real pain point is long project conversations becoming slow, fragmented, and difficult to search. Tianma Work OS must solve this as a core product capability.

### Requirement

Design a project-level memory and index system that preserves continuity across long-running project conversations.

### Acceptance Criteria

The design covers:

- Project-level memory.
- Session-level summaries.
- Decision records.
- Requirement records.
- Open tasks.
- File/document index.
- Cross-project sync blocks.
- Human-visible and user-invisible memory layers.
- How future AI agents retrieve the right context.

---

## TWOS-006 — Create Session Volume / Handoff Protocol

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M1 — Project Memory & Continuity MVP`  
Labels: `area:project-memory`, `area:ux`, `area:mvp`, `status:backlog`

### Background

The current manual workaround is to split long conversations into Vol.0, Vol.1, Vol.2, etc. This solves performance temporarily but requires a reliable handoff summary.

### Requirement

Create a standardized session handoff protocol.

### Acceptance Criteria

A handoff summary must include:

- Project name.
- Current volume number.
- Previous volume completed work.
- Current repository state.
- Key decisions.
- Open requirements.
- Latest active documents.
- Next recommended action.
- Known risks.
- Copy-ready block for the next conversation.

---

## TWOS-007 — Design invisible context compression and restoration layer

Type: `type:architecture`  
Priority: `priority:p0-critical`  
Milestone: `M1 — Project Memory & Continuity MVP`  
Labels: `area:project-memory`, `area:architecture`, `area:ux`, `status:backlog`

### Background

The final product should not force non-technical users to understand context windows, compression, indexing, or session splitting.

### Requirement

Design how Tianma Work OS should automatically compress, index, archive, and restore project context in the background.

### Acceptance Criteria

The design explains:

- What gets compressed.
- What remains visible.
- What becomes searchable.
- How retrieval is triggered.
- How users can inspect or override memory.
- How to avoid losing important decisions.
- How to avoid polluting memory with temporary details.

---

## TWOS-008 — Create Project-Aware Reminder / Record Routing System

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M1 — Project Memory & Continuity MVP`  
Labels: `area:project-memory`, `area:ux`, `area:duxd`, `status:backlog`

### Background

A DUXD pain point was discovered from the reminder workflow: reminders, scheduled tasks, review records, and operational logs should appear in the corresponding project’s latest active conversation by default.

### Requirement

Design a project-aware routing system for reminders and operational records.

### Acceptance Criteria

The design supports:

- Routing reminders to the correct project.
- Defaulting to the latest active project conversation.
- Overriding the destination when needed.
- Creating a new thread only when explicitly requested or logically necessary.
- Logging reminder outputs into project memory.

---

## TWOS-009 — Create searchable decision log format

Type: `type:feature`  
Priority: `priority:p1-high`  
Milestone: `M1 — Project Memory & Continuity MVP`  
Labels: `area:project-memory`, `area:docs`, `status:backlog`

### Background

Strategic product decisions are currently embedded in long conversations and may become difficult to retrieve.

### Requirement

Create a structured decision log format.

### Acceptance Criteria

Each decision record includes:

- Decision ID.
- Date.
- Context.
- Decision.
- Alternatives considered.
- Reasoning.
- Owner.
- Impacted documents or modules.
- Review date, if applicable.

---

## TWOS-010 — Define AI Board Mode v0.1

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M2 — AI Board Mode MVP`  
Labels: `area:ai-board`, `area:mvp`, `status:backlog`

### Background

Tianma Work OS is not simple model aggregation. Its core value is multi-role AI team collaboration.

### Requirement

Define AI Board Mode as a repeatable workflow for complex decisions.

### Acceptance Criteria

The specification includes:

- When AI Board Mode activates.
- Which roles participate.
- How each role contributes.
- How disagreement is surfaced.
- How final arbitration works.
- How decisions are recorded.
- How human strategy ownership is preserved.

---

## TWOS-011 — Create AI role cards and responsibility boundaries

Type: `type:feature`  
Priority: `priority:p1-high`  
Milestone: `M2 — AI Board Mode MVP`  
Labels: `area:ai-board`, `area:docs`, `status:backlog`

### Background

Role clarity is required for reliable multi-model collaboration.

### Requirement

Create role cards for core AI team members.

Suggested initial roles:

- Strategy Lead.
- Product Manager.
- Architect.
- Research Analyst.
- Data Verifier.
- Risk Officer.
- UX Designer.
- Implementation Agent.
- Review Officer.
- Final Commander.

### Acceptance Criteria

Each role card includes:

- Mission.
- Responsibilities.
- Inputs needed.
- Outputs produced.
- Escalation triggers.
- Failure modes.
- Example usage.

---

## TWOS-012 — Create disagreement visualization and final arbitration protocol

Type: `type:feature`  
Priority: `priority:p1-high`  
Milestone: `M2 — AI Board Mode MVP`  
Labels: `area:ai-board`, `area:ux`, `status:backlog`

### Background

Complex AI team decisions need visible disagreement rather than hidden consensus.

### Requirement

Design a protocol for showing role disagreement and producing a final decision.

### Acceptance Criteria

The protocol includes:

- How disagreements are detected.
- How conflicting role opinions are displayed.
- How risk warnings are elevated.
- How the Final Commander makes the final call.
- How unresolved uncertainty is documented.

---

## TWOS-013 — Create first-principles decision protocol template

Type: `type:feature`  
Priority: `priority:p1-high`  
Milestone: `M2 — AI Board Mode MVP`  
Labels: `area:ai-board`, `area:docs`, `status:backlog`

### Background

The project uses a first-principles loop:

1. What is the essence of the problem?
2. Why are we doing this?
3. Can we solve it?
4. Yes.
5. How do we solve it?
6. Is there a better way?

### Requirement

Turn this loop into a reusable product decision template.

### Acceptance Criteria

- The template exists in `templates/`.
- It can be used for product, engineering, UX, trading cockpit, and documentation decisions.
- It includes a final “better way” improvement pass.
- It produces a decision record.

---

## TWOS-014 — Build LLM Daredevil Desk cockpit information architecture

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:mvp`, `area:architecture`, `status:backlog`

### Background

LLM Daredevil Desk is the seed battlefield for Tianma Work OS. It must become the first domain-specific cockpit.

### Requirement

Design the LDD financial cockpit information architecture.

### Acceptance Criteria

The cockpit supports:

- U.S. equities section.
- Crypto section.
- Model strategy portfolio.
- Historical old positions.
- Bot/grid positions.
- Total real-account risk exposure.
- Daily review.
- Forecast.
- Action plan.
- Risk alerts.
- DUXD feedback output.

---

## TWOS-015 — Implement Opposite Exposure Detector / Net Exposure Map

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `type:risk-control`, `area:mvp`, `status:backlog`

### Background

LDD discovered a real risk: conflicting long/short and leveraged exposures can coexist in the same account, creating hidden risk and performance drag.

### Requirement

Design and later implement an Opposite Exposure Detector / Net Exposure Map.

### Acceptance Criteria

The system can identify:

- Long and inverse positions on the same theme.
- Leveraged ETF overlaps.
- Long/short conflicts.
- Theme-level net exposure.
- Decay-prone inverse ETF positions.
- Suggested cleanup priority.

Initial LDD example categories:

- Semiconductor long vs semiconductor inverse.
- TSLA long exposure vs TSLQ inverse exposure.
- Gold/gold-miner overlapping leveraged exposure.

---

## TWOS-016 — Implement Leveraged ETF Decay Warning System

Type: `type:risk-control`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:mvp`, `status:backlog`

### Background

Leveraged ETFs and ETNs can suffer from volatility decay and path dependency. LDD identified this as a recurring portfolio risk.

### Requirement

Create a warning system for leveraged and inverse ETF/ETN holdings.

### Acceptance Criteria

The system flags:

- 2x and 3x leveraged products.
- Inverse leveraged products.
- Long holding periods.
- Volatility-decay risk.
- Conflicting hedge use.
- Recommended review frequency.
- Whether the position is tactical, hedge, legacy error, or active opportunity.

---

## TWOS-017 — Implement Position Intent Tagging System

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:mvp`, `status:backlog`

### Background

LDD discovered that every holding needs a clear reason to exist. Otherwise historical mistakes, hedges, active opportunities, and model strategy trades get mixed together.

### Requirement

Create a Position Intent Tagging System.

### Acceptance Criteria

Each position can be tagged as:

- New strategy.
- Historical old position.
- Hedge.
- Legacy error.
- Leverage-decay position.
- Bot/grid position.
- Cash/financing pressure position.
- Active opportunity.
- Watch-only.

Each position also has:

- Current intent.
- Next required action.
- Risk level.
- Review trigger.
- Whether it belongs to model strategy performance.

---

## TWOS-018 — Implement Multi-account Asset De-duplication System

Type: `type:feature`  
Priority: `priority:p1-high`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `type:risk-control`, `status:backlog`

### Background

Financial cockpits can accidentally double-count assets across spot, funding, bot, futures, and margin accounts.

### Requirement

Design a Multi-account Asset De-duplication System.

### Acceptance Criteria

The system separates:

- New strategy performance.
- Historical old-position management.
- Robot/automated-strategy positions.
- Total real-account assets.
- Total risk exposure.

The system should prevent false portfolio totals caused by duplicated account views.

---

## TWOS-019 — Define source-of-truth priority system for financial data

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:mvp`, `type:risk-control`, `status:backlog`

### Background

LDD requires strict source verification. User-provided broker and exchange screenshots or platform prices are the execution source of truth. External data is used for cross-checking, context, news, and fundamentals.

### Requirement

Define a source-of-truth priority system for financial cockpit data.

### Acceptance Criteria

The system defines:

- Execution price source of truth.
- External market data source role.
- News and fundamentals source role.
- Timestamp requirements.
- What to do when data conflicts.
- What confidence level to assign to each data type.
- How to display uncertainty.

---

## TWOS-020 — Create LDD review scoring and forecast calibration module

Type: `type:feature`  
Priority: `priority:p1-high`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:duxd`, `status:backlog`

### Background

LDD reviews must evaluate not only market outcomes but also the AI team's forecast quality and decision process.

### Requirement

Create a review scoring and forecast calibration module.

### Acceptance Criteria

The module tracks:

- Yesterday’s forecast.
- Actual market outcome.
- Correct and incorrect assumptions.
- Signal quality.
- Missed risks.
- Decision score.
- Execution score.
- Risk-control score.
- Rule updates.
- DUXD product feedback.

---

## TWOS-021 — Create DUXD requirement intake and abstraction workflow

Type: `type:duxd`  
Priority: `priority:p0-critical`  
Milestone: `M4 — DUXD Feedback Loop & Codex Implementation Workflow`  
Labels: `area:duxd`, `area:mvp`, `status:backlog`

### Background

DUXD is the core development methodology. Real user pain points must become product requirements systematically.

### Requirement

Create a DUXD intake workflow.

### Acceptance Criteria

The workflow supports:

- Capturing raw pain points.
- Identifying real scenario context.
- Abstracting product requirement.
- Assigning requirement ID.
- Linking to affected modules.
- Defining implementation priority.
- Creating GitHub issue candidates.
- Feeding back into real scenario testing.

---

## TWOS-022 — Create pain-point-to-product-requirement template

Type: `type:duxd`  
Priority: `priority:p1-high`  
Milestone: `M4 — DUXD Feedback Loop & Codex Implementation Workflow`  
Labels: `area:duxd`, `area:templates`, `status:backlog`

### Background

The project needs a repeatable template for converting deep usage friction into product design.

### Requirement

Create a template in `templates/`.

### Acceptance Criteria

The template includes:

- Pain point.
- User scenario.
- Frequency.
- Severity.
- Root cause.
- Product abstraction.
- Proposed requirement.
- Acceptance criteria.
- Related documents.
- Suggested issue title.
- Suggested priority.
- DUXD review notes.

---

## TWOS-023 — Create Codex task packaging workflow

Type: `type:codex-task`  
Priority: `priority:p1-high`  
Milestone: `M4 — DUXD Feedback Loop & Codex Implementation Workflow`  
Labels: `area:codex`, `area:github-workflow`, `status:backlog`

### Background

Codex can implement repository changes, but each task needs clear boundaries and verification steps.

### Requirement

Create a standard workflow that turns selected backlog items into Codex-ready implementation tasks.

### Acceptance Criteria

The workflow includes:

- Input issue.
- Files to inspect.
- Files to create or modify.
- Constraints.
- Expected output.
- Test or verification steps.
- Commit message format.
- Final status report format.

---

## TWOS-024 — Decide whether to create GitHub Projects board

Type: `type:research`  
Priority: `priority:p2-medium`  
Milestone: `M4 — DUXD Feedback Loop & Codex Implementation Workflow`  
Labels: `area:github-workflow`, `status:backlog`

### Background

The current decision is not to create a GitHub Projects board yet. A board may become useful after the backlog stabilizes.

### Requirement

Evaluate when a GitHub Projects board becomes necessary.

### Acceptance Criteria

A recommendation is made based on:

- Number of active issues.
- Number of contributors or agents.
- Need for status visualization.
- MVP implementation complexity.
- Whether a simple Markdown backlog remains sufficient.

Recommended decision threshold:

- Fewer than 15 active issues: Markdown backlog is enough.
- 15–30 active issues: consider GitHub Projects.
- More than 30 active issues or multiple contributors/agents: create GitHub Projects board.

---

---

## TWOS-025 — Create Premarket vs Regular Session Execution Confirmation module

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `type:risk-control`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

LDD often generates trading plans before the U.S. regular session opens. Premarket signals can be useful, but liquidity, price reliability, volatility, and leadership can change after the regular session starts.

A DUXD requirement was discovered on 2026-05-27: premarket action plans should require a confirmation checkpoint after regular market open before execution.

### Requirement

Create a Premarket vs Regular Session Execution Confirmation module for the LDD financial cockpit.

### Acceptance Criteria

The module supports:

- Distinguishing premarket analysis from regular-session execution signals.
- Marking actions as `premarket plan`, `pending confirmation`, `confirmed`, `invalidated`, or `needs human review`.
- Defining confirmation triggers for each asset or position.
- Recording whether the regular-session market confirmed or rejected the premarket plan.
- Preventing premature execution when key confirmation data is missing.
- Logging confirmation decisions into the daily review record.

Initial LDD confirmation examples:

- Verify whether TSLA holds above 430 or 436–438 before executing TSLQ cleanup.
- Verify GDXU around 154–155 or 165–170 before reducing exposure.
- Verify GLD around 412 before reducing UGL.
- Verify SOXL around 220 before chasing or avoiding semiconductor exposure.
- Verify BTC 74,200 / 78,000 and ZEC 560 / 620 / 660 zones before crypto actions.

---

## TWOS-026 — Route review logs to the latest active project thread

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M1 — Project Memory & Continuity MVP`  
Labels: `area:project-memory`, `area:ux`, `area:duxd`, `status:backlog`

### Background

A DUXD requirement was discovered from LDD reminder and review workflows: review logs should be written into the corresponding project’s latest active thread by default.

This is related to TWOS-008 but should be tracked explicitly because review logs are high-value operational records.

### Requirement

Design review-log routing behavior for Tianma Work OS.

### Acceptance Criteria

The routing system supports:

- Detecting the relevant project context.
- Routing review logs to the latest active conversation for that project by default.
- Avoiding scattered new conversations unless the user explicitly requests a new thread.
- Preserving review time, source data, conclusions, actions, pending checks, risks, and DUXD feedback.
- Creating searchable project memory entries from review logs.
- Allowing user override when a review belongs to a different project or subproject.

---

## TWOS-027 — Create Trade Intent Ledger

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `type:risk-control`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

LDD discovered that a trade record is incomplete if it only records ticker, quantity, price, and P/L.

A real financial cockpit must know why a trade happened. Otherwise the system cannot distinguish a new strategy entry from a historical cleanup, a leverage-decay exit, a hedge removal, or a cash-release action.

### Requirement

Create a Trade Intent Ledger for the LDD financial cockpit.

### Acceptance Criteria

Each trade record supports:

- Trade timestamp.
- Account or sub-account.
- Asset class.
- Ticker or symbol.
- Quantity.
- Price.
- Gross value.
- Fees, if available.
- Realized P/L, if available.
- Source of execution data.
- Trade intent.
- Linked position intent tag.
- Linked net exposure impact.
- Linked review record.
- Whether the trade belongs to model strategy performance or historical-position management.

Initial trade intent categories:

- `new_entry`
- `add_to_position`
- `reduce_position`
- `historical_cleanup`
- `risk_reduction`
- `leverage_decay_exit`
- `hedge_removal`
- `stop_loss`
- `take_profit`
- `bot_profit_protection`
- `cash_release`
- `rebalance`
- `mistake_correction`
- `manual_override`

The ledger should support human-readable labels and machine-readable intent codes.

### LDD Example

TSLQ, SOXS, GDXU, and UGL reductions should not be recorded as LDD U.S. model strategy trades.

They should be recorded as historical-position cleanup and risk-reduction trades.

---

## TWOS-028 — Create Account Structure Improvement Score

Type: `type:feature`  
Priority: `priority:p1-high`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `type:risk-control`, `area:duxd`, `status:backlog`

### Background

A trade should not be judged only by immediate profit or loss.

For example, closing a decaying inverse leveraged ETF at a realized loss may still improve the account by removing bad convexity, opposite exposure, financing pressure, or long-term decay risk.

### Requirement

Create an Account Structure Improvement Score for trade review.

### Acceptance Criteria

The score evaluates whether a trade improved:

- Net exposure clarity.
- Leverage risk.
- Opposite exposure risk.
- Concentration risk.
- Cash flexibility.
- Strategy purity.
- Separation between model strategy and historical positions.
- Reduction of legacy-error positions.
- Reduction of volatility-decay exposure.
- Alignment with current strategy.

The score should be shown alongside immediate P/L.

Suggested output fields:

- `immediate_pnl_result`
- `structure_improvement_score`
- `risk_reduction_score`
- `strategy_alignment_score`
- `cash_flexibility_impact`
- `net_exposure_impact`
- `review_comment`

### LDD Example

Closing SOXS and TSLQ may realize or lock in historical losses, but it can still receive a high structure-improvement score because it removes opposite exposure, inverse-leveraged decay risk, and strategic confusion.

---

## TWOS-029 — Create Multi-Source Signal Intake System

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M5 — Multi-Source Signal Command Layer MVP`  
Labels: `area:signal-command`, `area:mvp`, `area:architecture`, `area:duxd`, `status:backlog`

### Background

As Tianma Work OS moves from documentation into development, information no longer comes from one source.

The project already has several real signal streams:

- LDD review feedback.
- Codex task instructions.
- Codex execution reports.
- GitHub repository updates.

Future sources may include:

- GitHub Issues, Pull Requests, and comments.
- Customers.
- Suppliers.
- Employees.
- Partners.
- Investors.
- Advisors.
- Market events.
- Media events.
- Regulatory or international events.

Without a unified intake system, important signals will be scattered across chats, documents, GitHub, Codex reports, and external channels.

### Requirement

Create a Multi-Source Signal Intake System.

### Acceptance Criteria

The system supports intake records with:

- Signal ID.
- Source type.
- Source name.
- Project.
- Related subproject.
- Timestamp.
- Raw content.
- Summary.
- Attachments or links.
- Initial classification.
- Initial priority.
- Confidence level.
- Suggested routing destination.
- Related memory records.
- Related decisions, issues, tasks, or commands.

Initial MVP source types:

- `ldd_sync_block`
- `codex_instruction`
- `codex_execution_report`
- `github_issue`
- `github_pull_request`
- `github_comment`
- `user_feedback`
- `project_update`

Future source types:

- `customer_feedback`
- `supplier_update`
- `employee_update`
- `partner_feedback`
- `investor_feedback`
- `advisor_feedback`
- `market_event`
- `media_event`
- `regulatory_event`
- `international_event`

### MVP Constraint

The first implementation should focus on three source streams:

1. LDD Sync Blocks.
2. Codex Task / Execution Reports.
3. GitHub Issue / Pull Request / Comment Feedback.

---

## TWOS-030 — Create Signal Classification & Priority Engine

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M5 — Multi-Source Signal Command Layer MVP`  
Labels: `area:signal-command`, `area:mvp`, `area:ai-board`, `area:duxd`, `status:backlog`

### Background

Raw signals are not equal. Some are urgent execution blockers. Some are product requirements. Some are low-confidence external noise. Some are strategic inputs. Some should be archived only.

Tianma Work OS needs a systematic way to classify and prioritize incoming signals before they are routed to AI Board, project memory, backlog, Codex, GitHub, or a human decision-maker.

### Requirement

Create a Signal Classification & Priority Engine.

### Acceptance Criteria

The engine supports:

- Signal type classification.
- Domain classification.
- Urgency scoring.
- Priority scoring.
- Reliability scoring.
- Confidence level.
- Impact scope.
- Suggested next action.
- Suggested routing target.
- Human review flag.

Suggested `signal_type` values:

- `trading_review`
- `product_feedback`
- `codex_execution_result`
- `github_feedback`
- `bug_report`
- `feature_request`
- `strategic_input`
- `market_event`
- `stakeholder_feedback`
- `operational_update`
- `risk_alert`
- `decision_request`
- `implementation_blocker`

Suggested priority values:

- `critical`
- `high`
- `medium`
- `low`

Suggested urgency values:

- `immediate`
- `today`
- `this_week`
- `later`
- `archive_only`

Suggested confidence values:

- `verified`
- `user_reported`
- `source_reported`
- `external_unverified`
- `conflicting`
- `unknown`

### AI Board Integration

Signals with high impact, conflicting evidence, or cross-domain implications should trigger AI Board Mode.

---

## TWOS-031 — Create Stakeholder / External Resource Registry

Type: `type:feature`  
Priority: `priority:p1-high`  
Milestone: `M5 — Multi-Source Signal Command Layer MVP`  
Labels: `area:signal-command`, `area:project-memory`, `area:architecture`, `status:backlog`

### Background

Real projects involve many stakeholders and external resource streams. Tianma Work OS must know who or what a signal came from, how much weight it should carry, and where responses should go.

### Requirement

Create a Stakeholder / External Resource Registry.

### Acceptance Criteria

The registry supports:

- Source ID.
- Source name.
- Source type.
- Relationship to project.
- Trust level.
- Decision weight.
- Usual response channel.
- Related projects.
- Related documents.
- Historical reliability notes.
- Last interaction timestamp.
- Open loops or pending responses.

Suggested `source_type` values:

- `user`
- `customer`
- `developer`
- `codex`
- `github_community`
- `supplier`
- `employee`
- `partner`
- `investor`
- `advisor`
- `market_data_source`
- `media_source`
- `regulator`
- `competitor`
- `unknown_external`

### MVP Constraint

The first version can support only:

- User.
- LDD.
- Codex.
- GitHub.

The schema should still allow future expansion.

---

## TWOS-032 — Create Decision-to-Command Routing System

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M5 — Multi-Source Signal Command Layer MVP`  
Labels: `area:signal-command`, `area:ai-board`, `area:codex`, `area:github-workflow`, `area:mvp`, `status:backlog`

### Background

Tianma Work OS should not stop at collecting and analyzing information. It must turn decisions into precise outbound commands or feedback.

Examples:

- LDD review produces a product requirement → update backlog.
- Codex execution fails → generate a repair instruction.
- GitHub user feedback suggests a feature → create an issue candidate.
- Investor advice affects strategy → route to strategy review.
- Customer complaint reveals a UX problem → route to product and support triage.
- Market event affects trading risk → route to LDD risk review.

### Requirement

Create a Decision-to-Command Routing System.

### Acceptance Criteria

The system supports:

- Decision ID.
- Source signal IDs.
- AI Board summary.
- Final decision.
- Command destination.
- Command type.
- Command content.
- Owner.
- Due date or urgency.
- Expected feedback format.
- Tracking status.
- Related issue, pull request, document, or memory record.
- Closed-loop confirmation.

Suggested `command_destination` values:

- `user`
- `codex`
- `github_issue`
- `github_pull_request`
- `project_memory`
- `ldd_cockpit`
- `product_backlog`
- `decision_log`
- `external_stakeholder`
- `archive`

Suggested `command_type` values:

- `create_issue`
- `update_document`
- `execute_coding_task`
- `request_clarification`
- `send_feedback`
- `schedule_review`
- `update_memory`
- `trigger_ai_board`
- `archive_only`

### MVP Constraint

The first version should support:

1. LDD signal → product requirement / backlog update.
2. Codex report → follow-up Codex instruction.
3. GitHub feedback → issue candidate or documentation update.

---

## TWOS-033 — Create Codex / GitHub Execution Failure Recovery Protocol

Type: `type:feature`  
Priority: `priority:p1-high`  
Milestone: `M4 — DUXD Feedback Loop & Codex Implementation Workflow`  
Labels: `area:codex`, `area:github-workflow`, `area:execution-recovery`, `type:technical-debt`, `area:duxd`, `status:backlog`

### Background

During Vol.2, Codex successfully committed local repository changes but failed to push to GitHub twice due to HTTPS connection timeouts.

The failure was recovered through diagnostics:

- Confirming the working tree was clean.
- Confirming local commits were preserved.
- Confirming the branch was ahead of `origin/main`.
- Checking Git remote configuration.
- Checking Git proxy configuration.
- Checking GitHub and GitHub API reachability with `curl`.
- Checking SSH reachability.
- Retrying HTTPS push with verbose Git tracing.

The verbose HTTPS retry succeeded.

### Requirement

Create a standard Codex / GitHub Execution Failure Recovery Protocol.

The protocol should help Tianma Work OS handle execution-agent failures safely instead of treating them as unstructured interruptions.

### Acceptance Criteria

The protocol supports:

- Detecting execution failure type.
- Preserving current work before further action.
- Checking repository cleanliness.
- Checking local commits and branch divergence.
- Checking remote configuration.
- Checking network reachability.
- Checking proxy configuration.
- Checking authentication or permission failures.
- Checking SSH fallback feasibility.
- Recommending the safest next action.
- Deciding whether the issue blocks the project.
- Recording the failure and recovery result into project memory.
- Generating a follow-up Codex instruction when needed.

Suggested failure categories:

- `network_timeout`
- `authentication_failure`
- `permission_denied`
- `host_key_verification_failed`
- `dirty_working_tree`
- `merge_conflict`
- `remote_rejected`
- `rate_limit`
- `tool_limitation`
- `unclear_instruction`
- `unknown_failure`

Suggested recovery states:

- `recovered`
- `retry_needed`
- `requires_user_action`
- `blocked`
- `safe_to_continue`
- `archive_only`

### Recovery Rule from Vol.2

If HTTPS push timeout recurs:

1. Confirm `git status`, `git branch -vv`, and `git log --oneline -5`.
2. Check `curl -I https://github.com`.
3. Check `curl -I https://api.github.com`.
4. Check Git proxy settings.
5. Retry HTTPS once with:

```bash
GIT_CURL_VERBOSE=1 GIT_TRACE=1 git push origin main
```

6. If it still fails, fix SSH host-key setup or push manually from the local terminal.

### DUXD Lesson

Every execution-chain failure should become structured product knowledge.

A failure is not merely trouble. It is a chance to improve the solution and upgrade the product.

---

## TWOS-034 — Create Project-Preserving Model Switching

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M1 — Project Memory & Continuity MVP`  
Labels: `area:project-continuity`, `area:model-switching`, `area:ux`, `area:project-memory`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

A DUXD discovery came from using ChatGPT project conversations.

In the Mac app, switching to a Thinking model from the top conversation-title selector can create or jump to a new chat that may not remain inside the current Project. This breaks the continuity that Tianma Work OS is designed to protect.

For long-running projects, model switching should not scatter work across unrelated conversations or cause the user to lose project context.

### Requirement

Create a Project-Preserving Model Switching design.

The user should be able to change model, role, or thinking intensity inside a project without leaving the project context.

### Acceptance Criteria

The design supports:

- Switching models inside the current project without creating an unassigned new chat.
- Switching thinking intensity inside the current project.
- Preserving project memory, files, instructions, and current session context.
- Preserving active project routing for reminders, review logs, and operational records.
- Warning the user before any switch that would create a new conversation.
- If a new conversation is technically required, defaulting that conversation into the current project.
- Generating an automatic handoff summary when a new project conversation is required.
- Linking the old and new conversations in the project index.
- Preventing accidental work fragmentation across non-project chats.

### Related Issues

- `TWOS-005 — Design Project Memory & Index System v0.1`
- `TWOS-006 — Create Session Volume / Handoff Protocol`
- `TWOS-008 — Create Project-Aware Reminder / Record Routing System`
- `TWOS-026 — Route review logs to the latest active project thread`
- `TWOS-029 — Create Multi-Source Signal Intake System`
- `TWOS-032 — Create Decision-to-Command Routing System`

### DUXD Lesson

Model capability is not enough.

For serious project work, stronger models must be reachable without breaking project continuity.

The user should not have to choose between better reasoning and keeping the project context intact.

---

## TWOS-035 — Create Cross-Workstream Interruption & Coordination System

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M5 — Multi-Source Signal Command Layer MVP`  
Labels: `area:signal-command`, `area:workstream-coordination`, `area:project-memory`, `area:duxd`, `area:mvp`, `status:backlog`

### Background

During Vol.2, Tianma Work OS / GitHub work reached a clean checkpoint after creating the first 8 GitHub trunk issues. A time-sensitive LDD review then arrived.

The correct decision was not to keep pushing Codex execution blindly. The system paused the Codex/GitHub workstream and switched to LDD review while preserving the GitHub resume point.

This exposed a product need: Tianma Work OS must coordinate competing active workstreams.

### Requirement

Create a Cross-Workstream Interruption & Coordination System.

The system should decide whether an incoming signal should interrupt, pause, queue, or simply be recorded while another workstream is active.

### Acceptance Criteria

The system supports:

- Active workstream detection.
- Incoming signal classification.
- Urgency and priority comparison.
- Workstream pause checkpoint.
- Resume-point preservation.
- Decision reason logging.
- Queued follow-up tasks.
- Cross-project or cross-workstream memory routing.
- Human override.
- Return-to-workflow reminder or resume command.

Suggested workstream states:

- `active`
- `paused`
- `queued`
- `interrupted`
- `resumed`
- `completed`
- `blocked`

Suggested coordination decisions:

- `continue_current`
- `pause_and_switch`
- `queue_new_signal`
- `record_only`
- `merge_into_current`
- `escalate_to_human`
- `trigger_ai_board`

### Real Case

Current workstream:

- GitHub issues first batch creation.

Incoming workstream:

- LDD premarket and ZEC bot risk review.

Decision:

- Pause further Codex execution.
- Switch to LDD review.
- Preserve GitHub state:
  - v0.1.5 pushed.
  - issues #1–#8 created.
  - repo clean.
  - no Projects board.
  - next Codex work deferred.

### Related Issues

- `TWOS-029 — Create Multi-Source Signal Intake System`
- `TWOS-030 — Create Signal Classification & Priority Engine`
- `TWOS-032 — Create Decision-to-Command Routing System`
- `TWOS-034 — Create Project-Preserving Model Switching`

---

## TWOS-036 — Create Strategy-State Risk Monitor

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:strategy-health`, `area:bot-monitoring`, `type:risk-control`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

LDD discovered that an automated strategy can remain profitable while its risk state is deteriorating.

The ZEC spot grid bot case showed this clearly. One ZEC bot was still profitable, but its total return was close to the hard protection threshold. The correct interpretation was not simply “profitable,” but “profitable but deteriorating.”

### Requirement

Create a Strategy-State Risk Monitor for automated strategies, bot positions, and structured strategy positions.

The monitor should track strategy health, profit drawdown, deterioration state, and action thresholds.

### Acceptance Criteria

The system supports:

- Strategy ID.
- Strategy type.
- Linked asset.
- Account or sub-account.
- Initial capital.
- Current value.
- Current return percentage.
- Peak return percentage.
- Profit drawdown percentage.
- Soft warning threshold.
- Hard protection threshold.
- Market-state context.
- Strategy health state.
- Recommended action.
- Last review time.
- Linked trade intent ledger entries.
- Linked position intent tags.
- Linked decision or review logs.

Suggested `strategy_type` values:

- `spot_grid_bot`
- `futures_grid_bot`
- `manual_position_strategy`
- `model_portfolio_strategy`
- `hedge_strategy`
- `cash_defense_strategy`

Suggested `health_state` values:

- `healthy_profit`
- `profitable_but_deteriorating`
- `near_protection_threshold`
- `below_protection_threshold`
- `forced_exit_required`
- `stopped`

### Real Case

ZEC grid bot update:

- 600U / 80-grid bot: closed.
- Automatic ZEC selling selected.
- Sold about 0.608 ZEC at about 524.61 USDT.
- Remaining 500U / 60-grid bot:
  - asset value about 601.84 USDT.
  - total return about +32.78%.
  - hard protection threshold: below 30%.
  - health state: `profitable_but_deteriorating`.

### Product Principle

A strategy can still be profitable but no longer safe.

The cockpit must monitor strategy health, not only current P/L.

### Profit Surge Protection Sub-module

Grid/robot strategies need upside lock-profit monitoring, not only downside stop-loss monitoring.

The system should detect when a bot moves from normal running state into high-profit lock-profit state and recommend:

- Continue.
- Extract profit.
- Partially close.
- Fully close.

Suggested states:

- `normal_running`
- `healthy_profit`
- `profit_surge_observation`
- `lock_profit_zone`
- `profit_extraction_recommended`
- `partial_close_recommended`
- `full_close_recommended`
- `downside_protection_triggered`

Real case:

As of 2026-06-01, the remaining 500U / 60-grid ZEC bot had total return around +39.87%, near a 40% lock-profit observation zone.

Rules:

- Continue while total return stays above 35%.
- Consider profit extraction or closure at 40%-42%.
- Consider closure if ZEC approaches 600-620.
- Prepare to close near 31.5%.
- Close below 30%.

### Related Issues

- `TWOS-017 — Implement Position Intent Tagging System`
- `TWOS-020 — Create LDD review scoring and forecast calibration module`
- `TWOS-027 — Create Trade Intent Ledger`
- `TWOS-028 — Create Account Structure Improvement Score`
- `TWOS-029 — Create Multi-Source Signal Intake System`
- `TWOS-032 — Create Decision-to-Command Routing System`

---

## TWOS-037 — Create Agent Resource / Quota-Aware Execution Scheduler

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M5 — Multi-Source Signal Command Layer MVP`  
Labels: `area:runtime`, `area:agent-resource`, `area:codex`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

Codex quota exhaustion showed that execution agents are finite, stateful resources. Tianma Work OS must know when an agent is unavailable, which task types are blocked, and what can still continue safely.

### Requirement

Create an Agent Resource / Quota-Aware Execution Scheduler.

The scheduler should preserve checkpoints, avoid stacking risky changes, continue in non-mutating design mode when needed, queue pending tasks, and resume execution from a clean state when capacity returns.

### Acceptance Criteria

The system supports:

- Tracking `agent_id`.
- Tracking `agent_type`.
- Tracking `availability_state`.
- Tracking `quota_state`.
- Tracking `current_blocker`.
- Tracking `safe_task_types`.
- Tracking `blocked_task_types`.
- Tracking `resume_time`.
- Tracking `pending_queue`.
- Tracking `fallback_agent`.
- Tracking `manual_override`.

Suggested `availability_state` values:

- `available`
- `rate_limited`
- `quota_exhausted`
- `network_blocked`
- `auth_blocked`
- `permission_blocked`
- `tool_unavailable`
- `manual_only`
- `unsafe_to_execute`
- `unknown`

Suggested execution modes:

- `execute_now`
- `queue_until_available`
- `switch_agent`
- `manual_handoff`
- `non_mutating_discussion_only`
- `blocked`

The system preserves checkpoints when agents are unavailable.

---

## TWOS-038 — Create Multi-Dimensional Progress Continuity & Resume Orchestrator

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M5 — Multi-Source Signal Command Layer MVP`  
Labels: `area:runtime`, `area:workstream-coordination`, `area:project-memory`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

A blocked dimension should not freeze the whole project. During Codex pause, LDD review, product architecture, and DUXD discovery continued.

### Requirement

Create a Multi-Dimensional Progress Continuity & Resume Orchestrator.

The orchestrator should preserve blocked checkpoints, advance unblocked dimensions, and reconcile all progress when the blocked dimension resumes.

### Acceptance Criteria

The system supports:

- Maintaining a dimension registry.
- Tracking blocked dimensions.
- Tracking active dimensions.
- Preserving checkpoints.
- Routing progress to unblocked dimensions.
- Maintaining a pending queue.
- Running a resume bridge before restarting blocked dimensions.
- Reconciling pause-period updates before further execution.

---

## TWOS-039 — Create Rule-Based Execution Review

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:execution-review`, `type:risk-control`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

LDD discovered that the user sold 5 SOXL at 206 after SOXL broke the 210 protection line. SOXL later rebounded, but the sale was rule-compliant and improved risk structure.

### Requirement

Create a Rule-Based Execution Review module.

Trade correctness should be judged by rule compliance and account-risk improvement, not by short-term price movement after execution.

### Acceptance Criteria

The system supports:

- Evaluating whether a trade followed predefined rules.
- Evaluating whether account risk improved.
- Distinguishing rule compliance from short-term price outcome.
- Linking to Trade Intent Ledger.
- Linking to Position Intent Tags.
- Linking to Account Structure Quality Score.

Suggested review results:

- `rule_compliant`
- `rule_violation`
- `rule_ambiguous`
- `improved_structure`
- `worsened_structure`

---

## TWOS-040 — Create Volatility-Aware Execution Splitter

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:execution`, `type:risk-control`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

For high-volatility leveraged ETFs, ETNs, crypto, and bot strategies, execution should be staged rather than binary.

### Requirement

Create a Volatility-Aware Execution Splitter.

The splitter should recommend partial exit, confirmation windows, rebound zones, and final stop lines.

### Acceptance Criteria

The system supports:

- Staged exits.
- Staged entries.
- Partial exit zones.
- Confirmation windows.
- Rebound zones.
- Final stop lines.
- Application to leveraged ETFs.
- Application to inverse ETFs.
- Application to ETNs.
- Application to crypto.
- Application to high-beta stocks.
- Application to grid/bot strategies.
- Linking to Trigger-to-Execution Rule Ledger.

---

## TWOS-041 — Create DUXD Spiral Improvement Loop

Type: `type:duxd`  
Priority: `priority:p1-high`  
Milestone: `M4 — DUXD Feedback Loop & Codex Implementation Workflow`  
Labels: `area:duxd`, `area:methodology`, `area:docs`, `status:backlog`

### Background

Tianma Work OS and DUXD are mutually reinforcing. Real project execution improves the product, the product structures the method, and the improved method improves future requirement discovery.

### Requirement

Create a DUXD Spiral Improvement Loop.

DUXD should be defined not only as a requirement discovery method, but as a spiral product evolution mechanism driven by real project execution.

### Acceptance Criteria

The system supports:

- Defining DUXD as a spiral product evolution mechanism.
- Documenting the loop: real project execution -> real friction -> product requirement -> system upgrade -> methodology upgrade -> better execution.
- Explaining how LDD, Tianma Work OS, Codex/GitHub, and DUXD mutually reinforce each other.
- Adding this concept to future methodology documentation.

---

## TWOS-042 — Create Account Structure Quality Score

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:account-quality`, `type:risk-control`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

After SOXS, TSLQ, GDXU, partial SOXL, partial INTC, and partial GGLL reductions, the account moved from risk-cleanup mode toward account-structure optimization. Cash improved from negative financing pressure to positive cash.

### Requirement

Create an Account Structure Quality Score.

A trading cockpit should not only evaluate P/L. It should evaluate account structure quality: cash pressure, exposure clarity, leverage risk, bot health, strategy separation, and redeployment readiness.

### Acceptance Criteria

The system evaluates:

- Cash / financing pressure.
- Exposure clarity.
- Leverage risk.
- Opposite exposure.
- Legacy vs strategy separation.
- Bot / automated strategy health.
- Concentration risk.
- Rule compliance.
- Redeployment readiness.
- Portfolio cleanliness.

The system outputs an account structure quality score and review comment.

---

## TWOS-043 — Create Trigger-to-Execution Rule Ledger

Type: `type:feature`  
Priority: `priority:p0-critical`  
Milestone: `M3 — LLM Daredevil Desk Financial Cockpit MVP`  
Labels: `area:financial-cockpit`, `area:rule-ledger`, `type:risk-control`, `area:mvp`, `area:duxd`, `status:backlog`

### Background

LDD discovered that remaining positions now have many trigger conditions and next action lines, including SOXL 210 / 205, GOOG / GGLL 380 / 374, GLD / UGL 405, NVDA 208, INTC 118 / 114, BTC 75,500-76,000 staged buyback, and ZEC bot 31.5% / 30%.

### Requirement

Create a Trigger-to-Execution Rule Ledger.

A financial cockpit must remember why a position should be acted on, which trigger fired, what was executed, what remains, and what the next trigger is.

### Acceptance Criteria

The system tracks:

- `position_id`
- `asset`
- `current_quantity`
- `trigger_condition`
- `trigger_level`
- `execution_status`
- `executed_quantity`
- `remaining_quantity`
- `execution_price`
- `trade_intent`
- `next_trigger_line`
- `next_action`
- `reminder_required`
- `last_review_time`

The system links to:

- Trade records.
- Position intent.
- Account quality score.
- Reminders.

Suggested states:

- `waiting`
- `triggered`
- `executed`
- `partially_executed`
- `invalidated`
- `next_trigger_pending`
- `closed`

The ledger prevents rule drift and forgotten follow-up actions.

# 8. Recommended First Issues to Create

Do not create all backlog issues immediately.

The first 8 trunk GitHub Issues have already been created. Items after the first created trunk set should remain pending for later issue creation unless explicitly selected.

Recommended first batch:

1. TWOS-001 — Create issue-ready backlog document.
2. TWOS-005 — Design Project Memory & Index System v0.1.
3. TWOS-006 — Create Session Volume / Handoff Protocol.
4. TWOS-008 — Create Project-Aware Reminder / Record Routing System.
5. TWOS-010 — Define AI Board Mode v0.1.
6. TWOS-014 — Build LLM Daredevil Desk cockpit information architecture.
7. TWOS-015 — Implement Opposite Exposure Detector / Net Exposure Map.
8. TWOS-017 — Implement Position Intent Tagging System.
9. TWOS-021 — Create DUXD requirement intake and abstraction workflow.
10. TWOS-025 — Create Premarket vs Regular Session Execution Confirmation module.
11. TWOS-027 — Create Trade Intent Ledger.
12. TWOS-029 — Create Multi-Source Signal Intake System.
13. TWOS-030 — Create Signal Classification & Priority Engine.
14. TWOS-032 — Create Decision-to-Command Routing System.
15. TWOS-033 — Create Codex / GitHub Execution Failure Recovery Protocol.
16. TWOS-034 — Create Project-Preserving Model Switching.
17. TWOS-035 — Create Cross-Workstream Interruption & Coordination System.
18. TWOS-036 — Create Strategy-State Risk Monitor.
19. TWOS-037 — Create Agent Resource / Quota-Aware Execution Scheduler.
20. TWOS-038 — Create Multi-Dimensional Progress Continuity & Resume Orchestrator.
21. TWOS-039 — Create Rule-Based Execution Review.
22. TWOS-040 — Create Volatility-Aware Execution Splitter.
23. TWOS-041 — Create DUXD Spiral Improvement Loop.
24. TWOS-042 — Create Account Structure Quality Score.
25. TWOS-043 — Create Trigger-to-Execution Rule Ledger.

Reason:

These issues represent the real MVP spine:

- Project continuity.
- Reminder, record, and review-log routing.
- Multi-role AI collaboration.
- Domain-specific cockpit.
- Financial risk-control use case.
- Premarket-to-regular-session execution confirmation.
- Trade intent and account-structure improvement evaluation.
- Multi-source signal intake, classification, and command routing.
- DUXD feedback loop.

---

# 9. Current Recommendation

For Vol.2, the next best workflow is:

1. Add this updated file to the repository root as `GITHUB_ISSUES_BACKLOG.md`.
2. Update `INDEX.md` to include this file.
3. Review the recommended and pending backlog items.
4. Keep the first 8 trunk GitHub Issues as the current created issue set.
5. Continue delaying GitHub Projects until the first active issue set is stable.
6. Ask Codex to implement the documentation update with a clean commit.

Suggested commit message:

```text
Add GitHub issues backlog v0.1.7
```

---

# 10. Codex Task Packet Draft

Use this instruction if asking Codex to sync the file.

```text
Task: Add GitHub Issues Backlog v0.1.7 to Tianma Work OS repository.

Repository:
https://github.com/loseyourself1978-blip/tianma-work-os

Current baseline:
e3e15d7 Add Tianma Work OS product blueprint documents

Files to create:
- GITHUB_ISSUES_BACKLOG.md

Files to update:
- INDEX.md

Requirements:
1. Add GITHUB_ISSUES_BACKLOG.md at the repository root.
2. Add a reference to GITHUB_ISSUES_BACKLOG.md inside INDEX.md.
3. Keep the document in English.
4. Do not create GitHub Issues yet.
5. Do not create a GitHub Projects board yet.
6. Commit changes with:
   Add GitHub issues backlog v0.1.7

Verification:
- Confirm git status is clean after commit.
- Confirm the new file exists in repository root.
- Confirm INDEX.md links to the new backlog file.
- Report final commit hash.
```
