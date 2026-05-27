# Project Memory and Index System v0.1

## Purpose

The Project Memory and Index System preserves continuity across conversations, documents, decisions, assets, tasks, reviews, and cross-project handoffs.

## Problem Statement

Long-running AI work creates structural problems: conversations become slow, decisions are buried, prior conclusions are hard to locate, AI may lose state, sessions become disconnected, and non-technical users do not understand context limits.

## First-Principles Analysis

The problem is not that conversations are long. The essence is that project knowledge is trapped in an unstable conversation stream.

Important knowledge must become durable, retrievable, structured project memory.

## Architecture

1. Visible Conversation Layer
2. Context Capture Layer
3. Background Compression Layer
4. Project Memory Layer
5. Project Index Layer
6. Asset Library Layer
7. Retrieval and Restoration Layer
8. Cross-Project Handoff Layer
9. Review and Improvement Layer

## Manual Prototype Protocol

Before full productization: use volume-based sessions, handoff summaries, INDEX.md, explicit document updates, and sync blocks between projects.

## Final Product Design

The final product should automatically detect long-context risk, summarize in the background, build searchable indexes, preserve visible chat continuity, restore project context on demand, maintain domain-specific state, resolve memory conflicts, and let users correct memory.

## Domain Memory Schemas

### Trading Project Schema

Market assumptions, portfolio state, historical positions, strategy positions, execution prices, source-of-truth hierarchy, risk limits, forecasts, review scores, action triggers.

### Product Project Schema

Product vision, roadmap, PRD, requirement pool, user feedback, decision log, asset library, MVP scope.
