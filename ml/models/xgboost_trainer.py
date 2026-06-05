"""
XGBoost trainer for price direction classification.
Target: will close be higher N bars from now? (binary classification)
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_pct_b",
    "bb_width",
    "atr_14_pct",
    "ema20_slope",
    "price_vs_sma200",
    "volume_ratio",
    "vwap_pct",
]


def load_training_data(
    db_path: str,
    tickers: list[str] | None = None,
    horizon_bars: int = 16,  # 16 × 30min = 8 hours ahead
    since: str = "2015-01-01",
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Load feature matrix X and binary target y from DuckDB (Parquet-backed).
    Uses 30-min indicator data joined with forward return.
    """
    con = duckdb.connect(db_path, read_only=True)

    ticker_filter = f"AND ticker IN ({','.join(repr(t) for t in tickers)})" if tickers else ""

    query = f"""
        WITH bars AS (
            SELECT
                i.*,
                m.close,
                LEAD(m.close, {horizon_bars}) OVER (PARTITION BY i.ticker ORDER BY i.time) AS future_close
            FROM indicators_30min i
            JOIN market_data_30min m USING (ticker, time)
            WHERE i.time >= '{since}' {ticker_filter}
              AND m.adjusted = TRUE
        )
        SELECT
            {", ".join(FEATURE_COLS)},
            (future_close > close)::INT AS target
        FROM bars
        WHERE future_close IS NOT NULL
    """
    df = con.execute(query).df()
    con.close()

    X = df[FEATURE_COLS]
    y = df["target"]
    return X, y


def train(
    db_path: str,
    output_path: Path,
    tickers: list[str] | None = None,
    horizon_bars: int = 16,
) -> dict:
    logger.info("Loading training data...")
    X, y = load_training_data(db_path, tickers=tickers, horizon_bars=horizon_bars)
    logger.info("Dataset: %d samples, %.1f%% positive", len(X), y.mean() * 100)

    model = XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        use_label_encoder=False,
        eval_metric="auc",
        tree_method="hist",
        device="cuda",  # uses 4090
        n_jobs=-1,
        random_state=42,
        early_stopping_rounds=50,
    )

    # Time-series CV (no data leakage)
    tscv = TimeSeriesSplit(n_splits=5)
    auc_scores = []

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        preds = model.predict_proba(X_val)[:, 1]
        auc = roc_auc_score(y_val, preds)
        auc_scores.append(auc)
        logger.info("Fold %d AUC: %.4f", fold + 1, auc)

    mean_auc = float(np.mean(auc_scores))
    logger.info("Mean CV AUC: %.4f", mean_auc)

    # Final fit on full data
    model.fit(X, y, verbose=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(model, f)
    logger.info("Model saved to %s", output_path)

    return {
        "mean_cv_auc": mean_auc,
        "n_samples": len(X),
        "feature_importance": dict(
            zip(FEATURE_COLS, model.feature_importances_.tolist(), strict=False)
        ),
    }
