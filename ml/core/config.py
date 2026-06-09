from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MLSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    REDIS_URL: str = "redis://localhost:6379/0"

    MODEL_DIR: str = str(_PROJECT_ROOT / "models" / "penguinai")

    # Gemma 4
    GEMMA_MODEL_PATH: str = "/models/gemma4"
    GEMMA_API_URL: str = ""
    GEMMA_API_KEY: str = ""
    GEMMA_MAX_TOKENS: int = 512
    GEMMA_TEMPERATURE: float = 0.1  # Low temp for deterministic financial reasoning

    # FinBERT
    FINBERT_MODEL: str = "ProsusAI/finbert"
    FINBERT_BATCH_SIZE: int = 32
    FINBERT_MAX_LENGTH: int = 512

    # Embeddings (for RAG)
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    # Signal thresholds
    MIN_CONFIDENCE_THRESHOLD: float = 0.55  # Below this → NEUTRAL
    TOP100_TICKERS_KEY: str = "top100:tickers"
    CACHE_TTL_TOP100: int = 3600
    CACHE_TTL_COLD: int = 14400

    # Feature engineering
    LOOKBACK_BARS_30MIN: int = 96  # 2 trading days of 30-min bars
    LOOKBACK_BARS_1MIN: int = 390  # 1 trading day of 1-min bars

    # Data APIs
    POLYGON_API_KEY: str = ""
    # Massive (massive.com) — Polygon-compatible REST; used to validate
    # user-requested symbols (reference/tickers) in symbol_validation task.
    MASSIVE_API_KEY: str = ""
    MASSIVE_BASE_URL: str = "https://api.massive.com"
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "PenguinAI/0.1"


@lru_cache
def get_ml_settings() -> MLSettings:
    return MLSettings()


ml_settings = get_ml_settings()
