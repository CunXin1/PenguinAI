#!/usr/bin/env bash
# Gemma 4 local serving — Linux (NVIDIA GPU, e.g. the RTX 4090 box) via vLLM.
#
# Prereqs: CUDA-capable GPU. Install vLLM into your env first:
#     pip install vllm
# (vLLM is intentionally NOT in ml/requirements.txt — heavy + CUDA-specific.
#  Install it only on the serving host.)
#
# Usage:
#   ml/serving/start_vllm.sh                       # google/gemma-4-E2B-it on :8080
#   GEMMA_VARIANT=e4b ml/serving/start_vllm.sh
#   VLLM_MODEL=/models/gemma-ft ml/serving/start_vllm.sh   # finetuned/merged checkpoint
#   LORA_PATH=/models/lora-adapter ml/serving/start_vllm.sh
#
# After this, set in .env:   LLM_BACKEND=vllm   (or leave LLM_BACKEND=auto on Linux)
set -euo pipefail

VARIANT="${GEMMA_VARIANT:-e2b}"
PORT="${PORT:-8080}"
VARIANT_UPPER="$(echo "$VARIANT" | tr '[:lower:]' '[:upper:]')"
MODEL="${VLLM_MODEL:-google/gemma-4-${VARIANT_UPPER}-it}"

if ! command -v vllm >/dev/null 2>&1; then
  echo "vLLM not found. Install on this GPU host:  pip install vllm"
  exit 1
fi

ARGS=(serve "$MODEL" --port "$PORT" --served-model-name "$MODEL"
      --guided-decoding-backend xgrammar)

if [[ -n "${LORA_PATH:-}" ]]; then
  ARGS+=(--enable-lora --lora-modules "gemma-ft=${LORA_PATH}")
  echo "LoRA enabled: adapter 'gemma-ft' from ${LORA_PATH} (set VLLM_MODEL=gemma-ft in .env)"
fi

echo "Starting vLLM: ${MODEL} on http://localhost:${PORT}/v1"
echo "  .env →  LLM_BACKEND=vllm  GEMMA_MODEL_VARIANT=${VARIANT}  VLLM_BASE_URL=http://localhost:${PORT}/v1"
echo "  Verify: PYTHONPATH=. python ml/scripts/llm_healthcheck.py"

exec vllm "${ARGS[@]}"
