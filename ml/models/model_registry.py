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


# Per-basket horizon models (built by ml/scripts/train_basket_models.py), keyed
# {basket}__{tf}__{label}__{algo}.pkl. label → timeframe whose feature dict to use.
# 1w predicts P(price up); 1m/3m predict P(beat SPY) — different targets, so the
# synthesis layer must interpret them accordingly (both >0.5 = bullish lean).
_BASKET_HORIZONS: dict[str, str] = {"1w": "30m", "1m": "1d", "3m": "1d"}
_HORIZON_TARGET: dict[str, str] = {"1w": "direction", "1m": "beat_spy", "3m": "beat_spy"}


class ModelRegistry:
    def __init__(self):
        self._xgb = None
        self._rf = None
        self._basket_models: dict[str, object | None] = {}
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

    # ── Per-basket × horizon models ───────────────────────────────────────────
    def _load_basket_model(self, key: str) -> object | None:
        """Lazily load + cache a basket model pkl (None when the file is absent)."""
        if key in self._basket_models:
            return self._basket_models[key]
        path = Path(ml_settings.MODEL_DIR) / f"{key}.pkl"
        model: object | None = None
        if path.exists():
            try:
                with open(path, "rb") as f:
                    model = pickle.load(f)
                logger.info("basket model loaded: %s", key)
            except Exception as e:  # noqa: BLE001
                logger.error("failed to load basket model %s: %s", key, e)
        self._basket_models[key] = model
        return model

    def _predict_model(self, model: object | None, features: dict, fill_nan: bool) -> float | None:
        """Predict P(up) with a model using its OWN saved feature order."""
        if model is None:
            return None
        try:
            names = [str(k) for k in getattr(model, "feature_names_in_", [])] or self._feature_names()
            x = np.array([[features.get(k, np.nan) for k in names]], dtype=float)
            if fill_nan:
                x = np.nan_to_num(x, nan=0.0)
            return round(float(model.predict_proba(x)[0][1]), 4)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            logger.error("basket prediction failed: %s", e)
            return None

    def predict_basket_horizons(
        self, ticker: str, feats_by_tf: dict[str, dict[str, float]]
    ) -> dict[str, dict]:
        """Multi-horizon ensemble probs for `ticker` from its basket models.

        feats_by_tf maps timeframe ("30m" / "1d") → feature dict. Returns
        {label: {"xgb", "rf", "ensemble", "target"}} for each horizon whose model
        exists; empty dict when the ticker is in no basket (→ global model only).
        """
        from ml.models.baskets import basket_for

        basket = basket_for(ticker)
        if basket is None:
            return {}
        out: dict[str, dict] = {}
        for label, tf in _BASKET_HORIZONS.items():
            feats = feats_by_tf.get(tf)
            if not feats:
                continue
            xgb = self._predict_model(self._load_basket_model(f"{basket}__{tf}__{label}__xgb"), feats, False)
            rf = self._predict_model(self._load_basket_model(f"{basket}__{tf}__{label}__rf"), feats, True)
            if xgb is None and rf is None:
                continue
            if xgb is not None and rf is not None:
                ensemble = round(xgb * 0.6 + rf * 0.4, 4)
            else:
                ensemble = xgb if xgb is not None else rf
            out[label] = {"xgb": xgb, "rf": rf, "ensemble": ensemble, "target": _HORIZON_TARGET[label]}
        return out

    def reload(self, model_dir: Path | None = None) -> None:
        logger.info("Hot-reloading models from %s", model_dir)
        self._basket_models.clear()
        self.load(model_dir)


model_registry = ModelRegistry()
