#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 scripts/validate_vol9_phase9_4_static_prototype_evidence_pack.py
