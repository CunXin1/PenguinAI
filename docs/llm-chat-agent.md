# LLM Chat Agent

The PREMIUM conversational assistant: a per-user, tool-calling chat surface backed
by Gemma 4. Distinct from the signal pipeline's Gemma agents — it intentionally
accepts user free text and carries its own security model. This document covers the
full stack: database, backend, ML agent, streaming, and the per-backend behavior.

## English

### Overview

Users chat with an AI that can fetch live market data through read-only tools
(quotes, indicators, earnings, fundamentals, news, watchlist). Conversations are
persisted per user and reload across devices. Replies stream token-by-token over
Server-Sent Events (SSE). The LLM transport is swappable: Ollama on macOS, vLLM on
a Linux/Windows GPU host, or a hosted API.

This is a SECOND, separate LLM surface from the signal pipeline. They share only the
`ml/inference/llm/` transport layer. The signal pipeline's prompts are 100%
backend-assembled (no injection surface); the chat agent takes user free text and so
enforces its own guardrails (read-only tools, server-side user identity, untrusted
tool output).

### Architecture

```
frontend/src/app/chat/page.tsx        chat UI: sidebar + streaming bubbles
        |  (fetch + ReadableStream SSE)
        v
backend/app/api/routes/chat.py        REST + SSE endpoints, quota, persistence
        |  ChatContext(user_id, tier, db)
        v
ml/inference/chat/agent.py            ChatAgent: multi-round tool loop (+ streaming)
        |                              ml/inference/chat/tools.py  (read-only tools)
        v
ml/inference/llm/{ollama,vllm,api}    swappable LLM transport (Gemma 4)
        |
        v
TimescaleDB  chat_conversations / chat_messages   (per-user history)
```

The tool loop: send messages + tool schemas to the model. If the model returns
tool calls, the backend runs the (read-only) handlers and feeds the results back,
repeating until the model produces a final text answer or the round cap is reached.

### Database

Two tables (`db/schema/03_relational.sql`):

| Table | Purpose |
|-------|---------|
| `chat_conversations` | one row per thread: `id`, `user_id` (FK users, cascade), `title`, `created_at`, `updated_at`. Index `(user_id, updated_at DESC)`. |
| `chat_messages` | one row per turn: `id`, `conversation_id` (FK conversations, cascade), `role` (`user`/`assistant`), `content`, `tools_used TEXT[]`, `created_at`. Index `(conversation_id, created_at)`. |

Deleting a user cascades to their conversations; deleting a conversation cascades to
its messages. The title is auto-derived from the first user message.

SQLAlchemy models: `backend/app/models/chat.py` (`ChatConversation`, `ChatMessage`).

### Backend API

