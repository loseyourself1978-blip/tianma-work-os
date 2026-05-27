# LLM Daredevil Desk Cockpit Spec v0.1

## Purpose

This document defines the initial LDD financial cockpit for Tianma Work OS.

## Account Layer Model

- New Strategy Book
- Historical Old-Position Management
- Robot / Automated-Strategy Positions
- Total Real-Account Exposure

## Required Cockpit Sections

1. Review Header
2. Account State
3. Position Segmentation
4. Source-of-Truth Price Status
5. Market State Summary
6. Strategy Judgment
7. Operation Plan
8. Risk Officer Block
9. Forecast Review Block
10. DUXD Feedback Block
11. Net Exposure Map
12. Opposite Exposure Detector
13. Leveraged ETF Decay Warning
14. Position Intent Tagging

## Position Intent Tags

```text
NEW_STRATEGY
HISTORICAL_OLD_POSITION
HEDGE
LEGACY_ERROR
LEVERAGE_DECAY_POSITION
BOT_GRID_POSITION
CASH_FINANCING_PRESSURE
ACTIVE_OPPORTUNITY
```

## Next Required Action Tags

```text
ATTACK
HOLD
DE_RISK
CLEAN_UP
WATCH
WAIT_FOR_CONFIRMATION
```

## Current LDD Memory Rules

1. User platform prices are execution source of truth.
2. External data is used for context and cross-checking.
3. New strategy book must be separated from historical old positions.
4. Robot/grid positions must be tracked separately.
5. Total real-account exposure is for risk management, not strategy performance.
6. Do not add to losing leveraged positions.
7. Avoid long-term holding of 3x inverse ETFs.
8. Forecasts must be reviewed and scored.
9. Every LDD review should output a sync block.
10. Every holding should be tagged by intent.
