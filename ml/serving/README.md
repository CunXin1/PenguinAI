# Gemma 4 Local Serving (LLM MVP)

The Agent 2 reasoner runs on a **local Gemma 4 E2B** model behind a swappable
backend. One model, three transports — picked by `LLM_BACKEND` (default `auto`):

| Platform | Backend | Server | Default model |
|----------|---------|--------|---------------|
| macOS (Apple Silicon) | `ollama` | Ollama `:11434` | `gemma4:e2b` |
| Windows / Linux (NVIDIA GPU) | `vllm` | vLLM `:8080` | `google/gemma-4-E2B-it` |
| Hosted (future) | `api` | any OpenAI-compatible | `gemma-4` |

`auto` → Ollama on macOS, vLLM elsewhere. The whole pipeline already degrades to
an ML-only signal if the LLM is down (`signal_engine._fallback_gemma_output`), so
serving is additive, never load-bearing.

> **Model.** Gemma 4 (released 2026-03-31, Apache 2.0). E2B/E4B = *effective*
> parameter sizing for edge/on-device; 128K context, day-one Ollama + vLLM + HF.
> Defaults: `gemma4:e2b` (Ollama) / `google/gemma-4-E2B-it` (HF/vLLM). Override
> `OLLAMA_MODEL` / `VLLM_MODEL` for a quant or finetune — no code change.
> **E2B now; E4B later** = flip `GEMMA_MODEL_VARIANT=e4b` (or pass `-Variant e4b`
> / `GEMMA_VARIANT=e4b`).

## macOS — Ollama

```bash
brew install ollama            # if needed
ml/serving/start_ollama.sh     # starts server + pulls gemma4:e2b
```
`.env`: leave `LLM_BACKEND=auto` (or set `ollama`).

## Windows — vLLM

```powershell
pip install vllm               # heavy, CUDA-specific — install on the GPU host only
./ml/serving/start_vllm.ps1    # serves google/gemma-4-E2B-it on :8080
```
`.env`: leave `LLM_BACKEND=auto` (or set `vllm`).

## Linux GPU (4090 box) — vLLM

```bash
pip install vllm
ml/serving/start_vllm.sh
```

## Verify

```bash
PYTHONPATH=. python ml/scripts/llm_healthcheck.py
```
Pings the backend, then runs the full Agent 2 harness on a synthetic bullish
context and prints the schema-locked JSON. Exit 0 = end-to-end OK.

## External API (the plug-in seam)

```ini
LLM_BACKEND=api
GEMMA_API_URL=https://your-endpoint/v1
GEMMA_API_KEY=...
GEMMA_API_MODEL=gemma-4
```
Any OpenAI-compatible endpoint (Vertex AI, a gateway, a managed host). Swapping
providers is config-only — see `ml/inference/llm/api_backend.py`.

## Finetuning (future) — serve-time seams already in place

Both local backends can serve a finetuned model with **no code change**:

- **Ollama (macOS):** export a LoRA/GGUF adapter, wire it in
  `ml/serving/Modelfile.gemma` (`ADAPTER` line), then
  `ollama create penguinai-gemma -f ml/serving/Modelfile.gemma` and set
  `OLLAMA_MODEL=penguinai-gemma`.
- **vLLM (Win/Linux):** serve a merged checkpoint (`VLLM_MODEL=/path/to/ckpt`)
  or a LoRA adapter (`start_vllm.sh` with `LORA_PATH=...` → `VLLM_MODEL=gemma-ft`).

The Agent 2 system prompt is assembled in code
(`ml/inference/gemma_agent.py:AGENT2_SYSTEM_PROMPT`) and sent per request, so it
stays in one place across base and finetuned models.

## Architecture

```
ml/inference/
├── gemma_agent.py        Agent 1 (assemble, no LLM) + Agent 2 (reason: retry/validate/fallback)
└── llm/
    ├── base.py           LLMBackend ABC: chat(messages, schema) -> dict, health()
    ├── vllm_backend.py    OpenAI /v1/chat/completions + guided json_schema
    ├── ollama_backend.py  /api/chat + structured `format` schema
    ├── api_backend.py     hosted OpenAI-compatible (future plug-in)
    └── factory.py         get_llm_backend() — auto-select by platform
```
The agent harness is backend-agnostic; backends are pure transport.
