from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MLSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    REDIS_URL: str = "redis://localhost:6379/0"

    MODEL_DIR: str = str(_PROJECT_ROOT / "models" / "penguinai")

    # ── Gemma 4 LLM (Agent 2 reasoner) ───────────────────────────────────────
    # Backend selection. "auto" → ollama on macOS, vllm elsewhere (Win/Linux GPU).
    #   auto | vllm | ollama | api
    LLM_BACKEND: str = "auto"
    # Model size. e2b now; e4b later — only this line changes to upgrade.
    #   e2b | e4b
    GEMMA_MODEL_VARIANT: str = "e2b"

    GEMMA_MAX_TOKENS: int = 512
    GEMMA_TEMPERATURE: float = 0.1  # Low temp for deterministic financial reasoning

    # vLLM (Windows / Linux GPU) — OpenAI-compatible server.
    VLLM_BASE_URL: str = "http://localhost:8080/v1"
    # Override to a HF id or a local finetuned/merged checkpoint path.
    # Blank → derived from GEMMA_MODEL_VARIANT (see vllm_model()).
    VLLM_MODEL: str = ""

    # Ollama (macOS) — native /api/chat with structured-output `format`.
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    # Override to a custom (e.g. finetuned, built via Modelfile) tag.
    # Blank → derived from GEMMA_MODEL_VARIANT (see ollama_model()).
    OLLAMA_MODEL: str = ""

    # External API (future: Vertex AI / any OpenAI-compatible endpoint).
    # Used only when LLM_BACKEND="api". Left as the plug-in point.
    GEMMA_API_URL: str = ""
    GEMMA_API_KEY: str = ""
    GEMMA_API_MODEL: str = "gemma-4"

    # Legacy — kept for back-compat with older deploys; not used by the
    # backend layer (model is now selected per-backend above).
    GEMMA_MODEL_PATH: str = "/models/gemma4"

    # ── Chat assistant (user-facing LLM, PREMIUM) ────────────────────────────
    # Uses the same backend layer (LLM_BACKEND). Quota metered per user/tier.
    CHAT_ENABLED: bool = True
    CHAT_WINDOW_SECONDS: int = 18000  # quota window (5 hours)
    CHAT_LIMIT_FREE: int = 5  # messages/window for FREE
    CHAT_LIMIT_PRO: int = 100  # messages/window for PRO
    CHAT_LIMIT_PREMIUM: int = 0  # PREMIUM/ADMIN: 0 = unlimited
    CHAT_MAX_INPUT_CHARS: int = 2000  # per user message
    CHAT_MAX_HISTORY: int = 20  # context turns kept
    CHAT_MAX_TOKENS: int = 1024  # model output cap
    CHAT_TEMPERATURE: float = 0.7
    CHAT_TIMEOUT_SECONDS: int = 60

    def chat_limit_for_tier(self, tier: str) -> int:
        """Per-window message quota for a tier (0 = unlimited)."""
        return {
            "FREE": self.CHAT_LIMIT_FREE,
            "PRO": self.CHAT_LIMIT_PRO,
            "PREMIUM": self.CHAT_LIMIT_PREMIUM,
            "ADMIN": 0,
        }.get(tier.upper(), self.CHAT_LIMIT_FREE)

    def vllm_model(self) -> str:
        """Resolved vLLM model id (HF id or local path)."""
        return self.VLLM_MODEL or f"google/gemma-4-{self.GEMMA_MODEL_VARIANT.upper()}-it"

    def ollama_model(self) -> str:
        """Resolved Ollama model tag."""
        return self.OLLAMA_MODEL or f"gemma4:{self.GEMMA_MODEL_VARIANT.lower()}"

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
