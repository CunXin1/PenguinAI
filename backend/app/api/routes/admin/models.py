from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tier

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))

_MODEL_DIR = Path("/models/penguinai")
_MODEL_FILES = [
    ("xgboost", "xgboost_prod.pkl"),
    ("random_forest", "rf_prod.pkl"),
]


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024  # type: ignore[assignment]
    return f"{nbytes:.1f} TB"


@router.get("/performance")
async def model_performance(
    db: Annotated[AsyncSession, Depends(get_db)],
    _=AdminUser,
):
    """Model file info, signal distribution, and feature importance."""
    # 1. Model file metadata
    models_info = []
    for name, filename in _MODEL_FILES:
        path = _MODEL_DIR / filename
        entry: dict = {
            "name": name,
            "file_path": str(path),
            "exists": path.exists(),
            "size_bytes": None,
            "size_human": None,
            "last_modified": None,
        }
        if path.exists():
            stat = path.stat()
            entry["size_bytes"] = stat.st_size
            entry["size_human"] = _human_size(stat.st_size)
            entry["last_modified"] = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()
        models_info.append(entry)

    # 2. Feature importance from the pickled XGBoost model
    feature_importance: dict[str, float] = {}
    xgb_path = _MODEL_DIR / "xgboost_prod.pkl"
    if xgb_path.exists():
        try:
            import pickle

            with open(xgb_path, "rb") as f:
                model = pickle.load(f)  # noqa: S301
            if hasattr(model, "get_score"):
                raw = model.get_score(importance_type="gain")
                total = sum(raw.values()) or 1
                feature_importance = {
                    k: round(v / total, 4) for k, v in sorted(raw.items(), key=lambda x: -x[1])[:15]
                }
            elif hasattr(model, "feature_importances_"):
                import numpy as np

                names = getattr(model, "feature_names_in_", None)
                imp = model.feature_importances_
                if names is not None:
                    pairs = sorted(zip(names, imp), key=lambda x: -x[1])[:15]
                    feature_importance = {k: round(float(v), 4) for k, v in pairs}
        except Exception:
            pass

    # 3. Signal distribution from signal_cache
    signal_dist: dict = {"total": 0, "by_direction": {}, "avg_confidence": None}
    try:
        result = await db.execute(
            text("""
                SELECT
                    direction,
                    count(*) AS cnt,
                    avg(confidence) AS avg_conf
                FROM signal_cache
                GROUP BY direction
            """)
        )
        rows = result.mappings().all()
        total = 0
        by_dir = {}
        conf_sum = 0.0
        for row in rows:
            cnt = int(row["cnt"])
            total += cnt
            by_dir[row["direction"]] = cnt
            conf_sum += float(row["avg_conf"] or 0) * cnt

        signal_dist = {
            "total": total,
            "by_direction": by_dir,
            "avg_confidence": round(conf_sum / total, 3) if total > 0 else None,
        }
    except Exception:
        pass

    return {
        "models": models_info,
        "feature_importance": feature_importance,
        "signal_distribution": signal_dist,
    }
