#!/usr/bin/env bash
set -euo pipefail

python3 "$(dirname "$0")/validate_ldd_full_market_scope_governance_sync.py"
