"""
Text embedder using sentence-transformers (MiniLM-L6, 384-dim).
Used for both indexing social posts and RAG query embedding.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from ml.core.config import ml_settings


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    return SentenceTransformer(ml_settings.EMBEDDING_MODEL)


class Embedder:
    def __init__(self):
        self._model = None

    def _ensure_loaded(self):
        if self._model is None:
            self._model = _load_model()

    def encode(self, text: str) -> np.ndarray:
        self._ensure_loaded()
        return self._model.encode(text, normalize_embeddings=True)

    def encode_batch(self, texts: list[str]) -> np.ndarray:
        self._ensure_loaded()
        return self._model.encode(
            texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False
        )


embedder = Embedder()
