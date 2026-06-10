#!/usr/bin/env bash
# Gemma 4 local serving — macOS (Apple Silicon / Metal) via Ollama.
#
# Usage:
#   ml/serving/start_ollama.sh            # serve + pull gemma3n:e2b
#   GEMMA_VARIANT=e4b ml/serving/start_ollama.sh
#
# After this, set in .env:   LLM_BACKEND=ollama   (or leave LLM_BACKEND=auto on macOS)
set -euo pipefail

VARIANT="${GEMMA_VARIANT:-e2b}"
MODEL="${OLLAMA_MODEL:-gemma3n:${VARIANT}}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama not found. Install it:  brew install ollama   (or https://ollama.com/download)"
  exit 1
fi

# Start the server if it isn't already up (Ollama listens on :11434).
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "Starting Ollama server..."
  ollama serve >/tmp/ollama.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "Pulling ${MODEL} (first run downloads weights; subsequent runs are instant)..."
ollama pull "${MODEL}"

echo
echo "✅ Ollama serving '${MODEL}' on http://localhost:11434"
echo "   .env →  LLM_BACKEND=ollama   GEMMA_MODEL_VARIANT=${VARIANT}"
echo "   Verify: PYTHONPATH=. python ml/scripts/llm_healthcheck.py"
