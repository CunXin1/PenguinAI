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
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """
    Load feature matrix X and binary target y straight from the 30-min parquet
    (one file per symbol, RTH rows, with precomputed indicators). Features are
    derived in SQL via FEATURE_SQL — identical to the indicators_30min view.

    Target: will adj_close be higher `horizon_bars` RTH bars from now?

    Returns (X, y, cv_meta) where cv_meta carries the per-row `ts` and
    `label_end_ts` (= the timestamp of the bar the label looks ahead to). Rows are
    globally ORDER BY ts so a walk-forward split sees real time blocks, and cv_meta
    lets `purged_walk_forward_splits` drop train rows whose label window overlaps the
    validation block (removes the overlapping-label leakage).
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
                ts,
                {feat_select},
                adj_close,
                LEAD(adj_close, {horizon_bars}) OVER (PARTITION BY symbol ORDER BY ts) AS future_close,
                LEAD(ts, {horizon_bars}) OVER (PARTITION BY symbol ORDER BY ts) AS label_end_ts
            FROM read_parquet({glob_literal}, union_by_name=true)
            WHERE rth AND ts >= TIMESTAMP '{since}' {ticker_filter}
        )
        SELECT
            ts,
            label_end_ts,
            {", ".join(FEATURE_COLS)},
            (future_close > adj_close)::INT AS target
        FROM bars
        WHERE future_close IS NOT NULL
        ORDER BY ts
    """
    con = duckdb.connect()
    df = con.execute(query).df()
    con.close()

    X = df[FEATURE_COLS].reset_index(drop=True)
    y = df["target"].reset_index(drop=True)
    cv_meta = df[["ts", "label_end_ts"]].reset_index(drop=True)
    return X, y, cv_meta


def purged_walk_forward_splits(cv_meta: pd.DataFrame, n_splits: int = 5):
    """Expanding-window walk-forward CV that PURGES the overlapping-label leakage.

    Rows must be time-sorted (load_training_data does ORDER BY ts). The timeline is
    cut into ``n_splits + 1`` contiguous blocks; fold k trains on blocks[:k] and
    validates on block k. A train row is dropped when its label window (which ends at
    ``label_end_ts``) reaches the validation block's start — i.e. when the label peeks
    into the future being validated. This replaces sklearn's plain TimeSeriesSplit,
    which (a) split pooled multi-symbol rows by position, not time, and (b) left the
    `horizon_bars`-overlap leak at every train/val boundary.

    Yields (train_idx, val_idx) positional index arrays into the sorted frame.
    """
    ts = cv_meta["ts"].to_numpy()
    label_end = cv_meta["label_end_ts"].to_numpy()
    n = len(ts)
    blocks = np.array_split(np.arange(n), n_splits + 1)
    for k in range(1, n_splits + 1):
        val_idx = blocks[k]
        if len(val_idx) == 0:
            continue
        val_start = ts[val_idx[0]]
        train_pool = np.concatenate(blocks[:k])
        # keep only train rows whose label fully precedes the validation block
        train_idx = train_pool[label_end[train_pool] < val_start]
        if len(train_idx) == 0:
            continue
        yield train_idx, val_idx


def train(
    parquet_root: str | Path = DEFAULT_PARQUET_ROOT,
    output_path: Path | None = None,
    tickers: list[str] | None = None,
    horizon_bars: int = 16,
) -> dict:
    if output_path is None:
        from ml.core.config import ml_settings
        output_path = Path(ml_settings.MODEL_DIR) / "xgboost_prod.pkl"

    logger.info("Loading training data...")
    X, y, cv_meta = load_training_data(parquet_root, tickers=tickers, horizon_bars=horizon_bars)
    logger.info("Dataset: %d samples, %.1f%% positive", len(X), y.mean() * 100)

    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "cpu"

    model = XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="auc",
        tree_method="hist",
        device=device,
        n_jobs=-1,
        random_state=42,
        early_stopping_rounds=50,
    )

    # Purged walk-forward CV (time-blocked + overlapping-label embargo; no leakage)
    auc_scores = []

    for fold, (train_idx, val_idx) in enumerate(purged_walk_forward_splits(cv_meta, n_splits=5)):
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

    # Final fit on full data (disable early stopping — no eval_set)
    model.set_params(early_stopping_rounds=None)
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
