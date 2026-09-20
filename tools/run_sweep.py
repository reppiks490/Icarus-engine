"""Drive the three-stage variant search. See tools/sweep.py for the discipline."""
from __future__ import annotations

import json, random, sys, time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.sweep import (
    TAPES, TIMEFRAME_CHOICES, Variant, build_tapes, fmt, passes, run_stage,
    sample_variant,
)

N_SAMPLES   = int(sys.argv[1]) if len(sys.argv) > 1 else 900
WORKERS     = 4
SCREEN_BARS = 60_000      # 2m bars -> ~83 days
FULL_BARS   = 300_000     # 2m bars -> ~416 days, so a 30m variant taking
                          # 0.5 trades/day still clears 200 trades
OUT         = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/sweep_results.json")

t0 = time.time()
print(f"building tapes ({FULL_BARS:,} 2m bars per seed, "
      f"{len(TIMEFRAME_CHOICES)} timeframes: {' '.join(TIMEFRAME_CHOICES)})...", flush=True)
build_tapes(SCREEN_BARS, FULL_BARS, tune_seed=11, hold_seed=41)
span = (TAPES[("tune","2m")][-1].ts - TAPES[("tune","2m")][0].ts).days
print(f"  tune/hold span: {span} days   ({time.time()-t0:.0f}s)", flush=True)

rng = random.Random(20260920)
variants, seen = [], set()
while len(variants) < N_SAMPLES:
    v = sample_variant(rng)
    if v.key() not in seen:
        seen.add(v.key()); variants.append(v)
print(f"sampled {len(variants)} distinct variants\n", flush=True)

# --- stage 1: cheap screen -------------------------------------------------
t = time.time()
screened = run_stage(variants, "screen", WORKERS)
alive = [(v, r) for v, r in screened
         if passes(r, min_trades=12, min_exp=0.02, max_tpd=3.5, min_tpd=0.02, min_win=35.0)]
print(f"stage 1 screen : {len(variants)} -> {len(alive)} survive  ({time.time()-t:.0f}s)", flush=True)

# --- stage 2: full tuning tape ---------------------------------------------
t = time.time()
tuned = run_stage([v for v, _ in alive], "tune", WORKERS)
alive2 = [(v, r) for v, r in tuned
          if passes(r, min_trades=40, min_exp=0.05, max_tpd=2.0, min_tpd=0.05, min_win=45.0)]
print(f"stage 2 tune   : {len(alive)} -> {len(alive2)} survive  ({time.time()-t:.0f}s)", flush=True)

# --- stage 3: held-out validation ------------------------------------------
t = time.time()
held = run_stage([v for v, _ in alive2], "hold", WORKERS)
tune_by_key = {v.key(): r for v, r in tuned}
final = []
for v, hr in held:
    if "error" in hr or hr["trades"] < 30:
        continue
    final.append((v, tune_by_key[v.key()], hr))
print(f"stage 3 holdout: {len(alive2)} -> {len(final)} evaluated  ({time.time()-t:.0f}s)\n", flush=True)

# Survivors must clear the bar on data they were NEVER selected on.
survivors = [(v, tr, hr) for v, tr, hr in final
             if hr["expectancy"] > 0 and hr["win_rate"] >= 45.0
             and 0.0 <= hr["trades_per_day"] <= 2.5]
survivors.sort(key=lambda x: -min(x[1]["expectancy"], x[2]["expectancy"]))

print("=" * 118)
print(f"{len(survivors)} VARIANTS POSITIVE ON HELD-OUT DATA (ranked by WORSE of tune/hold expectancy)")
print("=" * 118)
for i, (v, tr, hr) in enumerate(survivors[:40], 1):
    print(f"#{i:02d} TUNE {fmt(v, tr)}")
    print(f"    HOLD {fmt(v, hr)}")

json.dump([{ "rank": i, "variant": asdict(v), "tune": tr, "hold": hr }
           for i, (v, tr, hr) in enumerate(survivors, 1)], open(OUT, "w"), indent=1)
print(f"\nwrote {len(survivors)} survivors to {OUT}")
print(f"total {time.time()-t0:.0f}s")
