"""
Model registry: loads XGBoost and Random Forest from disk, serves predictions.
Supports hot-swap via is_production flag in the ml_models DB table.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from threading import Lock

import numpy as np

from ml.core.config import ml_settings

logger = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(self):
        self._xgb = None
        self._rf = None
        self._lock = Lock()
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def load(self, model_dir: Path | None = None) -> None:
        """Load latest production models from disk."""
        if model_dir is None:
            model_dir = Path(ml_settings.MODEL_DIR)
        with self._lock:
            xgb_path = model_dir / "xgboost_prod.pkl"
            rf_path = model_dir / "rf_prod.pkl"

            if xgb_path.exists():
                with open(xgb_path, "rb") as f:
                    self._xgb = pickle.load(f)
                logger.info("XGBoost model loaded from %s", xgb_path)
            else:
                logger.warning("XGBoost model not found at %s", xgb_path)

            if rf_path.exists():
                with open(rf_path, "rb") as f:
                    self._rf = pickle.load(f)
                logger.info("Random Forest model loaded from %s", rf_path)
            else:
                logger.warning("Random Forest model not found at %s", rf_path)
            self._loaded = True

    def predict_xgb(self, ticker: str, features: dict[str, float]) -> float | None:
        self._ensure_loaded()
        if self._xgb is None:
            return None
        try:
            x = np.array([[features.get(k, np.nan) for k in self._feature_names()]])
            prob = self._xgb.predict_proba(x)[0][1]
            return round(float(prob), 4)
        except Exception as e:
            logger.error("XGBoost prediction failed for %s: %s", ticker, e)
            return None

    def predict_rf(self, ticker: str, features: dict[str, float]) -> float | None:
        self._ensure_loaded()
        if self._rf is None:
            return None
        try:
            x = np.array([[features.get(k, np.nan) for k in self._feature_names()]])
            x = np.nan_to_num(x, nan=0.0)
            prob = self._rf.predict_proba(x)[0][1]
            return round(float(prob), 4)
        except Exception as e:
            logger.error("RF prediction failed for %s: %s", ticker, e)
            return None

    def _feature_names(self) -> list[str]:
        # Single source of truth — must match training feature order.
        from ml.models.xgboost_trainer import FEATURE_COLS

        return FEATURE_COLS

    def reload(self, model_dir: Path | None = None) -> None:
        logger.info("Hot-reloading models from %s", model_dir)
        self.load(model_dir)


model_registry = ModelRegistry()