All routes require a logged-in user (Bearer token). Usage is metered by a per-user
Redis quota (FREE 5 / PRO 100 / PREMIUM unlimited per window).

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/chat/quota` | remaining allowance (no consume) |
| POST | `/api/chat` | stateless one-shot reply (legacy; no history, no tools) |
| GET | `/api/chat/conversations` | list the caller's threads (newest first) |
| POST | `/api/chat/conversations` | create an empty thread |
| GET | `/api/chat/conversations/{id}` | a thread + its full message history |
| DELETE | `/api/chat/conversations/{id}` | delete a thread (cascade) |
| POST | `/api/chat/conversations/{id}/messages` | send a user turn, run the agent, persist + return the reply (non-streaming) |
| POST | `/api/chat/conversations/{id}/messages/stream` | same, but stream the reply over SSE |

Persistence is transactional: a user turn and its assistant reply are saved together
only after a successful generation. On failure the quota is refunded and nothing is
persisted (no dangling user turn).

### Streaming (SSE)

`POST .../messages/stream` returns `text/event-stream`. Each frame is
`data: {json}\n\n`. Event types:

| `type` | Fields | Meaning |
|--------|--------|---------|
| `tool` | `name` | the agent invoked a read-only tool |
| `delta` | `text` | one token (or token group) of the final answer |
| `done` | `message_id`, `conversation_id`, `title`, `tools_used`, `usage` | stream finished; the turn is persisted |
| `error` | `detail` | generation failed; quota refunded, nothing persisted |

Why the design works: with `think:false`, Gemma 4 emits either a tool call (no user
text) or final-answer content (no tool call) per round — never both. So the agent
streams every round and only the final-answer round produces `delta` frames; tool
rounds run silently. The header `X-Accel-Buffering: no` tells nginx not to buffer,
so frames reach the browser as they are produced.

Measured (warm, gemma4:e2b on Apple Silicon): first token at ~0.5s, total ~3.3s.
Non-streaming total is the same ~3.3s — streaming does not change generation speed,
only time-to-first-token (the user sees output ~6x sooner).

### LLM backends (what each supports)

The transport is selected by `LLM_BACKEND` (`auto` -> Ollama on macOS, vLLM
elsewhere). `ml/inference/llm/`:

| Backend | `chat()` (signal JSON) | `chat_tools()` (agent) | `chat_tools_stream()` (token streaming) |
|---------|:--:|:--:|:--:|
| Ollama (`ollama_backend.py`) | yes | yes | yes |
| vLLM (`vllm_backend.py`) | yes | yes | yes |
| Hosted API (`api_backend.py`) | yes | yes | no -> graceful fallback |

The agent's streaming method (`ChatAgent.chat_stream`) checks for
`chat_tools_stream` on the backend. If absent (e.g. the hosted API backend), it
falls back to a single non-streamed round emitted as one `delta` — the endpoint
still works, just without token-by-token output.

Backend-specific notes:
- Ollama: needs `"think": false` (Gemma 4 is a reasoning model; otherwise the
  thinking phase consumes the whole token budget and content is empty). Replayed
  tool-call history must use object `arguments` (not the OpenAI JSON-string form);
  `OllamaBackend._to_ollama_msg` normalizes this. Ollama >= 0.4 (verified on 0.22.1)
  parses Gemma 4 tool calls reliably.
- vLLM: start the server with `--enable-auto-tool-choice` and a Gemma 4 tool parser.
  Streaming reassembles OpenAI tool-call fragments keyed by `index`.

### Security

- `user_id` is taken from the auth token server-side and passed via `ChatContext`.
  The model never supplies it, so a user (or a prompt injection) cannot reach another
  user's watchlist/holdings. Verified: cross-user GET/POST on someone else's
  conversation returns 404.
- Tools are READ-ONLY. No orders, no writes, no money movement (signals only).
- Tool output (news, etc.) is untrusted data, never instructions — the system prompt
  tells the model to treat it as data only.
- Ticker arguments are regex-validated; handlers run parameterized SQL.
- Conversation routes enforce ownership (`WHERE user_id = :caller`) -> 404 otherwise.

### Configuration

`ml/core/config.py` (`CHAT_*`, `LLM_BACKEND`, model variant) and `.env`:

| Setting | Default | Notes |
|---------|---------|-------|
| `LLM_BACKEND` | `auto` | `auto` / `ollama` / `vllm` / `api` |
| `GEMMA_MODEL_VARIANT` | `e2b` | `e2b` now, `e4b` later (no code change) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | in Docker on macOS: `http://host.docker.internal:11434` |
| `VLLM_BASE_URL` | `http://localhost:8080/v1` | GPU host |
| `CHAT_LIMIT_FREE / PRO / PREMIUM` | 5 / 100 / 0 | messages per window; 0 = unlimited |
| `CHAT_MAX_INPUT_CHARS` | 2000 | per-message cap |
| `CHAT_MAX_HISTORY` | 20 | context turns kept |
| `CHAT_MAX_TOKENS` | 1024 | output cap |
| `CHAT_TEMPERATURE` | 0.7 | conversational |

### Key files

```
db/schema/03_relational.sql                    chat_conversations + chat_messages DDL
backend/app/models/chat.py                     SQLAlchemy models
backend/app/schemas/chat.py                    Pydantic request/response models
backend/app/api/routes/chat.py                 REST + SSE endpoints
backend/app/services/chat_agent.py             bridge to the ML agent (sync + stream)
backend/app/services/chat_llm.py               legacy stateless reply
ml/inference/chat/agent.py                     ChatAgent: tool loop + chat_stream
ml/inference/chat/tools.py                     read-only tool registry
ml/inference/chat/context.py                   ChatContext (server-side user_id)
ml/inference/llm/ollama_backend.py             Ollama transport (+ streaming)
ml/inference/llm/vllm_backend.py               vLLM transport (+ streaming)
frontend/src/app/chat/page.tsx                 chat UI (sidebar + streaming)
frontend/src/lib/api.ts                        chat client (incl. sendMessageStream)
frontend/src/lib/types.ts                      Conversation / StoredMessage types
```

