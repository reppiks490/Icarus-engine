"""H-LOC P2 -- does a negative location lambda unlock GOAL qualifiers?

Same three-stage discipline as tools/run_sweep_pulse.py (screen on a short
slice, confirm on the full tuning tape, validate on a held-out tape from a
different seed), with `vwap_vote_lambda` added to the sampled search space.
Every stage reports its funnel BUCKETED BY LAMBDA so the comparison is not
itself gated by thresholds that were chosen under lambda = +1.
"""
from __future__ import annotations
import json, random, sys, time
from collections import Counter
from pathlib import Path
sys.path.insert(0, '/home/user/Icarus-engine')

from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from tools.htf_context import ContextProvider
from tools.goal import GOAL
from tools.sweep_pulse import (
    CONTEXTS, TAPES, PulseVariant, fmt, load_meta, passes, run_stage, sample_overrides,
)

N       = int(sys.argv[1]) if len(sys.argv) > 1 else 500
OUT     = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/p2.json")
WORKERS = 2
LAMS    = (-1.0, -0.5, 0.0, 0.5, 1.0)
TIMEFRAMES = ("2m", "3m", "5m", "10m", "15m", "20m", "30m", "1h")
SCREEN_2M, FULL_2M = 30_000, 110_000

t0 = time.time()
print(f"building tapes ({FULL_2M:,} 2m bars x2 seeds, {len(TIMEFRAMES)} timeframes)...", flush=True)
tune_src = synthetic_for(AssetClass.MICRO_FUTURES, FULL_2M, seed=11, minutes=2)
hold_src = synthetic_for(AssetClass.MICRO_FUTURES, FULL_2M, seed=41, minutes=2)
for tf in TIMEFRAMES:
    TAPES[("screen", tf)] = resample(tune_src[:SCREEN_2M], tf)
    TAPES[("tune", tf)]   = resample(tune_src, tf)
    TAPES[("hold", tf)]   = resample(hold_src, tf)
    CONTEXTS[("screen", tf)] = ContextProvider(tune_src[:SCREEN_2M], tf)
    CONTEXTS[("tune", tf)]   = ContextProvider(tune_src, tf)
    CONTEXTS[("hold", tf)]   = ContextProvider(hold_src, tf)
span = (TAPES[("tune", "10m")][-1].ts - TAPES[("tune", "10m")][0].ts).days
print(f"  span {span} days, real HTF context  ({time.time()-t0:.0f}s)", flush=True)

meta = load_meta()
rng = random.Random(20260920)
variants, seen = [], set()
while len(variants) < N:
    ov = sample_overrides(meta, rng)
    ov["vwap_vote_lambda"] = rng.choice(LAMS)
    v = PulseVariant(rng.choice(TIMEFRAMES), ov)
    if v.key() not in seen:
        seen.add(v.key()); variants.append(v)

def lam_of(v):   return v.overrides["vwap_vote_lambda"]
def bucket(vs):  return Counter(lam_of(v) for v in vs)
def show(label, vs):
    c = bucket(vs)
    print(f"{label:<26s} total {len(vs):4d}  " +
          "  ".join(f"lam{l:+.1f}={c.get(l,0):3d}" for l in LAMS), flush=True)

show("sampled", variants)

t = time.time()
screened = run_stage(variants, "screen", WORKERS)
alive = [(v, r) for v, r in screened
         if passes(r, min_trades=10, min_exp=1.0, min_tpd=0.02, max_tpd=4.0, min_win=35.0)]
show("stage 1 screen", [v for v, _ in alive]); print(f"  ({time.time()-t:.0f}s)", flush=True)

t = time.time()
tuned = run_stage([v for v, _ in alive], "tune", WORKERS)
alive2 = [(v, r) for v, r in tuned
          if passes(r, min_trades=40, min_exp=50.0, min_tpd=0.05, max_tpd=2.5, min_win=45.0)]
show("stage 2 tune", [v for v, _ in alive2]); print(f"  ({time.time()-t:.0f}s)", flush=True)

t = time.time()
held = run_stage([v for v, _ in alive2], "hold", WORKERS)
tune_by = {v.key(): r for v, r in tuned}
final = [(v, tune_by[v.key()], hr) for v, hr in held if "error" not in hr]
show("stage 3 held out", [v for v, _, _ in final]); print(f"  ({time.time()-t:.0f}s)", flush=True)

