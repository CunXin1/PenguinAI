import json
import logging
import secrets
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)

_INSECURE_KEYS = {"change_me", "change_me_to_a_long_random_string_in_production", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── App ───────────────────────────────────────────────────────
    APP_NAME: str = "PenguinAI"
    DEBUG: bool = False
    SECRET_KEY: str = "change_me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _parse_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @model_validator(mode="after")
    def _check_secret_key(self) -> "Settings":
        if self.SECRET_KEY not in _INSECURE_KEYS:
            return self
        self.SECRET_KEY = secrets.token_urlsafe(64)
        if self.DEBUG:
            _logger.warning(
                "SECRET_KEY not set — using ephemeral random key (dev only, tokens reset on restart)"
            )
        else:
            _logger.critical(
                "SECRET_KEY is insecure in non-DEBUG mode! All tokens will reset on restart. "
                "Set a strong SECRET_KEY in .env for production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        return self

    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    DATABASE_POOL_SIZE: int = 40
    DATABASE_MAX_OVERFLOW: int = 20

    # ── Redis ─────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Rate limiting (per IP, Redis-backed) ─────────────────────
    RATE_LIMIT_LOGIN_TIMES: int = 10       # max attempts per window
    RATE_LIMIT_LOGIN_WINDOW: int = 60      # seconds
    RATE_LIMIT_REGISTER_TIMES: int = 5
    RATE_LIMIT_REGISTER_WINDOW: int = 3600
    RATE_LIMIT_FORGOT_PW_TIMES: int = 5
    RATE_LIMIT_FORGOT_PW_WINDOW: int = 3600
    RATE_LIMIT_RESET_PW_TIMES: int = 5
    RATE_LIMIT_RESET_PW_WINDOW: int = 3600
    RATE_LIMIT_ACCOUNT_LOGIN_TIMES: int = 20   # per account (any IP)
    RATE_LIMIT_ACCOUNT_LOGIN_WINDOW: int = 3600

    # ── Signal cache TTL (seconds) ────────────────────────────────
    CACHE_TTL_TOP100: int = 3600  # 1 hour
    CACHE_TTL_COLD: int = 14400  # 4 hours
    TOP100_TICKERS_KEY: str = "top100:tickers"

    # ── Data APIs ─────────────────────────────────────────────────
    POLYGON_API_KEY: str = ""
    MASSIVE_API_KEY: str = ""
    MASSIVE_BASE_URL: str = "https://api.massive.com"
    FINNHUB_API_KEY: str = ""  # free tier: earnings calendar + estimates (60 req/min)
    FINNHUB_BASE_URL: str = "https://finnhub.io/api/v1"
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 7497
    IBKR_CLIENT_ID: int = 1

    # ── Social scrapers ───────────────────────────────────────────
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "PenguinAI/0.1"

    # ── ML ────────────────────────────────────────────────────────
    GEMMA_MODEL_PATH: str = "/models/gemma4"
    GEMMA_API_URL: str = ""  # empty = use local inference
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
