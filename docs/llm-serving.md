# LLM Serving & Operations (Gemma 4 Agent 2)

> Agent 2 (the quant reasoner) runs on a local **Gemma 4 E2B** model behind a
> **pluggable backend layer** (vLLM / Ollama / external API). This is the deploy,
> config, and troubleshooting manual for that layer. For the LLM's role in the
> pipeline see [signal-pipeline.md](./signal-pipeline.md); for the overall system
> see [architecture.md](./architecture.md).

## English

### 1. Design — harness decoupled from transport

```
ml/inference/
├── gemma_agent.py        Agent 1 (assemble, no LLM) + Agent 2 (reason: retry/validate/fallback)
└── llm/
    ├── base.py           LLMBackend ABC: chat(messages, schema)->dict, health()
    ├── vllm_backend.py    OpenAI /v1/chat/completions + guided json_schema
    ├── ollama_backend.py  /api/chat + structured `format` schema
    ├── api_backend.py     external OpenAI-compatible endpoint (plug-in seam)
    └── factory.py         get_llm_backend() — select by LLM_BACKEND / platform
```

The **agent harness is backend-agnostic**: `GemmaAgent` only does "assemble
context → call backend → validate → retry → fall back"; a backend is pure
transport (one call). Swapping backends is a config change, never a logic change.

**Graceful degrade:** when the LLM is unavailable, `signal_engine._fallback_gemma_output()`
returns an ML-only signal. **Serving is additive, never load-bearing** — if the
model is down the system still emits signals (just without LLM attribution text).

### 2. Model

Gemma 4 (Google DeepMind, 2026-03-31, Apache 2.0). E2B/E4B are *effective*
parameter sizes (edge/on-device, 128K context, day-one Ollama + vLLM + HF support).

| Backend | E2B | E4B |
|---------|-----|-----|
| Ollama | `gemma4:e2b` | `gemma4:e4b` |
| HF / vLLM (instruction-tuned) | `google/gemma-4-E2B-it` | `google/gemma-4-E4B-it` |

**E2B now; flip to E4B later** = change one line `GEMMA_MODEL_VARIANT=e4b`; the
config derives the per-backend id automatically.

### 3. Backend selection

`LLM_BACKEND` (default `auto`):

| Value | Behaviour |
|-------|-----------|
| `auto` | macOS → `ollama`; otherwise (Windows/Linux GPU) → `vllm` |
| `ollama` | force Ollama (`OLLAMA_BASE_URL`, default `http://localhost:11434`) |
| `vllm` | force vLLM (`VLLM_BASE_URL`, default `http://localhost:8080/v1`) |
| `api` | external OpenAI-compatible endpoint (`GEMMA_API_URL` + `GEMMA_API_KEY`) |

> ⚠️ Inside a container `auto` detects Linux → picks `vllm`. To use an Ollama
> service from a container you **must set `LLM_BACKEND=ollama` explicitly**
> (docker-compose already does this for `ml_worker`).

### 4. Local serving

**macOS — Ollama (Metal-accelerated, recommended for Mac dev)**
```bash
brew install ollama            # if needed
make gemma-serve               # start server + pull gemma4:e2b (~7.2GB first run)
make gemma-check               # end-to-end verify + JSON schema
```
`.env`: `LLM_BACKEND=auto` (or `ollama`).

**Windows / Linux GPU — vLLM**
```bash
pip install vllm               # heavy, CUDA-specific; GPU host only (not in requirements.txt)
ml/serving/start_vllm.sh       # Linux, :8080
# Windows: ./ml/serving/start_vllm.ps1   (native vLLM is most stable via WSL2)
make gemma-check
```

### 5. Docker deployment — standalone `gemma` service

In docker-compose, Gemma is a **standalone service** (`ollama/ollama` image). On
first boot it auto-pulls the model into the `ollama_models` volume and exposes it
on the compose network at `http://gemma:11434`.

```yaml
gemma:
  image: ollama/ollama:latest
  volumes: [ollama_models:/root/.ollama]
  environment:
    - GEMMA_PULL_MODEL=${GEMMA_PULL_MODEL:-gemma4:e2b}
  # entrypoint: ollama pull on first boot, then serve
```

`ml_worker` is wired up: `LLM_BACKEND=ollama` + `OLLAMA_BASE_URL=http://gemma:11434`,
`depends_on: gemma` (`service_started`, non-blocking — the worker starts and
degrades while the model is still pulling).

**Platform differences (important)**

| Host | Containerized Ollama GPU? | Recommendation |
|------|---------------------------|----------------|
| **macOS** (Docker Desktop) | ❌ no Metal passthrough — CPU-only (slow) | Use **native** Ollama (`make gemma-serve`); point the worker at `host.docker.internal` (below) |
| **Linux** + nvidia-container-toolkit | ✅ uncomment the `deploy:` GPU block in compose | Use the compose `gemma` service directly |

