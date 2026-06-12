# ML Layer — Signal Inference Engine

## English

### Overview

The ML layer is the computational core of PenguinAI. It runs on the RTX 4090 GPU and is responsible for:
- Computing technical features from 30-min OHLCV bars
- Running XGBoost and Random Forest classifiers
- Scoring social media sentiment with FinBERT
- Retrieving relevant posts via metadata-filtered RAG (pgvector)
- Synthesizing all signals through a two-step Gemma 4 agentic pipeline
- Caching results in `signal_cache` via Celery tasks

This layer **never receives user input**. All data flows from the database and scrapers.

### Structure

```
ml/
├── core/
│   └── config.py            MLSettings — all config via environment variables
├── inference/
│   ├── signal_engine.py     Orchestrator: bars → features → ML → RAG → Gemma → cache
│   ├── finbert_scorer.py    FinBERT sentiment scorer (batch, lazy-loaded)
│   └── gemma_agent.py       Two-step Gemma 4 agent with output validation + retry
├── models/
│   ├── xgboost_trainer.py   XGBoost GPU training with purged walk-forward CV
│   ├── rf_trainer.py        Random Forest training with class_weight="balanced"
│   └── model_registry.py   Hot-swap model loader (no restart needed)
├── features/
│   ├── technical.py         pandas-ta indicator computation on 30-min bars
│   ├── sentiment.py         Aggregate FinBERT scores from social_posts table
│   └── fundamental.py       Fetch earnings surprise + PE ratio from DB
├── rag/
│   ├── embedder.py          sentence-transformers MiniLM-L6 (384-dim)
│   └── retriever.py         pgvector cosine search with ticker+time metadata filter
├── tasks/
│   ├── celery_app.py        Celery app + Beat schedule definitions
│   ├── hourly_signal_cache.py  refresh_top100 + compute_single_signal tasks
│   ├── daily_pipeline.py    run_daily_pipeline (retrain) + fetch_fundamentals (stub)
│   ├── realtime_ingest.py   scrape_social_media (stub) + fetch_earnings (Finnhub)
│   └── symbol_validation.py validate_symbol_requests — classify user-requested symbols via Massive
├── requirements.txt
└── Dockerfile
```

### Signal Generation Pipeline

```
30-min OHLCV bars (TimescaleDB)
        │
        ▼
[1] Technical Features (pandas-ta)
    RSI-14, MACD, Bollinger %B, ATR%, EMA-20 slope,
    price vs SMA-200, volume ratio, VWAP%
        │
        ▼
[2] ML Inference
    XGBoost  ──┐
               ├─► ensemble_prob = XGB×0.6 + RF×0.4
    RF         ──┘
        │
        ▼
[3] Sentiment (FinBERT)
    social_posts last 72h → avg finbert_score + post_count
        │
        ▼
[4] RAG Retrieval (pgvector)
    top-5 relevant posts filtered by [ticker, time window]
        │
        ▼
[5] Context Assembly (Agent 1 — no LLM)
    Structured JSON: ML scores + sentiment + RAG posts +
    celebrity actions + FOMC score + fundamentals
        │
        ▼
[6] Gemma 4 Reasoning (Agent 2)
    Input:  structured context JSON
    Output: { direction, confidence, holding_period,
              ai_attribution (≤150 chars),
              ai_analysis (≤300 chars) }
    JSON mode locked · 3 retries · output validated
        │
        ▼
[7] FOMC Macro Filter
    If hawk_dove > 0.5 and direction=LONG: dampen confidence × 0.85
        │
        ▼
[8] signal_cache UPSERT
```

### Models

> **Specialization (B1/B2, built):** beyond the single global model below, there are now
> per-basket × horizon models (1w / 1m / 3m), and the CV is purged walk-forward (the old
> "no leakage" TimeSeriesSplit actually leaked). Full reference: `docs/ml-specialization.md`.

#### XGBoost
- **Task**: Binary classification — will close price be higher in 16 bars (8 hours)?
- **Training**: GPU (`device="cuda"`), **purged walk-forward CV** — globally time-sorted +
  overlapping-label embargo (`purged_walk_forward_splits`). NOT `TimeSeriesSplit`, which
  leaked on pooled multi-symbol rows; honest short-horizon direction AUC is ~0.50.
- **Features**: 11 technical indicators (see `FEATURE_COLS` in `xgboost_trainer.py`)
- **Saved to**: `/models/penguinai/xgboost_prod.pkl`

#### Random Forest
- **Task**: Same target, ensemble diversity (different model family = uncorrelated errors)
- **Training**: CPU multi-core, `class_weight="balanced"` for imbalanced classes
- **Saved to**: `/models/penguinai/rf_prod.pkl`

#### FinBERT
- **Model**: `ProsusAI/finbert` (HuggingFace)
- **Output**: sentiment ∈ [-1, 1] per post; aggregated to mean over 72-hour window
- **Loading**: Lazy-loaded on first call, cached in memory via `@lru_cache`

#### Gemma 4
- **Backend layer**: pluggable transport under `ml/inference/llm/` selected by
  `LLM_BACKEND` (`auto` → Ollama on macOS, vLLM on Windows/Linux GPU; `api` for
  hosted). The Agent 2 harness (`gemma_agent.py`) is backend-agnostic.
- **Model**: Gemma 4 **E2B** now (`GEMMA_MODEL_VARIANT`); flip to **E4B** later.
- **Deployment**: `ml/serving/` (`start_ollama.sh` / `start_vllm.ps1` /
  `start_vllm.sh`). Verify with `make gemma-check`. Full guide: `ml/serving/README.md`.
