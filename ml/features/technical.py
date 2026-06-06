"""Map a precomputed ``indicators_30min`` row to the model feature vector.

Indicators (and the scale-free derived features the model consumes) are
precomputed in the 30-min parquet pipeline and exposed by the
``indicators_30min`` view — see db/schema/04_compat_views.sql and
``ml/models/xgboost_trainer.FEATURE_SQL``. Inference therefore no longer
recomputes anything with pandas-ta; it selects FEATURE_COLS straight from the
view, guaranteeing the exact same feature definitions training saw.
"""

from __future__ import annotations

import numpy as np

from ml.models.xgboost_trainer import FEATURE_COLS


def features_to_dict(row: dict | None) -> dict[str, float]:
    """Flatten a feature row (FEATURE_COLS → value) to NaN-filled floats for the models."""
    row = row or {}
    return {
        k: (float(row[k]) if row.get(k) is not None else np.nan) for k in FEATURE_COLS
    }