**Mac: let the dockerized worker reach native Ollama** — in `.env`:
```ini
OLLAMA_BASE_URL=http://host.docker.internal:11434
```
then you can skip the compose `gemma` service (it's only a CPU fallback on Mac).

**Pull / debug models**
```bash
docker compose exec gemma ollama list                 # list pulled models
docker compose exec gemma ollama pull gemma4:e2b      # pull / swap manually
# The gemma port is not published to the host by default; to run gemma-check
# from the host, uncomment the `ports:` mapping in compose.
```

### 6. Configuration (`.env`)

| Variable | Default | Notes |
|----------|---------|-------|
| `LLM_BACKEND` | `auto` | `auto`/`vllm`/`ollama`/`api` |
| `GEMMA_MODEL_VARIANT` | `e2b` | `e2b`/`e4b` — switch size here only |
| `GEMMA_TEMPERATURE` | `0.1` | near-deterministic financial reasoning |
| `GEMMA_MAX_TOKENS` | `512` | output cap |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | (blank, derived from variant) | override for a custom/finetuned tag |
| `VLLM_BASE_URL` | `http://localhost:8080/v1` | vLLM endpoint |
| `VLLM_MODEL` | (blank, derived from variant) | HF id or local checkpoint path |
| `GEMMA_API_URL` / `GEMMA_API_KEY` / `GEMMA_API_MODEL` | blank | only when `LLM_BACKEND=api` |

### 7. Structured output (JSON schema lock)

Each backend constrains output to `AGENT2_OUTPUT_SCHEMA` its own way:
- **vLLM**: `response_format: {type: json_schema}` + guided decoding (`--guided-decoding-backend xgrammar`)
- **Ollama**: pass the JSON Schema object directly as `format`
- **API**: `response_format: json_schema` (falls back to `json_object` with no schema)

`gemma_agent._validate_output()` adds a defensive second pass (enum correction,
confidence clamp, field truncation) so an occasional out-of-bounds output never crashes.

### 8. Finetuning (serve-time seams — already in place, no code change)

- **Ollama (Mac)**: export a LoRA/GGUF adapter → wire it into the `ADAPTER` line of
  `ml/serving/Modelfile.gemma` → `ollama create penguinai-gemma -f ml/serving/Modelfile.gemma`
  → set `OLLAMA_MODEL=penguinai-gemma`.
- **vLLM (Win/Linux)**: serve a merged checkpoint (`VLLM_MODEL=/path/ckpt`) or a
  LoRA adapter (`start_vllm.sh` with `LORA_PATH=...` → `VLLM_MODEL=gemma-ft`).

The Agent 2 system prompt is sent per request from code
(`gemma_agent.py:AGENT2_SYSTEM_PROMPT`), shared across base and finetuned models —
it is intentionally not baked into the Modelfile.

### 9. Concurrency & performance

- `refresh_top100` runs 10 tickers per batch concurrently, 100/hour.
- Ollama default concurrency is limited; compose sets `OLLAMA_NUM_PARALLEL=4` and
  `OLLAMA_KEEP_ALIVE=24h` to avoid repeated model load/unload.
- vLLM has continuous batching — better under high concurrency.
- Timeouts: Ollama 120s / vLLM 60s (`*_backend.py`); tune as needed.

### 10. Troubleshooting

| Symptom | Check |
|---------|-------|
| Signal `ai_analysis` shows "LLM reasoning unavailable" | LLM not connected → fell back. Run `make gemma-check` |
| `reachable: False` | Server not up / wrong URL / `auto` picked wrong backend in container |
| Container can't reach native Ollama | Use `host.docker.internal` in `.env`; check Docker Desktop version |
| JSON parse fails, repeated retries | Schema constraint not active (vLLM missing guided-decoding backend / too old) |
| Containerized Ollama very slow on Mac | Expected (no GPU passthrough) → use native Ollama |

**One-line verify**: `make gemma-check` — pings the backend, then runs the full
Agent 2 harness on a synthetic bullish context and prints the schema-locked JSON.
Exit 0 = end-to-end OK.

### Related files

```
ml/inference/llm/            backend layer (base/vllm/ollama/api/factory)
ml/inference/gemma_agent.py  Agent 1 + Agent 2 harness
ml/core/config.py            MLSettings: LLM_BACKEND / GEMMA_MODEL_VARIANT / *_model()
ml/serving/                  start_ollama.sh / start_vllm.{sh,ps1} / Modelfile.gemma / README.md
ml/scripts/llm_healthcheck.py  implementation behind `make gemma-check`
docker-compose.yml           gemma service + ml_worker wiring
```

---

## 中文

### 1. 设计:harness 与 transport 解耦

```
ml/inference/
├── gemma_agent.py        Agent 1(纯组装,无 LLM) + Agent 2(推理:retry/校验/降级)
└── llm/
    ├── base.py           LLMBackend ABC: chat(messages, schema)->dict, health()
    ├── vllm_backend.py    OpenAI /v1/chat/completions + guided json_schema
    ├── ollama_backend.py  /api/chat + 结构化 format schema
    ├── api_backend.py     外部 OpenAI 兼容端点(预留)
    └── factory.py         get_llm_backend() — 按 LLM_BACKEND / 平台自选
```

**Agent harness 与具体后端无关**:`GemmaAgent` 只负责「组装上下文 → 调 backend →
校验 → 重试 → 失败降级」;backend 只是一次纯传输调用。换后端 = 改配置,不动推理逻辑。

**优雅降级**:LLM 不可用时,`signal_engine._fallback_gemma_output()` 退化为 ML-only
信号。**serving 是增量,永远不是承重件** —— 模型挂了,系统仍出信号(只是没有 LLM 文字归因)。

### 2. 模型

Gemma 4(Google DeepMind,2026-03-31,Apache 2.0)。E2B/E4B 是 *effective*
参数量(边缘/端侧,128K 上下文,day-one 支持 Ollama + vLLM + HF)。

| 后端 | E2B | E4B |
|------|-----|-----|
| Ollama | `gemma4:e2b` | `gemma4:e4b` |
| HF / vLLM(instruction-tuned) | `google/gemma-4-E2B-it` | `google/gemma-4-E4B-it` |

**当前用 E2B,以后切 E4B** = 改一行 `GEMMA_MODEL_VARIANT=e4b`,配置自动派生各后端 id。

### 3. 后端选择

`LLM_BACKEND`(默认 `auto`):

| 值 | 行为 |
|----|------|
| `auto` | macOS → `ollama`;其它(Windows/Linux GPU)→ `vllm` |
| `ollama` | 强制 Ollama(`OLLAMA_BASE_URL`,默认 `http://localhost:11434`) |
| `vllm` | 强制 vLLM(`VLLM_BASE_URL`,默认 `http://localhost:8080/v1`) |
| `api` | 外部 OpenAI 兼容端点(`GEMMA_API_URL` + `GEMMA_API_KEY`) |

> ⚠️ 在容器内 `auto` 会探测到 Linux → 选 `vllm`。若容器里要用 Ollama 服务,
> **必须显式设 `LLM_BACKEND=ollama`**(docker-compose 已为 `ml_worker` 设好)。

### 4. 本地起服务

**macOS — Ollama(Metal 加速,推荐 Mac 开发)**
```bash
brew install ollama            # 如未安装
make gemma-serve               # 起服务 + 拉 gemma4:e2b(首次 ~7.2GB)
make gemma-check               # 端到端验证 + JSON schema
```
`.env`:`LLM_BACKEND=auto`(或 `ollama`)即可。

**Windows / Linux GPU — vLLM**
```bash
pip install vllm               # 重、CUDA 相关,只在 GPU host 装(不在 requirements.txt)
ml/serving/start_vllm.sh       # Linux,:8080
# Windows: ./ml/serving/start_vllm.ps1   (原生 vLLM 走 WSL2 更稳)
make gemma-check
```

### 5. Docker 部署:独立 `gemma` 服务

docker-compose 中 Gemma 是**独立 service**(`ollama/ollama` 镜像),首次启动自动
把模型拉进 `ollama_models` volume,在 compose 网络上以 `http://gemma:11434` 暴露。

```yaml
gemma:
  image: ollama/ollama:latest
  volumes: [ollama_models:/root/.ollama]
  environment:
    - GEMMA_PULL_MODEL=${GEMMA_PULL_MODEL:-gemma4:e2b}
  # entrypoint:首启 ollama pull,然后 serve
```

`ml_worker` 已接线:`LLM_BACKEND=ollama` + `OLLAMA_BASE_URL=http://gemma:11434`,
`depends_on: gemma`(`service_started`,非阻塞 —— 模型还在拉时 worker 照常启动并降级)。

**平台差异(重要)**

| 宿主 | 容器化 Ollama 能否用 GPU | 建议 |
|------|--------------------------|------|
| **macOS**(Docker Desktop) | ❌ 无 Metal 透传,容器内纯 CPU(慢) | 用**原生** Ollama(`make gemma-serve`),worker 指 `host.docker.internal`(见下) |
| **Linux** + nvidia-container-toolkit | ✅ 取消 compose 里 `deploy:` GPU 块 | 直接用 compose 的 `gemma` 服务 |

**Mac 上让 docker 的 worker 连原生 Ollama**,`.env`:
```ini
OLLAMA_BASE_URL=http://host.docker.internal:11434
```
然后可跳过 compose 的 `gemma` 服务(它在 Mac 上只是 CPU 兜底)。

**拉模型 / 调试**
```bash
docker compose exec gemma ollama list                 # 查已拉模型
docker compose exec gemma ollama pull gemma4:e2b      # 手动拉/换模型
# 默认 gemma 端口不发布到宿主;要从宿主跑 gemma-check,取消 compose 里 ports 注释
```

### 6. 配置项(`.env`)

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_BACKEND` | `auto` | `auto`/`vllm`/`ollama`/`api` |
| `GEMMA_MODEL_VARIANT` | `e2b` | `e2b`/`e4b` —— 切档只改这里 |
| `GEMMA_TEMPERATURE` | `0.1` | 近确定性金融推理 |
| `GEMMA_MAX_TOKENS` | `512` | 输出上限 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 端点 |
| `OLLAMA_MODEL` | (空,按 variant 派生) | 覆盖为自定义/finetune tag |
| `VLLM_BASE_URL` | `http://localhost:8080/v1` | vLLM 端点 |
| `VLLM_MODEL` | (空,按 variant 派生) | HF id 或本地 checkpoint 路径 |
| `GEMMA_API_URL` / `GEMMA_API_KEY` / `GEMMA_API_MODEL` | 空 | 仅 `LLM_BACKEND=api` 时用 |

### 7. 结构化输出(JSON schema 锁定)

每个后端用各自方式强约束输出符合 `AGENT2_OUTPUT_SCHEMA`:
- **vLLM**:`response_format: {type: json_schema}` + guided decoding(`--guided-decoding-backend xgrammar`)
- **Ollama**:`format` 直接传 JSON Schema 对象
- **API**:`response_format: json_schema`(无 schema 时退 `json_object`)

`gemma_agent._validate_output()` 再做一层兜底校验(枚举纠偏、confidence 钳位、字段截断),
即使模型偶发越界也不会崩。

### 8. Finetune(serve-time seam,已留好,无需改代码)

- **Ollama(Mac)**:导出 LoRA/GGUF adapter → 写进 `ml/serving/Modelfile.gemma`
  的 `ADAPTER` 行 → `ollama create penguinai-gemma -f ml/serving/Modelfile.gemma`
  → `.env` 设 `OLLAMA_MODEL=penguinai-gemma`。
- **vLLM(Win/Linux)**:merged checkpoint(`VLLM_MODEL=/path/ckpt`)或 LoRA
  (`start_vllm.sh` 带 `LORA_PATH=...` → `VLLM_MODEL=gemma-ft`)。

Agent 2 system prompt 在代码里按请求下发(`gemma_agent.py:AGENT2_SYSTEM_PROMPT`),
base / finetune 共用一处,不写进 Modelfile。

### 9. 并发与性能

- `refresh_top100` 每批 10 个 ticker 并发调 LLM,100 个/小时。
- Ollama 默认并发有限,已在 compose 设 `OLLAMA_NUM_PARALLEL=4`;`OLLAMA_KEEP_ALIVE=24h` 避免反复换入换出。
- vLLM 自带 continuous batching,高并发更优。
- 超时:Ollama 120s / vLLM 60s(`*_backend.py`),按需调。

### 10. 排障

| 现象 | 排查 |
|------|------|
| 信号 `ai_analysis` 显示 "LLM reasoning unavailable" | LLM 没连上 → 走了 fallback。跑 `make gemma-check` |
| `reachable: False` | 服务没起 / URL 不对 / 容器内 `auto` 选错后端 |
| 容器内连不上原生 Ollama | `.env` 用 `host.docker.internal`,确认 Docker Desktop 版本支持 |
| JSON 解析失败反复重试 | 后端 schema 约束未生效(vLLM 缺 guided-decoding 后端 / 版本过旧) |
| Mac 容器 Ollama 巨慢 | 预期(无 GPU 透传)→ 改用原生 Ollama |

**一句话验证**:`make gemma-check` —— ping 后端 + 用合成 bullish 上下文跑完整
Agent 2,打印 schema 锁定的 JSON。exit 0 即端到端通。

### 关联文件

```
ml/inference/llm/            backend 层(base/vllm/ollama/api/factory)
ml/inference/gemma_agent.py  Agent 1 + Agent 2 harness
ml/core/config.py            MLSettings:LLM_BACKEND / GEMMA_MODEL_VARIANT / *_model()
ml/serving/                  start_ollama.sh / start_vllm.{sh,ps1} / Modelfile.gemma / README.md
ml/scripts/llm_healthcheck.py  make gemma-check 的实现
docker-compose.yml           gemma 服务 + ml_worker 接线
```
