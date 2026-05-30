# PenguinAI

> AI-powered quantitative investment signal platform for US equities.
> Signals only — no trading execution.

---

## English

### Overview

PenguinAI is an industrial-grade AI investment research system that fuses classical quantitative finance, NLP-based sentiment analysis, and a multi-agent LLM reasoning pipeline to produce high-quality, explainable Long/Short/Neutral signals for US stocks and ETFs.

**Core design principles:**
- **Signal-only**: No order execution, no portfolio management. Pure research output.
- **Zero prompt injection**: All LLM prompts are backend-assembled. No user free-text ever reaches the model.
- **Decoupled architecture**: Frontend, API gateway, and ML inference run as independent services.
- **Dual-track caching**: Top-100 tickers pre-computed hourly (instant); cold tickers computed on-demand (~2–5 s).

### Quick Start

```bash
# 1. Copy environment file and fill in secrets
cp .env.example .env

# 2. Start all services
docker-compose up -d

# 3. Bootstrap ticker universe (run once)
python scripts/bootstrap_universe.py

# 4. Open the app
open http://localhost
```

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        nginx (80)                           │
└──────────────────┬──────────────────┬───────────────────────┘
                   │                  │
          ┌────────▼──────┐  ┌───────▼────────┐
          │  Next.js :3000 │  │  FastAPI :8000  │
          │   (frontend)   │  │   (backend)     │
          └────────────────┘  └───────┬─────────┘
                                      │ async
                              ┌───────▼─────────┐
                              │   TimescaleDB   │◄── Hypertable (170M rows)
                              │   + pgvector    │
                              └───────┬─────────┘
                                      │
                    ┌─────────────────▼──────────────────┐
                    │            Redis                    │
                    │  signal cache · task broker · TTL  │
                    └─────────────────┬──────────────────┘
                                      │ Celery
                    ┌─────────────────▼──────────────────┐
                    │         ML Inference Layer          │
                    │  XGBoost · RF · FinBERT · Gemma 4  │
                    │            (RTX 4090)               │
                    └────────────────────────────────────┘
```

### Project Structure

```
penguinai/
├── backend/        FastAPI API gateway (port 8000)
├── ml/             ML inference + Celery workers (GPU)
├── data/           Data ingestion + scrapers
├── frontend/       Next.js web app (port 3000)
├── db/             TimescaleDB schema + Alembic migrations
├── scripts/        One-time bootstrap scripts
├── docs/           Architecture and developer guides
└── nginx/          Reverse proxy config
```

### Module Documentation

| Module | README | Description |
|--------|--------|-------------|
| Backend | [backend/README.md](backend/README.md) | FastAPI routes, auth, DB models |
| ML | [ml/README.md](ml/README.md) | Signal pipeline, models, Celery tasks |
| Data | [data/README.md](data/README.md) | Ingestion, scrapers, IBKR stream |
| Frontend | [frontend/README.md](frontend/README.md) | Next.js pages, components, theming |
| Database | [db/README.md](db/README.md) | Schema, hypertables, migrations |

### Developer Guides

| Guide | Description |
|-------|-------------|
| [docs/architecture.md](docs/architecture.md) | Full system design and data flow |
| [docs/signal-pipeline.md](docs/signal-pipeline.md) | Step-by-step signal generation |
| [docs/data-sources.md](docs/data-sources.md) | Data sources, coverage, and ingestion |
| [docs/api-reference.md](docs/api-reference.md) | REST API endpoint reference |
| [docs/deployment.md](docs/deployment.md) | Docker local → AWS production |

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS |
| Backend | FastAPI, SQLAlchemy (async), Pydantic v2 |
| Database | TimescaleDB (PostgreSQL 16) + pgvector |
| Cache / Queue | Redis 7 + Celery 5 |
| ML Models | XGBoost, Random Forest, FinBERT, Gemma 4 (vLLM) |
| Infrastructure | Docker Compose → AWS ECS + ECR |

---

## 中文

### 项目简介

PenguinAI 是一个工业级 AI 自动化投研信号推荐系统，将经典量化金融、NLP 文本情绪挖掘与多智能体大语言模型推理深度融合，面向美股及 ETF 输出高可解释性的多空信号。

**核心设计理念：**
- **纯信号输出**：无交易执行，无持仓管理，只输出投研信号
- **零提示词注入**：所有 LLM 提示词由后端硬编码组装，用户零自由文本输入
- **三层解耦架构**：前端、API 网关、ML 推理层完全独立部署
- **双轨缓存策略**：Top-100 热门股每小时预计算（毫秒响应）；冷门股按需实时推理（2–5 秒）

### 快速启动

```bash
# 1. 复制环境变量文件并填写密钥
cp .env.example .env

# 2. 启动所有服务
docker-compose up -d

# 3. 初始化股票池（仅执行一次）
python scripts/bootstrap_universe.py

# 4. 打开应用
open http://localhost
```

### 技术栈

| 层级 | 技术选型 |
|------|---------|
| 前端 | Next.js 15、React 19、TypeScript、Tailwind CSS |
| 后端 | FastAPI、SQLAlchemy（异步）、Pydantic v2 |
| 数据库 | TimescaleDB（PostgreSQL 16）+ pgvector 向量扩展 |
| 缓存/队列 | Redis 7 + Celery 5 |
| ML 模型 | XGBoost、随机森林、FinBERT 情绪模型、Gemma 4（vLLM 本地部署） |
| 基础设施 | Docker Compose 本地开发 → AWS ECS + ECR 生产环境 |

### 项目规范

- 前端永远使用暗黑主题，背景色 `#09090b`（zinc-950）
- 做空信号：红色；做多信号：绿色；中性：灰色
- 所有 API 调用只通过 `frontend/src/lib/api.ts`，禁止在组件内直接 fetch
- 信号输出 Schema 变更必须同步更新：`signal_cache` 表 + `schemas/signal.py` + `types.ts`
- ML 训练禁止在 FastAPI 进程内运行，必须通过 Celery `ml_inference` 队列派发
