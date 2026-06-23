#!/usr/bin/env bash
# Ensure a native, Metal-accelerated Ollama is serving on the host before the
# Docker stack comes up, so the LLM chat agent (api container → host.docker.
# internal:11434) has a backend.
#
# Why native and not a container: Docker Desktop on macOS has no GPU passthrough,
# so a containerised Ollama would be CPU-only, and the image's bundled Ollama is
# too old for Gemma 4 (HTTP 412). On Linux/GPU hosts use the compose
# `container-llm` profile instead — this script is a macOS-only no-op elsewhere.
#
# Idempotent and non-fatal by design: if Ollama is already up it does nothing,
# and any failure (not installed, won't start, pull fails) only logs a warning
# and exits 0 so `make up` still brings up the rest of the stack. Chat is the
# only feature that degrades.
set -uo pipefail

# Native host Ollama only matters on macOS; bail cleanly everywhere else.
[ "$(uname -s)" = "Darwin" ] || exit 0

OLLAMA_URL="${OLLAMA_PROBE_URL:-http://localhost:11434}"

# Pick up OLLAMA_MODEL / GEMMA_VARIANT from .env when not already exported, so the
# model this script ensures matches what the api/ml_worker containers resolve
# (they read the same .env via compose env_file). Shell env still wins over .env.
_ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env"
if [ -f "$_ENV_FILE" ]; then
  for _k in OLLAMA_MODEL GEMMA_VARIANT; do
    if [ -z "${!_k:-}" ]; then
      _v="$(grep -E "^${_k}=" "$_ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r')"
      [ -n "$_v" ] && export "$_k=$_v"
    fi
  done
fi

# Mirror ml/serving/start_ollama.sh + ml.core.config.ollama_model() defaults.
MODEL="${OLLAMA_MODEL:-gemma4:${GEMMA_VARIANT:-e2b}}"

probe() { curl -fsS -m 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; }

if probe; then
  echo "✓ Ollama already serving on $OLLAMA_URL"
else
  if ! command -v ollama >/dev/null 2>&1; then
    echo "⚠ ollama not installed (brew install ollama) — chat agent will be degraded"
    exit 0
  fi
  echo "Starting native Ollama (Metal) ..."
  OLLAMA_KEEP_ALIVE=24h nohup ollama serve >/tmp/ollama.log 2>&1 &
  for _ in $(seq 1 30); do
    probe && break
    sleep 1
  done
  if ! probe; then
    echo "⚠ Ollama did not come up within 30s — see /tmp/ollama.log; chat agent will be degraded"
    exit 0
  fi
  echo "✓ Ollama serving on $OLLAMA_URL"
fi

# Ensure the chat model is present. Don't block the stack if the pull fails.
if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$MODEL"; then
  echo "✓ chat model ready: $MODEL"
else
  echo "Pulling $MODEL (first run downloads weights) ..."
  if ollama pull "$MODEL"; then
    echo "✓ chat model ready: $MODEL"
  else
    echo "⚠ could not pull $MODEL — chat agent will be degraded until it is available"
  fi
fi