# ---------------------------------------------------------------------------
# Goal funnel: each criterion evaluated independently on the HELD-OUT result,
# so "which criterion is binding" is a count, not an impression.
# ---------------------------------------------------------------------------
def criteria(h: dict) -> dict:
    legs = h.get("runner_legs", 0) or 0
    return {
        "win_rate>=82":        h.get("win_rate", 0) >= GOAL.min_win_rate,
        "trades>=120":         h.get("trades", 0) >= GOAL.min_trades,
        "tpd in [0.5,4]":      GOAL.min_trades_per_day <= h.get("trades_per_day", 0) <= GOAL.max_trades_per_day,
        "hold>=4 bars":        h.get("mean_hold", 0) >= GOAL.min_hold_bars,
        "expectancy>0":        h.get("expectancy", 0) > GOAL.min_expectancy,
        "consistency>=0.30":   h.get("consistency", 0.0) >= GOAL.min_consistency,
        "pos block rate>=60":  h.get("positive_block_rate", 0.0) >= GOAL.min_positive_block_rate,
        "top decile<=65%":     not (h.get("top_decile_share", 0.0) and h["top_decile_share"] > GOAL.max_top_decile_share),
        "streak vs random<=2": not (h.get("streak_vs_random", 0.0) and h["streak_vs_random"] > GOAL.max_streak_vs_random),
        "streak ratio>=2.0":   h.get("streak_ratio", 0.0) >= GOAL.min_streak_ratio,
        "mean run ratio>=1.3": h.get("mean_run_ratio", 0.0) >= GOAL.min_mean_run_ratio,
        "runner win>=90":      legs == 0 or ((h.get("runner_win_rate") or 0.0) >= GOAL.min_runner_win_rate
                                             and legs >= GOAL.min_runner_legs),
        "TP gap<=6pp":         legs == 0 or (h.get("tp_gap_pp", 99.0) <= GOAL.max_tp_gap_pp
                                             and h.get("tp1_rate", 0.0) >= GOAL.min_tp_leg_rate
                                             and h.get("tp2_rate", 0.0) >= GOAL.min_tp_leg_rate),
    }

names = list(criteria({}).keys())
print("\n" + "=" * 96)
print("GOAL FUNNEL on HELD-OUT data -- each criterion counted INDEPENDENTLY")
print("=" * 96)
print(f"{'criterion':<24s}" + "".join(f"{f'lam{l:+.1f}':>10s}" for l in LAMS) + f"{'all':>8s}")
per_lam_counts = {l: Counter() for l in LAMS}
totals = Counter()
for v, _, hr in final:
    for name, ok in criteria(hr).items():
        if ok:
            per_lam_counts[lam_of(v)][name] += 1
            totals[name] += 1
denom = bucket([v for v, _, _ in final])
for name in names:
    row = "".join(f"{per_lam_counts[l][name]:>10d}" for l in LAMS)
    print(f"{name:<24s}{row}{totals[name]:>8d}")
print(f"{'-- evaluated --':<24s}" + "".join(f"{denom.get(l,0):>10d}" for l in LAMS) + f"{len(final):>8d}")

qualifiers = [(v, tr, hr) for v, tr, hr in final if GOAL.clears(hr, tr)]
print(f"\nFULL GOAL qualifiers: {len(qualifiers)}   " +
      "  ".join(f"lam{l:+.1f}={sum(1 for v,_,_ in qualifiers if lam_of(v)==l)}" for l in LAMS))

# Nearest misses, and the shortfall list for each.
final.sort(key=lambda x: -GOAL.score(x[2]))
print("\nTOP 12 held-out results by goal score, with their shortfalls:")
for i, (v, tr, hr) in enumerate(final[:12], 1):
    print(f"#{i:02d} lam={lam_of(v):+.1f} {fmt(v, hr)}")
    print(f"    shortfall: {'; '.join(GOAL.shortfall(hr)) or 'NONE'}")

json.dump({"lams": list(LAMS),
           "funnel": {f"{l:+.1f}": dict(per_lam_counts[l]) for l in LAMS},
           "evaluated": {f"{l:+.1f}": denom.get(l, 0) for l in LAMS},
           "sampled": {f"{l:+.1f}": bucket(variants).get(l, 0) for l in LAMS},
           "screen": {f"{l:+.1f}": bucket([v for v, _ in alive]).get(l, 0) for l in LAMS},
           "tune": {f"{l:+.1f}": bucket([v for v, _ in alive2]).get(l, 0) for l in LAMS},
           "qualifiers": len(qualifiers),
           "results": [{"lam": lam_of(v), "timeframe": v.timeframe,
                        "changed": v.changed_from_anchor(), "tune": tr, "hold": hr}
                       for v, tr, hr in final[:60]]},
          open(OUT, "w"), indent=1, default=str)
print(f"\ntotal {time.time()-t0:.0f}s -> {OUT}")