### Local dev / testing

macOS (Ollama): the backend talks to the host's native Ollama
(`OLLAMA_BASE_URL=http://host.docker.internal:11434`); pull the model with
`ollama pull gemma4:e2b`. Keep `ollama serve` running.

Quick end-to-end check (replace TOKEN):

```bash
# create a thread, then stream a tool-using question
CONV=$(curl -s -X POST localhost:8000/api/chat/conversations \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "localhost:8000/api/chat/conversations/$CONV/messages/stream" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"What is the latest quote for AAPL?"}'
```

You should see a `tool` frame (`get_quote`), then `delta` frames streaming the reply,
then a `done` frame.

## 中文

### 概述

PREMIUM 对话助手:分用户、带工具调用的聊天界面,底层是 Gemma 4。与信号管线的
Gemma agent 是两个独立面;它们只共用 `ml/inference/llm/` 这一层传输。用户可以让
AI 通过只读工具拉取实时行情(报价、指标、财报、基本面、新闻、自选股)。会话按用户
持久化、跨设备可重载。回复通过 SSE 逐 token 流式返回。LLM 传输可切换:macOS 用
Ollama,Linux/Windows GPU 用 vLLM,或托管 API。

信号管线的 prompt 是 100% 后端拼装(无注入面);聊天助手接受用户自由文本,因此有
自己的防护(只读工具、服务端注入 user_id、把工具输出当作不可信数据)。

### 架构

```
frontend/src/app/chat/page.tsx        聊天 UI:侧边栏 + 流式气泡
        |  (fetch + ReadableStream 解析 SSE)
        v
backend/app/api/routes/chat.py        REST + SSE 端点、配额、持久化
        |  ChatContext(user_id, tier, db)
        v
ml/inference/chat/agent.py            ChatAgent:多轮工具循环(+ 流式)
        |                              ml/inference/chat/tools.py(只读工具)
        v
ml/inference/llm/{ollama,vllm,api}    可切换 LLM 传输(Gemma 4)
        |
        v
TimescaleDB  chat_conversations / chat_messages   (分用户历史)
```

工具循环:把消息 + 工具 schema 发给模型。模型若返回工具调用,后端执行(只读)
处理器并把结果回灌,如此往复,直到模型给出最终文字答案或达到轮次上限。

### 数据库

两张表(`db/schema/03_relational.sql`):

| 表 | 用途 |
|----|------|
| `chat_conversations` | 每个会话一行:`id`、`user_id`(外键 users,级联)、`title`、`created_at`、`updated_at`。索引 `(user_id, updated_at DESC)`。 |
| `chat_messages` | 每条消息一行:`id`、`conversation_id`(外键,级联)、`role`、`content`、`tools_used TEXT[]`、`created_at`。索引 `(conversation_id, created_at)`。 |

删除用户级联删其会话;删除会话级联删其消息。标题由第一条用户消息自动生成。
SQLAlchemy 模型:`backend/app/models/chat.py`。

### 后端 API

