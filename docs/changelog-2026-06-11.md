# Changelog — 2026-06-11

A single session that (1) got the full Docker stack actually running on macOS,
(2) fixed the signal output, and (3) built the LLM Chat Agent end-to-end. This is
the work log; the chat agent has its own reference in `docs/llm-chat-agent.md`.

## English

### 1. Docker stack: workers and realtime were not running

Symptom: data was not updating and signals were not refreshing. Root cause was not
one bug but a chain.

- Only 5 of 10 compose services were up (`api`, `frontend`, `nginx`, `redis`,
  `timescaledb`). The schedulers/workers were never in any dependency chain, so
  `docker compose up -d nginx` only pulled those 5. Fix: added `celery_beat`,
  `celery_worker`, `ml_worker` to the `api` service `depends_on`, so starting the
  API brings up the whole backend.
- The ML image (`ml/Dockerfile`, shared by the workers) could not build on Apple
  Silicon at all:
  - `torch==2.5.1+cu124` is a CUDA wheel that does not exist for ARM. Fix: torch is
    now installed in the Dockerfile via build args (`TORCH_SPEC` / `TORCH_INDEX_URL`)
    defaulting to CPU wheels; a GPU host overrides them to cu124.
  - `pandas==3.0.3` (a dependabot bump) conflicts with `mlflow 3.13` (`pandas<3`).
    Fix: pinned `pandas==2.2.3`.
  - `pandas-ta==0.3.14b0` was yanked from PyPI and is never imported by any code
    (features are computed in numpy / the `indicators_30min` SQL view). Removed.
  - `playwright install --with-deps` failed on Debian-arm64 (Ubuntu-only font
    packages). Fix: fall back to a browser-only install so the image still builds.
- Realtime ingestion was gated off (`REALTIME_ENABLED=false`). Enabled it on the
  `api` service with `IBKR_HOST=host.docker.internal`. Finnhub WS + Massive now run
  inside the container; IBKR degrades gracefully if no host TWS is present.
- The `scraper` service crash-looped because `data.scrapers.runner` does not exist
  yet (the Twitter/Reddit scrapers are stubs). Commented it out (and removed it from
  `depends_on`) until the runner is built.
- Trained model pickles live on the host (`./models/penguinai/`) but were not mounted
  into the worker, so signals fell back to NEUTRAL "models not available". Fix:
  mount `./models:/app/models` on `ml_worker`.
- nginx used `upstream { server api:8000; }`, which resolves the IP once at config
  load and caches it forever; recreating `api` (new IP) stranded nginx -> 502. Fix:
  use Docker's embedded DNS resolver (`127.0.0.11`) with a variable `proxy_pass` so
  upstreams re-resolve at request time. Verified: recreating `api` self-heals.

Operational note: on a laptop, Docker pauses when the machine sleeps, so Celery beat
stops scheduling and catches up on wake. A run of "all signals expired" turned out
to be the Mac sleeping, not a defect.

### 2. Gemma 4 serving on macOS (host Ollama, not the container)

The bundled `ollama/ollama` image was too old to pull Gemma 4 (HTTP 412). Per the
compose comments, macOS should use the host's native Ollama (Metal) anyway. So:

