#!/usr/bin/env bash
set -euo pipefail

python3 "$(dirname "$0")/validate_vol6_handoff_readiness_gate.py"
