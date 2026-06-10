import json
import logging
import secrets
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)

_INSECURE_KEYS = {"change_me", "change_me_to_a_long_random_string_in_production", ""}


def _find_env_file() -> str:
    from pathlib import Path

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
    return ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(), env_file_encoding="utf-8", extra="ignore"
    )

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
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        return self

    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    DATABASE_POOL_SIZE: int = 40
    DATABASE_MAX_OVERFLOW: int = 20

    # ── Redis ─────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Rate limiting (per IP, Redis-backed) ─────────────────────
    RATE_LIMIT_LOGIN_TIMES: int = 10  # max attempts per window
    RATE_LIMIT_LOGIN_WINDOW: int = 60  # seconds
    RATE_LIMIT_REGISTER_TIMES: int = 5
    RATE_LIMIT_REGISTER_WINDOW: int = 3600
    RATE_LIMIT_FORGOT_PW_TIMES: int = 5
    RATE_LIMIT_FORGOT_PW_WINDOW: int = 3600
    RATE_LIMIT_RESET_PW_TIMES: int = 5
    RATE_LIMIT_RESET_PW_WINDOW: int = 3600
    RATE_LIMIT_ACCOUNT_LOGIN_TIMES: int = 20  # per account (any IP)
    RATE_LIMIT_ACCOUNT_LOGIN_WINDOW: int = 3600

    # ── Signal cache TTL (seconds) ────────────────────────────────
    CACHE_TTL_TOP100: int = 3600  # 1 hour
    CACHE_TTL_COLD: int = 14400  # 4 hours
    TOP100_TICKERS_KEY: str = "top100:tickers"

    # ── Data APIs ─────────────────────────────────────────────────
    POLYGON_API_KEY: str = ""
    MASSIVE_API_KEY: str = ""
    MASSIVE_BASE_URL: str = "https://api.massive.com"
    FRED_API_KEY: str = ""  # free: fed funds rate history (fred.stlouisfed.org)
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

    # ── Admin seed ─────────────────────────────────────────────────
    ADMIN_EMAIL: str = "admin@penguinai.com"
    ADMIN_PASSWORD: str = ""  # auto-generated on first startup if empty

    # ── Fear & Greed / Volatility ────────────────────────────────
    # No settings here by design: source URLs are module constants in
    # data/fear_greed/{cnn,cboe}.py (single source of truth), and
    # FEAR_GREED_REFRESH_MIN is read directly from the environment by
    # data/fear_greed/scheduler.py.

    # ── FOMC defaults ────────────────────────────────────────────
    FOMC_DEFAULT_TREND_LIMIT: int = 10
    FOMC_DEFAULT_STATEMENTS_LIMIT: int = 10
    FOMC_DEFAULT_MARKET_REACTION_LIMIT: int = 20
    FOMC_DEFAULT_SCHEDULE_PAST: int = 10
    FOMC_DEFAULT_SCHEDULE_FUTURE: int = 10
    FOMC_DEFAULT_RATE_HISTORY_YEARS: int = 5

    # ── OAuth (Google + Apple Sign In) ────────────────────────────
    # Public origin of THIS backend; the OAuth redirect_uri is built as
    # {OAUTH_REDIRECT_BASE}/api/auth/oauth/{provider}/callback and must be
    # registered verbatim in the Google/Apple console.
    OAUTH_REDIRECT_BASE: str = "http://localhost:8000"
    # Where users land after sign-in and where email links point (the Next.js app).
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    # "Sign in with Apple": APPLE_CLIENT_ID is the Services ID (e.g. com.penguinai.web).
    # The client secret is an ES256 JWT minted on the fly from the .p8 key — see core/oauth.py.
    APPLE_CLIENT_ID: str = ""
    APPLE_TEAM_ID: str = ""
    APPLE_KEY_ID: str = ""
    APPLE_PRIVATE_KEY: str = ""  # contents of the .p8 (PEM); \n-escaped in .env is fine

    @field_validator("APPLE_PRIVATE_KEY", mode="before")
    @classmethod
    def _normalize_apple_key(cls, v: object) -> object:
        # .env can't hold real newlines; allow a \n-escaped PEM and restore them.
        if isinstance(v, str) and "\\n" in v:
            return v.replace("\\n", "\n")
        return v

    # ── Email (transactional: verification + password reset) ──────
    # EMAIL_BACKEND: "console" just logs the message (dev default); "smtp" sends it.
    EMAIL_BACKEND: str = "console"
    EMAIL_FROM: str = "PenguinAI <no-reply@penguinai.com>"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_STARTTLS: bool = True  # True for port 587 (STARTTLS); for 465 set False + SMTP_SSL=true
    SMTP_SSL: bool = False

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
