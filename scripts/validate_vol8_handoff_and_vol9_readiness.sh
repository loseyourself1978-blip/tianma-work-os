#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 scripts/validate_vol8_handoff_and_vol9_readiness.py
