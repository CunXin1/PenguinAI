"""Train per-basket, per-horizon specialized models (roadmap B1/B2).

For each basket (ml/models/baskets.py) and each horizon below, trains an XGBoost and a
Random Forest on the basket's pooled rows and saves them under MODEL_DIR keyed as
    {basket}__{timeframe}__{label}__{algo}.pkl     e.g. nasdaq10__30m__1w__xgb.pkl

Horizons built now (1-day is intentionally deferred — it will run on 1-min / aggregated
10-min bars once that data is ready):
    1w  -> 30-min bars, 65 bars ahead (~1 week),  direction (up/down)
    1m  -> daily bars,  21 days ahead (~1 month),  beat_spy (excess vs SPY)
    3m  -> daily bars,  63 days ahead (~3 months), beat_spy

Usage:
    python ml/scripts/train_basket_models.py                       # all baskets, all horizons
    python ml/scripts/train_basket_models.py --basket nasdaq10
    python ml/scripts/train_basket_models.py --horizon 1w --horizon 1m
    python ml/scripts/train_basket_models.py --model-dir /tmp/models   # override output dir
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ml.core.config import ml_settings
from ml.models import rf_trainer, xgboost_trainer
from ml.models.baskets import BASKETS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# (label, timeframe, horizon_bars, target_type)
HORIZONS: list[tuple[str, str, int, str]] = [
    ("1w", "30m", 65, "direction"),
    ("1m", "1d", 21, "beat_spy"),
    ("3m", "1d", 63, "beat_spy"),
]

ALGOS = (("xgb", xgboost_trainer), ("rf", rf_trainer))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--basket", action="append", help="Limit to these baskets (repeatable).")
    p.add_argument("--horizon", action="append", help="Limit to these horizon labels (repeatable).")
    p.add_argument("--model-dir", default=ml_settings.MODEL_DIR, help="Output dir for pkls.")
    args = p.parse_args()

    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    basket_names = args.basket or list(BASKETS)
    horizons = [h for h in HORIZONS if (not args.horizon or h[0] in args.horizon)]

    rows: list[tuple[str, str, str, float, int]] = []
    for bname in basket_names:
        tickers = BASKETS[bname]
        for label, tf, horizon_bars, target in horizons:
            for algo, mod in ALGOS:
                out = model_dir / f"{bname}__{tf}__{label}__{algo}.pkl"
                logger.info("=== %s | %s %s (%s, h=%d, %s) ===", bname, label, algo, tf, horizon_bars, target)
                metrics = mod.train(
                    tickers=tickers,
                    horizon_bars=horizon_bars,
                    timeframe=tf,
                    target_type=target,
                    output_path=out,
                )
                rows.append((bname, label, algo, metrics["mean_cv_auc"], metrics["n_samples"]))

    print("\n=== summary (purged walk-forward CV AUC) ===")
    print(f"{'basket':<10} {'horizon':<8} {'algo':<5} {'cv_auc':>8} {'samples':>10}")
    for bname, label, algo, auc, n in rows:
        print(f"{bname:<10} {label:<8} {algo:<5} {auc:>8.4f} {n:>10,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
