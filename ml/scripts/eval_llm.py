"""Evaluate a Gemma 4 backend on a battery of synthetic signal scenarios.

Goes beyond the single-shot healthcheck: runs several market setups (bullish,
bearish, neutral, conflicting, sparse) through the full Agent 2 harness and
scores each on:
  - schema conformance (valid enums, confidence in range, length contract)
  - directional sanity (does the call match the setup's expected polarity?)
  - latency (per call)
  - consistency (stable direction across repeated runs)

No DB, no ML models — pure LLM evaluation against a running backend.

Run from repo root (uses the configured backend; macOS auto -> Ollama):
    PYTHONPATH=. python ml/scripts/eval_llm.py --variant e4b
    PYTHONPATH=. python ml/scripts/eval_llm.py --variant e4b --runs 3
    PYTHONPATH=. python ml/scripts/eval_llm.py --variant e4b --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from statistics import median

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

# ── Scenarios ────────────────────────────────────────────────────────────────
# `expect` = directions considered correct for this setup. NEUTRAL is allowed
# wherever the evidence is weak/conflicting, since a cautious model is not wrong.
SCENARIOS = [
    {
        "name": "strong_bullish",
        "expect": {"LONG"},
        "ctx": {
            "xgb_prob_up": 0.82,
            "rf_prob_up": 0.78,
            "finbert_score": 0.55,
            "post_count": 64,
            "hawk_dove_score": -0.5,
            "top_posts": [
                "blowout earnings, guidance raised",
                "multiple analyst upgrades to strong buy",
            ],
            "celebrity_actions": [{"who": "big_fund", "action": "BUY", "date": "2026-06-02"}],
            "earnings_surprise_pct": 14.0,
            "pe_ratio": 22.0,
        },
    },
    {
        "name": "strong_bearish",
        "expect": {"SHORT"},
        "ctx": {
            "xgb_prob_up": 0.18,
            "rf_prob_up": 0.24,
            "finbert_score": -0.5,
            "post_count": 58,
            "hawk_dove_score": 0.6,
            "top_posts": [
                "guidance cut, demand weakening",
                "downgrade to sell on margin compression",
            ],
            "celebrity_actions": [{"who": "big_fund", "action": "SELL", "date": "2026-06-02"}],
            "earnings_surprise_pct": -9.0,
            "pe_ratio": 41.0,
        },
    },
    {
        "name": "neutral_balanced",
        "expect": {"NEUTRAL"},
        "ctx": {
            "xgb_prob_up": 0.51,
            "rf_prob_up": 0.49,
            "finbert_score": 0.03,
            "post_count": 12,
            "hawk_dove_score": 0.0,
            "top_posts": ["mixed reactions, range-bound trading"],
            "celebrity_actions": [],
            "earnings_surprise_pct": 0.5,
            "pe_ratio": 25.0,
        },
    },
    {
        "name": "conflicting_ml_vs_sentiment",
        "expect": {"LONG", "SHORT", "NEUTRAL"},  # any valid call; we check coherence
        "ctx": {
            "xgb_prob_up": 0.74,
            "rf_prob_up": 0.69,
            "finbert_score": -0.45,
            "post_count": 40,
            "hawk_dove_score": 0.55,
            "top_posts": [
                "strong technicals but macro fears",
                "bearish headlines despite solid fundamentals",
            ],
            "celebrity_actions": [],
            "earnings_surprise_pct": 6.0,
            "pe_ratio": 30.0,
        },
    },
    {
        "name": "sparse_data",
        "expect": {"NEUTRAL"},
        "ctx": {
            "xgb_prob_up": None,
            "rf_prob_up": None,
            "finbert_score": None,
            "post_count": 0,
            "hawk_dove_score": None,
            "top_posts": [],
            "celebrity_actions": [],
            "earnings_surprise_pct": None,
            "pe_ratio": None,
        },
    },
]

VALID_DIRECTIONS = {"LONG", "SHORT", "NEUTRAL"}
VALID_PERIODS = {"INTRADAY", "SHORT_TERM", "SWING", "POSITION"}


def _check_schema(out) -> list[str]:
    """Return a list of contract violations (empty = clean)."""
    errs = []
    if out.direction not in VALID_DIRECTIONS:
        errs.append(f"bad direction {out.direction!r}")
    if not (0.0 <= out.confidence <= 1.0):
        errs.append(f"confidence out of range {out.confidence}")
    if out.holding_period not in VALID_PERIODS:
        errs.append(f"bad holding_period {out.holding_period!r}")
    if not out.ai_attribution.strip():
        errs.append("empty ai_attribution")
    if len(out.ai_attribution) > 300:
        errs.append(f"ai_attribution too long ({len(out.ai_attribution)})")
    if not out.ai_analysis.strip():
        errs.append("empty ai_analysis")
    if len(out.ai_analysis) > 600:
        errs.append(f"ai_analysis too long ({len(out.ai_analysis)})")
    return errs


async def _run_scenario(agent, scn, runs):
    results = []
    for _ in range(runs):
        ctx = agent.assemble_context(ticker="EVAL", **scn["ctx"])
        t0 = time.perf_counter()
        try:
            out = await agent.reason(ctx)
            latency = time.perf_counter() - t0
            results.append(
                {
                    "ok": True,
                    "direction": out.direction,
                    "confidence": out.confidence,
                    "holding_period": out.holding_period,
                    "latency": latency,
                    "schema_errs": _check_schema(out),
                    "attribution": out.ai_attribution,
                    "analysis": out.ai_analysis,
                }
            )
        except Exception as e:
            results.append({"ok": False, "error": str(e), "latency": time.perf_counter() - t0})
    return results


def _mode_direction(results) -> str | None:
    dirs = [r["direction"] for r in results if r.get("ok")]
    if not dirs:
        return None
    return max(set(dirs), key=dirs.count)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Eval a Gemma backend on synthetic scenarios")
    parser.add_argument("--variant", help="override GEMMA_MODEL_VARIANT (e.g. e4b)")
    parser.add_argument("--backend", help="override LLM_BACKEND (ollama|vllm|api)")
    parser.add_argument("--runs", type=int, default=1, help="repeats per scenario (consistency)")
    parser.add_argument("--json", action="store_true", help="dump raw results as JSON")
    args = parser.parse_args()

    from ml.core.config import ml_settings
    from ml.inference.llm import get_llm_backend, reset_llm_backend

    if args.variant:
        ml_settings.GEMMA_MODEL_VARIANT = args.variant
    if args.backend:
        ml_settings.LLM_BACKEND = args.backend
    reset_llm_backend()

    from ml.inference.gemma_agent import GemmaAgent

    backend = get_llm_backend()
    agent = GemmaAgent(backend=backend)

    print("=== Gemma eval ===")
    print(f"backend : {backend.name}")
    print(f"model   : {backend.model_id()}")
    print(f"runs    : {args.runs} per scenario\n")

    if not await backend.health():
        print("Backend not reachable — start it first (ml/serving/start_ollama.sh).")
        return 1

    all_results = {}
    n_scen_pass = 0
    schema_clean = 0
    schema_total = 0
    latencies: list[float] = []

    for scn in SCENARIOS:
        results = await _run_scenario(agent, scn, args.runs)
        all_results[scn["name"]] = results

        oks = [r for r in results if r.get("ok")]
        mode = _mode_direction(results)
        dir_pass = mode in scn["expect"] if mode else False
        consistent = len({r["direction"] for r in oks}) <= 1 if oks else False

        for r in oks:
            schema_total += 1
            if not r["schema_errs"]:
                schema_clean += 1
            latencies.append(r["latency"])

        if dir_pass and all(not r["schema_errs"] for r in oks) and oks:
            n_scen_pass += 1
            verdict = "PASS"
        else:
            verdict = "FAIL"

        conf = median([r["confidence"] for r in oks]) if oks else float("nan")
        lat = median([r["latency"] for r in oks]) if oks else float("nan")
        exp = "/".join(sorted(scn["expect"]))
        print(
            f"[{verdict}] {scn['name']:<28} dir={mode or 'ERR':<7} (exp {exp:<18}) "
            f"conf={conf:.2f}  med_lat={lat:5.1f}s  "
            f"{'consistent' if consistent or args.runs == 1 else 'VARIES'}"
        )
        # Show one sample analysis per scenario for eyeballing quality.
        if oks:
            print(f"        attr: {oks[0]['attribution'][:110]}")

    print("\n--- summary ---")
    print(f"scenarios passed   : {n_scen_pass}/{len(SCENARIOS)}")
    print(f"schema-clean calls : {schema_clean}/{schema_total}")
    if latencies:
        latencies.sort()
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        print(f"latency med/p95    : {median(latencies):.1f}s / {p95:.1f}s")

    if args.json:
        print("\n" + json.dumps(all_results, indent=2, default=str))

    # Exit non-zero if any scenario failed or any schema violation occurred.
    return 0 if (n_scen_pass == len(SCENARIOS) and schema_clean == schema_total) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
