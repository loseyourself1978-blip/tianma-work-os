#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 scripts/validate_vol9_phase9_2_ldd_consumer_acknowledgement.py