- `.env`: `LLM_BACKEND=ollama`, `OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- The `gemma` container is now behind a compose profile (`container-llm`) and off by
  default; the backend/workers talk to the host Ollama (which already serves
  `gemma4:e2b`). Enable the profile only on a Linux/GPU host.

Gemma 4 is a reasoning model: the request must send `"think": false`, or the
thinking phase consumes the whole token budget and the content comes back empty
(HTTP 200, `done_reason: length`). Applied in `ollama_backend.py` and
`backend/app/services/chat_llm.py`.

### 3. Signal output: every ticker was NEUTRAL at 55%

The ML models were producing varied probabilities (ensemble 0.35-0.58), but Agent 2
(Gemma) was misreading them — it described `ensemble_prob_up=0.38` (clearly bearish)
as "slightly upward" and defaulted everything to NEUTRAL with a flat 0.55 confidence.

Fix: rewrote the Agent 2 system prompt (`ml/inference/gemma_agent.py`) to state the
input semantics explicitly — `*_prob_up` is P(price rises), so `<0.5` is bearish and
the distance from 0.5 is the strength — and to let the ensemble lead direction with
confidence that scales with the evidence. Result: differentiated signals
(SHORT/NEUTRAL/LONG, confidence 0.50-0.95) instead of a flat wall of NEUTRAL 55%.

### 4. LLM Chat Agent (the major feature)

Built the per-user, tool-calling assistant end-to-end with Gemma 4 and SSE token
streaming. Full reference: `docs/llm-chat-agent.md`. In brief:

- Database: `chat_conversations` + `chat_messages` (per-user history, cascade delete).
- ML: implemented tool-calling on the Ollama backend (`chat_tools` + streaming
  `chat_tools_stream`); confirmed Ollama 0.22.1 parses Gemma 4 tool calls reliably
  (CLAUDE.md's "use vLLM, Ollama parser is buggy" note is outdated). Added a
  streaming `ChatAgent.chat_stream` loop and matching `chat_tools_stream` on the
  vLLM backend.
- Backend: conversation CRUD + a non-streaming and an SSE streaming send endpoint,
  with quota metering, transactional persistence, and refund-on-failure.
- Frontend: rewrote `app/chat/page.tsx` from a localStorage stub into a server-backed
  chat with a conversation sidebar, tool-usage chips, and live token streaming.
- Security verified: cross-user access to another user's conversation returns 404;
  `user_id` is server-side only.

### Files changed (high level)

```
docker-compose.yml                 depends_on, realtime, scraper, models mount, gemma profile, torch build-args
ml/Dockerfile                      CPU-default torch build-args, playwright fallback
ml/requirements.txt                torch moved to Dockerfile, pandas 2.2.3, pandas-ta removed
nginx/nginx.conf                   Docker resolver + variable proxy_pass
.env                               LLM_BACKEND=ollama, OLLAMA_BASE_URL=host.docker.internal, REALTIME_ENABLED, IBKR_HOST
ml/inference/gemma_agent.py        Agent 2 prompt rewrite (probability semantics)
ml/inference/llm/ollama_backend.py think:false, chat_tools, chat_tools_stream, message normalization
ml/inference/llm/vllm_backend.py   chat_tools_stream (OpenAI SSE)
ml/inference/chat/agent.py         chat_stream (streaming tool loop)
db/schema/03_relational.sql        chat_conversations + chat_messages
backend/app/models/chat.py         SQLAlchemy models (new)
backend/app/schemas/chat.py        conversation/message schemas
backend/app/api/routes/chat.py     conversation + streaming endpoints
backend/app/services/chat_agent.py ML agent bridge (new)
backend/app/services/chat_llm.py   think:false
frontend/src/app/chat/page.tsx     server-backed chat + streaming UI
frontend/src/lib/api.ts            conversation + sendMessageStream client
frontend/src/lib/types.ts          Conversation / StoredMessage / SendMessageReply
```

## 中文

### 1. Docker 栈:worker 和实时采集根本没启动

现象:数据不更新、信号不刷新。根因不是单个 bug,而是一连串问题。

- 10 个 compose 服务只起了 5 个(`api`、`frontend`、`nginx`、`redis`、
  `timescaledb`)。调度器/worker 不在任何依赖链里,所以 `docker compose up -d nginx`
  只拉起这 5 个。修复:把 `celery_beat`、`celery_worker`、`ml_worker` 加进 `api` 的
  `depends_on`,起 API 就带起整个后端。
- ML 镜像(`ml/Dockerfile`,worker 共用)在 Apple Silicon 上根本 build 不出来:
  - `torch==2.5.1+cu124` 是 CUDA wheel,ARM 上不存在。修复:torch 改由 Dockerfile
    用 build 参数(`TORCH_SPEC` / `TORCH_INDEX_URL`)安装,默认 CPU 版;GPU 主机覆盖
    为 cu124。
  - `pandas==3.0.3`(dependabot 自动 bump)与 `mlflow 3.13`(要求 `pandas<3`)冲突。
    修复:钉 `pandas==2.2.3`。
  - `pandas-ta==0.3.14b0` 已从 PyPI 撤掉,且任何代码都没 import(特征用 numpy /
    `indicators_30min` SQL 视图算)。删除。
  - `playwright install --with-deps` 在 Debian-arm64 上失败(Ubuntu 专属字体包)。
    修复:回退到只装浏览器二进制,镜像照样 build。
- 实时采集被 `REALTIME_ENABLED=false` 关掉。在 `api` 服务打开,并设
  `IBKR_HOST=host.docker.internal`。Finnhub WS + Massive 现在容器内运行;宿主机没
  TWS 时 IBKR 优雅降级。
- `scraper` 服务崩溃循环,因为 `data.scrapers.runner` 还不存在(Twitter/Reddit
  抓取器是占位)。先注释掉(并从 `depends_on` 移除),等 runner 写好再开。
- 训练好的模型 pickle 在宿主机(`./models/penguinai/`),但没挂进 worker,导致信号
  退化成 NEUTRAL "模型不可用"。修复:给 `ml_worker` 挂 `./models:/app/models`。
- nginx 用 `upstream { server api:8000; }`,在加载时把 IP 解析一次并永久缓存;
  recreate `api`(换 IP)后 nginx 指向旧地址 -> 502。修复:用 Docker 内置 DNS
  解析器(`127.0.0.11`)+ 变量 `proxy_pass`,每次请求重新解析。实测:recreate `api`
  后自动恢复。

运维注意:笔记本睡眠时 Docker 暂停,Celery beat 停止调度、唤醒后补发。一次"信号
全部过期"其实是 Mac 睡眠所致,不是故障。

### 2. macOS 上的 Gemma 4(用宿主机 Ollama,不用容器)

自带的 `ollama/ollama` 镜像太旧,拉不动 Gemma 4(HTTP 412)。按 compose 注释,
macOS 本就应该用宿主机原生 Ollama(Metal)。于是:

- `.env`:`LLM_BACKEND=ollama`、`OLLAMA_BASE_URL=http://host.docker.internal:11434`。
- `gemma` 容器现在放在 compose profile(`container-llm`)后,默认不启动;后端/worker
  连宿主机 Ollama(它已经在服务 `gemma4:e2b`)。只在 Linux/GPU 主机才开这个 profile。

