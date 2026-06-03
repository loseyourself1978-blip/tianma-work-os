#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Generates LDD runtime summaries, including memory-retention reports, from local records only.
python3 "${REPO_ROOT}/scripts/generate_runtime_report.py"
