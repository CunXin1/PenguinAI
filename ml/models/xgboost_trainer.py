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

# Repo-root parquet (the real 30-min data with precomputed indicators).
DEFAULT_PARQUET_ROOT = Path(__file__).resolve().parents[2] / "data" / "30min_data"

# The model's input features. Order here IS the on-wire order (model_registry
# builds the inference vector from this list).
FEATURE_COLS = [
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_pct_b",
    "bb_width",
    "atr_14_pct",
    "price_vs_sma200",
    "price_vs_ema50",
    "vwap_pct",
    "ret_1bar",
]

# SQL that derives each FEATURE_COL from the raw parquet / bars_30m columns.
# MUST stay byte-for-byte equivalent to db/schema/04_compat_views.sql
# (indicators_30min) so training (DuckDB over parquet) and serving (the Postgres
# view) compute identical features — no train/serve skew.
FEATURE_SQL: dict[str, str] = {
    "rsi_14": "rsi_14",
    "macd": "macd",
    "macd_signal": "macd_signal",
    "macd_hist": "macd_hist",
    "bb_pct_b": "bb_pctb",
    "bb_width": "bb_bw",
    "atr_14_pct": "atr_14 / NULLIF(adj_close, 0)",
    "price_vs_sma200": "adj_close / NULLIF(sma_200, 0) - 1",
    "price_vs_ema50": "adj_close / NULLIF(ema_50, 0) - 1",
    "vwap_pct": "(adj_close - vwap_day) / NULLIF(vwap_day, 0)",
    "ret_1bar": "ret_1bar",
}


def load_training_data(
    parquet_root: str | Path = DEFAULT_PARQUET_ROOT,
    tickers: list[str] | None = None,
    horizon_bars: int = 16,  # 16 RTH 30-min bars ahead (~1.2 trading days)
    since: str = "2015-01-01",
    scope: str = "all",  # 'all' | 'stock' | 'etf'
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Load feature matrix X and binary target y straight from the 30-min parquet
    (one file per symbol, RTH rows, with precomputed indicators). Features are
    derived in SQL via FEATURE_SQL — identical to the indicators_30min view.

    Target: will adj_close be higher `horizon_bars` RTH bars from now?
    """
    assets = ["stock", "etf"] if scope == "all" else [scope]
    globs = [str(Path(parquet_root) / a / "*.parquet") for a in assets]
    glob_literal = "[" + ", ".join(f"'{g}'" for g in globs) + "]"

    feat_select = ",\n                ".join(f"{expr} AS {name}" for name, expr in FEATURE_SQL.items())
    ticker_filter = (
        "AND symbol IN (" + ",".join(repr(t) for t in tickers) + ")" if tickers else ""
    )

    query = f"""
        WITH bars AS (
            SELECT
                {feat_select},
                adj_close,
                LEAD(adj_close, {horizon_bars}) OVER (PARTITION BY symbol ORDER BY ts) AS future_close
            FROM read_parquet({glob_literal}, union_by_name=true)
            WHERE rth AND ts >= TIMESTAMP '{since}' {ticker_filter}
        )
        SELECT
            {", ".join(FEATURE_COLS)},
            (future_close > adj_close)::INT AS target
        FROM bars
        WHERE future_close IS NOT NULL
    """
    con = duckdb.connect()
    df = con.execute(query).df()
    con.close()

    X = df[FEATURE_COLS]
    y = df["target"]
    return X, y


def train(
    parquet_root: str | Path = DEFAULT_PARQUET_ROOT,
    output_path: Path = Path("/models/penguinai/xgboost_prod.pkl"),
    tickers: list[str] | None = None,
    horizon_bars: int = 16,
) -> dict:
    logger.info("Loading training data...")
    X, y = load_training_data(parquet_root, tickers=tickers, horizon_bars=horizon_bars)
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
