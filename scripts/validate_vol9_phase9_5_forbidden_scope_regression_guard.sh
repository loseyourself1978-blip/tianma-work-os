#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 scripts/validate_vol9_phase9_5_forbidden_scope_regression_guard.py
