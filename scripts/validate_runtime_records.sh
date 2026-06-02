#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Validates examples/ldd, examples/runtime, and records/ldd against local schemas.
python3 "${REPO_ROOT}/scripts/validate_runtime_records.py"