所有路由需登录(Bearer token)。用量由 Redis 按用户分级计费(FREE 5 / PRO 100 /
PREMIUM 不限 每窗口)。

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/chat/quota` | 剩余额度(不消耗) |
| POST | `/api/chat` | 无状态一次性回复(旧接口;无历史、无工具) |
| GET | `/api/chat/conversations` | 列出本人会话(最新在前) |
| POST | `/api/chat/conversations` | 新建空会话 |
| GET | `/api/chat/conversations/{id}` | 会话 + 完整消息历史 |
| DELETE | `/api/chat/conversations/{id}` | 删除会话(级联) |
| POST | `/api/chat/conversations/{id}/messages` | 发一条用户消息,跑 agent,落库并返回回复(非流式) |
| POST | `/api/chat/conversations/{id}/messages/stream` | 同上,但通过 SSE 流式返回 |

持久化是事务性的:用户消息和助手回复在生成成功后才一起写入。失败则退还配额、
不落库(不会留半截用户消息)。

### 流式(SSE)

`POST .../messages/stream` 返回 `text/event-stream`,每帧 `data: {json}\n\n`:

| `type` | 字段 | 含义 |
|--------|------|------|
| `tool` | `name` | agent 调用了一个只读工具 |
| `delta` | `text` | 最终答案的一个 token(或一组) |
| `done` | `message_id`、`conversation_id`、`title`、`tools_used`、`usage` | 流结束;该轮已落库 |
| `error` | `detail` | 生成失败;退配额、不落库 |

为什么这样设计成立:配合 `think:false`,Gemma 4 每轮要么吐工具调用(无用户文字)、
要么吐最终答案正文(无工具调用),不会混在一起。所以 agent 逐轮流式,只有最终答案
轮产生 `delta`,工具轮静默运行。响应头 `X-Accel-Buffering: no` 让 nginx 不缓冲,
帧实时到达浏览器。

实测(热状态,Apple Silicon 上的 gemma4:e2b):首 token ~0.5s,总时长 ~3.3s。
非流式总时长同样 ~3.3s ——流式不改变生成速度,只把首字时间提前约 6 倍。

### LLM 后端(各自支持什么)

由 `LLM_BACKEND` 选择(`auto` -> macOS 用 Ollama,其它用 vLLM):

| 后端 | `chat()`(信号 JSON) | `chat_tools()`(agent) | `chat_tools_stream()`(token 流式) |
|------|:--:|:--:|:--:|
| Ollama | 有 | 有 | 有 |
| vLLM | 有 | 有 | 有 |
| 托管 API | 有 | 有 | 无 -> 优雅降级 |

agent 的流式方法 `ChatAgent.chat_stream` 会检测后端有没有 `chat_tools_stream`。
没有(如托管 API)就降级成"整段生成完、当作一个 `delta` 发出"——端点仍可用,只是
不是逐字。

后端注意:
- Ollama:需要 `"think": false`(Gemma 4 是推理模型,否则思考阶段吃光 token 预算、
  正文为空)。回灌的工具调用历史必须用对象形式的 `arguments`(不是 OpenAI 的 JSON
  字符串);`OllamaBackend._to_ollama_msg` 会归一化。Ollama >= 0.4(0.22.1 实测)
  能可靠解析 Gemma 4 工具调用。
- vLLM:启动时加 `--enable-auto-tool-choice` 和 Gemma 4 的 tool parser。流式会按
  `index` 重组 OpenAI 的工具调用分片。

### 安全

- `user_id` 在服务端从 token 取出,经 `ChatContext` 传入;模型永远拿不到它,所以
  用户(或提示注入)无法访问他人自选股/持仓。实测:跨用户 GET/POST 他人会话返回 404。
- 工具全部只读。无下单、无写入、无资金操作(只出信号)。
- 工具输出(新闻等)是不可信数据,绝非指令——系统提示要求模型只当数据看。
- ticker 参数正则校验;处理器走参数化 SQL。
- 会话路由强制归属(`WHERE user_id = :caller`),否则 404。

### 配置

见 `ml/core/config.py`(`CHAT_*`、`LLM_BACKEND`、模型 variant)与 `.env`:

| 配置 | 默认 | 说明 |
|------|------|------|
| `LLM_BACKEND` | `auto` | `auto` / `ollama` / `vllm` / `api` |
| `GEMMA_MODEL_VARIANT` | `e2b` | 现 `e2b`,以后 `e4b`(无需改代码) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | macOS 上 Docker 内用 `http://host.docker.internal:11434` |
| `VLLM_BASE_URL` | `http://localhost:8080/v1` | GPU 主机 |
| `CHAT_LIMIT_FREE / PRO / PREMIUM` | 5 / 100 / 0 | 每窗口消息数;0 = 不限 |
| `CHAT_MAX_INPUT_CHARS` | 2000 | 单条上限 |
| `CHAT_MAX_HISTORY` | 20 | 保留的上下文轮数 |
| `CHAT_MAX_TOKENS` | 1024 | 输出上限 |
| `CHAT_TEMPERATURE` | 0.7 | 对话型 |

### 关键文件

见上方英文 "Key files" 列表(路径相同)。

### 本地开发 / 测试

macOS(Ollama):后端连宿主机原生 Ollama
(`OLLAMA_BASE_URL=http://host.docker.internal:11434`);用 `ollama pull gemma4:e2b`
拉模型,保持 `ollama serve` 运行。快速端到端检查见上方英文 bash 示例:应先看到一个
`tool` 帧(`get_quote`),再是流式 `delta`,最后 `done`。
