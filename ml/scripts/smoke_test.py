"""Quick smoke test: run SignalEngine.compute() for a ticker and print result.

Verifies the full pipeline works end-to-end. Gracefully degrades if Gemma,
FinBERT, or database tables are empty.

Run from repo root:
    PYTHONPATH=. python ml/scripts/smoke_test.py
    PYTHONPATH=. python ml/scripts/smoke_test.py --ticker MSFT
    PYTHONPATH=. python ml/scripts/smoke_test.py --mock  # no DB needed
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def run_with_db(ticker: str) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ml.core.config import ml_settings
    from ml.inference.signal_engine import signal_engine

    engine = create_async_engine(ml_settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        result = await signal_engine.compute(ticker, db)

    await engine.dispose()
    return result


async def run_with_mock(ticker: str) -> dict:
    from unittest.mock import AsyncMock

    from ml.inference.signal_engine import signal_engine

    mock_session = AsyncMock()

    mock_result = AsyncMock()
    mock_result.mappings.return_value.first.return_value = None
    mock_result.scalar_one_or_none.return_value = None
    mock_result.all.return_value = []
    mock_session.execute.return_value = mock_result

    return await signal_engine.compute(ticker, mock_session)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test SignalEngine")
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--mock", action="store_true", help="Use mock DB session (no DB needed)")
    args = parser.parse_args()

    print(f"\n=== Smoke Test: {args.ticker} (mock={args.mock}) ===\n")

    if args.mock:
        result = asyncio.run(run_with_mock(args.ticker))
    else:
        result = asyncio.run(run_with_db(args.ticker))

    for k, v in result.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()

    print(json.dumps(result, indent=2, default=str))
    print(f"\nSignal: {result['direction']} @ {result['confidence']} confidence")
    print(f"Holding: {result['holding_period']}")
    print(f"ML: xgb={result['xgb_prob_up']}, rf={result['rf_prob_up']}, ensemble={result['ensemble_prob']}")
    print(f"Sentiment: finbert={result['finbert_score']}, posts={result['post_count']}")
    print(f"Analysis: {result['ai_analysis']}")


if __name__ == "__main__":
    main()
