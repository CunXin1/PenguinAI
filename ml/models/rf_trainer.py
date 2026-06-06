"""
Random Forest trainer — complementary to XGBoost for ensemble diversity.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from ml.models.xgboost_trainer import DEFAULT_PARQUET_ROOT, load_training_data

logger = logging.getLogger(__name__)


def train(
    parquet_root: str | Path = DEFAULT_PARQUET_ROOT,
    output_path: Path = Path("/models/penguinai/rf_prod.pkl"),
    tickers: list[str] | None = None,
    horizon_bars: int = 16,
) -> dict:
    logger.info("Loading training data for Random Forest...")
    X, y = load_training_data(parquet_root, tickers=tickers, horizon_bars=horizon_bars)

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=10,
        min_samples_leaf=50,
        n_jobs=-1,
        random_state=42,
        class_weight="balanced",
    )

    tscv = TimeSeriesSplit(n_splits=5)
    auc_scores = []

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
        model.fit(X_train.fillna(0), y_train)
        preds = model.predict_proba(X_val.fillna(0))[:, 1]
        auc = roc_auc_score(y_val, preds)
        auc_scores.append(auc)
        logger.info("Fold %d AUC: %.4f", fold + 1, auc)

    mean_auc = float(np.mean(auc_scores))
    logger.info("Mean CV AUC: %.4f", mean_auc)

    model.fit(X.fillna(0), y)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(model, f)
    logger.info("RF model saved to %s", output_path)

    return {"mean_cv_auc": mean_auc, "n_samples": len(X)}
