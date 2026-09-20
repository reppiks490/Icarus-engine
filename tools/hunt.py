"""Goal-directed hill climb over pulse.py's inputs.

Random sampling across 185 dimensions is a poor way to hit a specific target.
This climbs instead: start from several seeds, perturb a handful of inputs, keep
what improves the goal score on the TUNING tape, and only then check the result
against HELD-OUT data it was never optimised on.

The separation matters. Climbing on held-out data would make the held-out number
meaningless -- it would just be a second tuning tape with extra steps. Every
accept/reject decision here uses the tuning tape alone.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.goal import GOAL, TARGET_COUNT
from tools.sweep_pulse import (
    CONTEXTS, FROZEN, TAPES, VIDEO_ANCHOR, PulseVariant, _sample_numeric, evaluate, load_meta,
)

# Earlier runs put 80-86% win rates under ATR-Based and 52-56% under
# Structure-Based, so the climb starts where the target actually lives.
SEEDS = [
    {"tpsl_mode": "ATR-Based"},
    {"tpsl_mode": "ATR-Based", "sl_atr_mult": 5.5, "tp1_atr_mult": 2.5},
    {"tpsl_mode": "ATR-Based", "use_trailing_tp2": True, "trail_atr_mult": 2.0},
    {"tpsl_mode": "ATR-Based", "conf_min_votes": 6},
    {"tpsl_mode": "ATR-Based", "conf_min_votes": 8, "sl_atr_mult": 4.0},
    {"tpsl_mode": "Structure-Based"},
]


def neighbour(overrides: dict, meta: list[dict], rng: random.Random, width: int = 3) -> dict:
    """One step: perturb a few inputs, leaving the rest of the point intact."""
    by_name = {e["name"]: e for e in meta}
    candidates = [e["name"] for e in meta if e["name"] not in FROZEN]
    out = dict(overrides)
    for name in rng.sample(candidates, width):
        entry = by_name[name]
        kind = entry["kind"]
        if kind == "bool":
            out[name] = not out.get(name, entry["default"])
        elif kind in ("float", "int"):
            out[name] = _sample_numeric(entry, rng, out.get(name, entry["default"]))
        elif kind in ("string", "timeframe") and entry.get("options"):
            out[name] = rng.choice(entry["options"])
    return out


def _eval_worker(payload):
    variant, key = payload
    try:
        return variant, evaluate(variant, key)
    except Exception as exc:
        return variant, {"error": f"{type(exc).__name__}: {exc}", "trades": 0}


def climb(timeframes, meta, *, iterations: int, width: int, workers: int,
          rng: random.Random, log=print) -> list[tuple[PulseVariant, dict]]:
    """Parallel multi-start climb. Returns every point that cleared the goal on tune."""
    population = []
    for seed in SEEDS:
        for tf in timeframes:
            population.append(PulseVariant(tf, {**VIDEO_ANCHOR, **seed}))

    with mp.Pool(workers) as pool:
        scored = pool.map(_eval_worker, [(v, "tune") for v in population], chunksize=1)
        best = [(v, r) for v, r in scored if "error" not in r]
        best.sort(key=lambda x: -GOAL.score(x[1]))
        best = best[:workers * 3]
        log(f"  start: {len(best)} live points, best win "
            f"{max((r['win_rate'] for _, r in best), default=0):.1f}%")

        for step in range(iterations):
            trials = []
            for variant, _ in best:
                for _ in range(3):
                    trials.append(PulseVariant(variant.timeframe,
                                               neighbour(variant.overrides, meta, rng, width)))
            results = pool.map(_eval_worker, [(v, "tune") for v in trials], chunksize=1)
            pool_all = best + [(v, r) for v, r in results if "error" not in r]
            pool_all.sort(key=lambda x: -GOAL.score(x[1]))

            deduped, seen = [], set()
            for variant, result in pool_all:
                k = variant.key()
                if k not in seen:
                    seen.add(k); deduped.append((variant, result))
            best = deduped[: workers * 3]
            top = best[0][1]
            log(f"  step {step+1:2d}: best win {top['win_rate']:5.1f}%  "
                f"n={top['trades']:4d}  hold={top.get('mean_bars',0):5.1f}  "
                f"exp=${top['expectancy']:+,.0f}")

    return best