Gemma 4 是推理模型:请求必须带 `"think": false`,否则思考阶段吃光 token 预算、正文
返回空(HTTP 200,`done_reason: length`)。已在 `ollama_backend.py` 和
`backend/app/services/chat_llm.py` 应用。

### 3. 信号输出:所有票都是 55% NEUTRAL

ML 模型其实给出了有区分度的概率(ensemble 0.35-0.58),但 Agent 2(Gemma)读错了
——它把 `ensemble_prob_up=0.38`(明显看跌)描述成"略微看涨",并把所有票默认成
NEUTRAL、置信度写死 0.55。

修复:重写 Agent 2 的系统提示(`ml/inference/gemma_agent.py`),明确输入语义——
`*_prob_up` 是"上涨概率",`<0.5` 看跌,离 0.5 越远越强——并让 ensemble 主导方向、
置信度随证据强度变化。结果:信号有了区分度(SHORT/NEUTRAL/LONG,置信度 0.50-0.95),
不再是一片 55% NEUTRAL。

### 4. LLM 聊天助手(主要功能)

用 Gemma 4 + SSE token 流式,端到端做了分用户、带工具调用的助手。完整文档见
`docs/llm-chat-agent.md`。简述:

- 数据库:`chat_conversations` + `chat_messages`(分用户历史,级联删除)。
- ML:给 Ollama backend 实现工具调用(`chat_tools` + 流式 `chat_tools_stream`);
  确认 Ollama 0.22.1 能可靠解析 Gemma 4 工具调用(CLAUDE.md 里"必须用 vLLM,Ollama
  解析器有 bug"已过时)。新增流式 `ChatAgent.chat_stream`,并给 vLLM backend 配套
  `chat_tools_stream`。
- 后端:会话增删查 + 非流式与 SSE 流式两个发送端点,带配额计费、事务性持久化、
  失败退款。
- 前端:把 `app/chat/page.tsx` 从 localStorage 占位改成服务端聊天,带会话侧边栏、
  工具调用 chip、实时 token 流式。
- 安全已验证:跨用户访问他人会话返回 404;`user_id` 仅服务端注入。

### 改动文件(概览)

见上方英文 "Files changed" 列表(路径相同)。
