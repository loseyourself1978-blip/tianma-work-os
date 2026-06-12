#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 scripts/validate_ai_board_cockpit_static_spec.py
