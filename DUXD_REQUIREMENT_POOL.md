# DUXD Requirement Pool v0.1

## Purpose

This document tracks product requirements generated through DUXD.

## Current Requirement Pool

| ID | Requirement | Type | Priority | Status |
|---|---|---|---|---|
| DUXD-001 | Source-of-truth priority system | Core Infrastructure / Risk Control | High | Defined |
| DUXD-002 | Model disagreement visualization and final arbitration | AI Team Collaboration | High | Defined |
| DUXD-003 | Asset segmentation and state tracking | Asset Management / Domain Cockpit | High | Defined |
| DUXD-004 | Forecast review and scoring module | Review System | High | Defined |
| DUXD-005 | Mandatory Risk Officer role | AI Team / Risk Control | High | Defined |
| DUXD-006 | Long-context project memory and conversation index system | Project Memory | High | Defined |
| DUXD-007 | Program-level project index and cross-project handoff | Cross-Project System | High | Defined |
| DUXD-008 | Time-based session sharding / weekly volume system | Manual Prototype | Medium | Prototype |
| DUXD-009 | User-invisible background compression and indexing | Project Memory / UX | High | Defined |
| DUXD-010 | Domain-specific cockpit architecture | Domain Cockpit | High | Defined |
| DUXD-011 | Professional service-first execution design | Product Philosophy | High | Defined |
| DUXD-012 | Model-role fit optimization | AI Team Collaboration | High | Defined |
| DUXD-013 | Multi-account asset de-duplication system | Financial Cockpit | High | Proposed |
| DUXD-014 | First-principles problem-solving loop | Product Philosophy | High | Defined |
| DUXD-015 | Opposite Exposure Detector / Net Exposure Map | Financial Cockpit / Risk Control | High | Proposed |
| DUXD-016 | Leveraged ETF Decay Warning System | Financial Cockpit / Risk Control | High | Proposed |
| DUXD-017 | Position Intent Tagging System | Financial Cockpit / Asset Management | High | Proposed |

## Selected Definitions

### DUXD-013 — Multi-Account Asset De-Duplication System

Financial cockpits must distinguish spot, funding, bot/grid, futures, old-position, new-strategy, and total account views to avoid double counting.

### DUXD-015 — Opposite Exposure Detector / Net Exposure Map

Financial cockpits must detect conflicting long-short exposures, inverse products, leverage overlaps, and accidental hedges.

### DUXD-016 — Leveraged ETF Decay Warning System

Warn when leveraged or inverse ETFs are held too long, added to while losing, or used as long-term investments.

### DUXD-017 — Position Intent Tagging System

Every holding should be tagged by intent: new strategy, historical old position, hedge, legacy error, leverage-decay position, bot/grid position, cash/financing pressure position, or active opportunity.
