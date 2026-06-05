import json
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── App ───────────────────────────────────────────────────────
    APP_NAME: str = "PenguinAI"
    DEBUG: bool = False
    SECRET_KEY: str = "change_me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # ── Redis ─────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Signal cache TTL (seconds) ────────────────────────────────
    CACHE_TTL_TOP100: int = 3600        # 1 hour
    CACHE_TTL_COLD: int = 14400         # 4 hours
    TOP100_TICKERS_KEY: str = "top100:tickers"

    # ── Data APIs ─────────────────────────────────────────────────
    POLYGON_API_KEY: str = ""
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 7497
    IBKR_CLIENT_ID: int = 1

    # ── Social scrapers ───────────────────────────────────────────
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "PenguinAI/0.1"

    # ── ML ────────────────────────────────────────────────────────
    GEMMA_MODEL_PATH: str = "/models/gemma4"
    GEMMA_API_URL: str = ""          # empty = use local inference
    GEMMA_API_KEY: str = ""
    FINBERT_MODEL: str = "ProsusAI/finbert"

    # ── OAuth (future) ────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    APPLE_CLIENT_ID: str = ""

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value):
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                return json.loads(raw)
            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
