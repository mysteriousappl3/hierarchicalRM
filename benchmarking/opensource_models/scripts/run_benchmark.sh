#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PATH="${VENV_PATH:-${MODEL_DIR}/.venv}"

source "${VENV_PATH}/bin/activate"
exec python "${MODEL_DIR}/run_open_source.py" "$@"
