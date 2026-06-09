"""Train initial XGBoost + RF models from parquet data.

Run from repo root:
    PYTHONPATH=. python ml/scripts/train_initial_models.py
"""

import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARQUET_ROOT = PROJECT_ROOT / "data" / "30min_data"


def main() -> None:
    from ml.models.rf_trainer import train as train_rf
    from ml.models.xgboost_trainer import train as train_xgb

    if not PARQUET_ROOT.exists():
        print(f"ERROR: {PARQUET_ROOT} does not exist.")
        print("Run: python -m data.ingestion.massive_30min_parquet")
        print("Then: python -m backend.scripts.market_data.compute_indicators --by-symbol-root data/30min_data")
        return

    parquets = list(PARQUET_ROOT.rglob("*.parquet"))
    print(f"Found {len(parquets)} parquet files in {PARQUET_ROOT}")
    if not parquets:
        print("ERROR: no parquet files found")
        return

    print("\n=== Training XGBoost ===")
    try:
        xgb_metrics = train_xgb(parquet_root=PARQUET_ROOT)
        print(f"XGBoost done: {xgb_metrics}")
    except Exception as e:
        print(f"XGBoost training failed: {e}")
        xgb_metrics = None

    print("\n=== Training Random Forest ===")
    try:
        rf_metrics = train_rf(parquet_root=PARQUET_ROOT)
        print(f"RF done: {rf_metrics}")
    except Exception as e:
        print(f"RF training failed: {e}")
        rf_metrics = None

    print("\n=== Summary ===")
    if xgb_metrics:
        print(f"XGBoost CV AUC: {xgb_metrics['mean_cv_auc']:.4f} ({xgb_metrics['n_samples']} samples)")
        print("Feature importance:")
        for feat, imp in sorted(xgb_metrics["feature_importance"].items(), key=lambda x: -x[1]):
            print(f"  {feat:20s} {imp:.4f}")
    if rf_metrics:
        print(f"RF CV AUC: {rf_metrics['mean_cv_auc']:.4f} ({rf_metrics['n_samples']} samples)")


if __name__ == "__main__":
    main()