- **Output format**: JSON-schema locked per backend (vLLM guided decoding /
  Ollama `format` / API json_schema).
- **Temperature**: 0.1 (near-deterministic for financial reasoning)
- **Finetune seam**: vLLM LoRA/merged checkpoint or Ollama `Modelfile.gemma`
  ADAPTER — serve-time only, no code change.
- **Graceful degrade**: if the LLM is down, `signal_engine` falls back to an
  ML-only signal, so serving is additive, never load-bearing.

### Celery Tasks & Schedule

| Task | Queue | Schedule | Description |
|------|-------|----------|-------------|
| `refresh_top100` | ml_inference | Hourly 9am–5pm ET weekdays | Pre-compute Top-100 signals |
| `compute_single_signal` | ml_inference | On-demand | Cold ticker real-time compute |
| `run_daily_pipeline` | ml_inference | 10pm ET weekdays | Model retrain + Redis update |
| `scrape_social_media` | default | Every 30 min | Reddit + Twitter → FinBERT score *(stub — scrapers not built)* |
| `fetch_fundamentals` | default | 8am ET weekdays | PE / fundamentals refresh *(stub)* |
| `fetch_earnings` | default | 3×/weekday (08:00/14:00/21:00 ET) | Finnhub earnings calendar + BMO/AMC actuals |
| `validate_symbol_requests` | default | Every 6h | Classify user-requested symbols against Massive |

### Feature Engineering

At serve time, features come from the `indicators_30min` view (computed in SQL over `bars_30m`); training reads the `data/30min_data` parquet through the *same* SQL, so there's no train/serve skew. `ml/features/technical.py` (`pandas-ta`) is the live/fallback path for symbols without precomputed indicators. The canonical feature list lives in `ml/models/xgboost_trainer.py:FEATURE_COLS` — this is the **single source of truth**. Adding a feature requires updating:
1. `FEATURE_COLS` in `xgboost_trainer.py`
2. `_feature_names()` in `model_registry.py`
3. `compute_features()` in `features/technical.py`
4. Retrain both models

### Training a New Model

```bash
# GPU environment required
cd /path/to/penguinai

# Train XGBoost
python -c "
from ml.models.xgboost_trainer import train
metrics = train(db_path='path/to/features.duckdb', output_path='/models/penguinai/xgboost_prod.pkl')
print(metrics)
"

# Train Random Forest
python -c "
from ml.models.rf_trainer import train
metrics = train(db_path='path/to/features.duckdb', output_path='/models/penguinai/rf_prod.pkl')
print(metrics)
"

# Hot-reload (no restart needed)
python -c "from ml.models.model_registry import model_registry; model_registry.reload()"
```

### Running Workers

```bash
# ML inference worker (requires GPU)
celery -A ml.tasks.celery_app worker --queues=ml_inference -c 1 --loglevel=info

# General worker (scrapers, fundamentals)
celery -A ml.tasks.celery_app worker --queues=default -c 4 --loglevel=info

# Beat scheduler
celery -A ml.tasks.celery_app beat --loglevel=info

# Monitor (Flower UI at :5555)
celery -A ml.tasks.celery_app flower --port=5555
```

---

## 中文

### 模块概述

ML 层是 PenguinAI 的算力核心，运行在 RTX 4090 GPU 上，负责完整的信号生成流水线：特征工程 → ML 推理 → RAG 检索 → Gemma 4 智能体推理 → 信号缓存写入。

**该层绝不接收用户输入。** 所有数据来自数据库和爬虫。

### 信号生成流水线（中文版）

```
30分钟K线（TimescaleDB）
    → 技术指标计算（pandas-ta）
    → XGBoost + 随机森林推理
    → FinBERT 情绪聚合（72小时内帖子）
    → pgvector RAG 检索（股票+时间过滤）
    → Gemma 4 Agent 1（结构化上下文组装，无LLM调用）
    → Gemma 4 Agent 2（量化推理，JSON模式锁定输出格式）
    → FOMC 鹰鸽过滤（强鹰派时压制做多置信度）
    → signal_cache 表 UPSERT
```

### 模型说明

> **专门化（B1/B2，已建）**：除下面的全局模型外，现有 分篮子 × 跨度 模型（1周/1月/3月），
> 且 CV 已改为 purged walk-forward（旧 TimeSeriesSplit 实际会泄漏）。详见 `docs/ml-specialization.md`。

| 模型 | 用途 | 关键参数 |
|------|------|---------|
| XGBoost | 主分类器，预测8小时后涨跌 | GPU训练、purged walk-forward CV（全局排序+重叠标签 embargo，非 TimeSeriesSplit） |
| 随机森林 | 集成多样性，与XGBoost互补 | class_weight="balanced" |
| FinBERT | 社媒帖子情绪打分 | 输出[-1,1]，懒加载+LRU缓存 |
| Gemma 4 | 最终综合推理和文字归因 | 温度0.1，JSON模式，3次重试 |

### 特征工程注意事项

特征名单的**唯一来源**是 `ml/models/xgboost_trainer.py:FEATURE_COLS`。新增特征必须同步修改以下四处，否则模型预测会报 shape 错误：
1. `xgboost_trainer.py:FEATURE_COLS`
2. `model_registry.py:_feature_names()`
3. `features/technical.py:compute_features()`
4. 重新训练两个模型

### Celery 并发注意

Top-100 刷新任务使用 `asyncio.gather` 10 并发，**每个 ticker 使用独立 Session**。禁止多个协程共享同一个 SQLAlchemy async session。
