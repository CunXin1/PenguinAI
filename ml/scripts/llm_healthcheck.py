"""LLM backend health + end-to-end Agent 2 check.

Resolves the configured backend (vLLM / Ollama / API), pings it, then runs the
full Gemma agent harness on a synthetic context so the JSON-schema-locked
output path is exercised. No DB, no models, no network beyond the LLM server.

Run from repo root:
    PYTHONPATH=. python ml/scripts/llm_healthcheck.py
"""

import asyncio
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> int:
    from ml.core.config import ml_settings
    from ml.inference.gemma_agent import gemma_agent
    from ml.inference.llm import get_llm_backend

    backend = get_llm_backend()
    print("\n=== LLM healthcheck ===")
    print(f"backend  : {backend.name}")
    print(f"model    : {backend.model_id()}")
    print(f"variant  : {ml_settings.GEMMA_MODEL_VARIANT}")

    ok = await backend.health()
    print(f"reachable: {ok}")
    if not ok:
        print("\n❌ Backend not reachable. Start it first:")
        print("   macOS  : ml/serving/start_ollama.sh")
        print("   Windows: ml/serving/start_vllm.ps1")
        print("   Linux  : ml/serving/start_vllm.sh")
        return 1

    # Synthetic context — a clearly bullish setup, to confirm reasoning + schema.
    context = gemma_agent.assemble_context(
        ticker="DEMO",
        xgb_prob_up=0.78,
        rf_prob_up=0.71,
        finbert_score=0.42,
        post_count=37,
        hawk_dove_score=-0.4,
        top_posts=["DEMO crushed earnings, guidance raised", "analysts upgrade DEMO to buy"],
        celebrity_actions=[{"who": "demo_fund", "action": "BUY", "date": "2026-06-01"}],
        earnings_surprise_pct=12.5,
        pe_ratio=24.0,
    )

    print("\nRunning Agent 2 (this calls the model)...")
    out = await gemma_agent.reason(context)
    print(json.dumps(out.__dict__, indent=2))
    print(f"\n✅ End-to-end OK — {out.direction} @ {out.confidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
