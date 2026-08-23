#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PATH="${VENV_PATH:-${MODEL_DIR}/.venv}"
VLLM_CHANNEL="${VLLM_CHANNEL:-nightly}"

python3 -m venv "${VENV_PATH}"
source "${VENV_PATH}/bin/activate"
python -m pip install --upgrade pip uv

if [[ "${VLLM_CHANNEL}" == "nightly" ]]; then
  uv pip install vllm --torch-backend=auto --extra-index-url https://wheels.vllm.ai/nightly
elif [[ "${VLLM_CHANNEL}" == "stable" ]]; then
  uv pip install "vllm>=0.12.0"
else
  echo "VLLM_CHANNEL must be nightly or stable" >&2
  exit 2
fi

python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'devices', torch.cuda.device_count())"
vllm --version
