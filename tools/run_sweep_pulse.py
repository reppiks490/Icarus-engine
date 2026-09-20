"""Drive the three-stage search over THE PULSE OF ICARUS's 185 inputs."""
from __future__ import annotations

import json, random, sys, time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from tools.htf_context import ContextProvider
from tools.sweep_pulse import (
    CONTEXTS, TAPES, PulseVariant, fmt, load_meta, passes, run_stage, sample_overrides,
)

N          = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
OUT        = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/pulse_sweep.json")
WORKERS    = 4
# Full intraday band. The Suite runs 10m; the TradingView export was 20m.
# Every input combination is drawn against a randomly chosen timeframe, so
# the search covers configuration AND bar size jointly rather than fixing one.
TIMEFRAMES = ("2m", "3m", "5m", "10m", "15m", "20m", "30m", "1h")
SCREEN_2M  = 30_000      # ~42 days
FULL_2M    = 110_000     # ~153 days

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
span = (TAPES[("tune","10m")][-1].ts - TAPES[("tune","10m")][0].ts).days
print(f"  span {span} days, real HTF context on all tapes  ({time.time()-t0:.0f}s)", flush=True)

meta = load_meta()
rng = random.Random(20260920)
variants, seen = [], set()
while len(variants) < N:
    v = PulseVariant(rng.choice(TIMEFRAMES), sample_overrides(meta, rng))
    if v.key() not in seen:
        seen.add(v.key()); variants.append(v)
print(f"sampled {len(variants)} variants over {len(meta)} declared inputs\n", flush=True)

t = time.time()
screened = run_stage(variants, "screen", WORKERS)
alive = [(v, r) for v, r in screened
         if passes(r, min_trades=10, min_exp=1.0, min_tpd=0.02, max_tpd=4.0, min_win=35.0)]
print(f"stage 1 screen : {len(variants)} -> {len(alive)}  ({time.time()-t:.0f}s)", flush=True)

t = time.time()
tuned = run_stage([v for v, _ in alive], "tune", WORKERS)
alive2 = [(v, r) for v, r in tuned
          if passes(r, min_trades=40, min_exp=50.0, min_tpd=0.05, max_tpd=2.5, min_win=45.0)]
print(f"stage 2 tune   : {len(alive)} -> {len(alive2)}  ({time.time()-t:.0f}s)", flush=True)

t = time.time()
held = run_stage([v for v, _ in alive2], "hold", WORKERS)
tune_by = {v.key(): r for v, r in tuned}
final = [(v, tune_by[v.key()], hr) for v, hr in held
         if "error" not in hr and hr.get("trades", 0) >= 30 and hr["expectancy"] > 0]
final.sort(key=lambda x: -min(x[1]["expectancy"], x[2]["expectancy"]))
print(f"stage 3 holdout: {len(alive2)} -> {len(final)} positive out of sample  ({time.time()-t:.0f}s)\n", flush=True)

print("=" * 100)
print(f"TOP {min(20,len(final))} — ranked on the WORSE of tune/held-out expectancy")
print("=" * 100)
for i, (v, tr, hr) in enumerate(final[:20], 1):
    print(f"#{i:02d} TUNE {fmt(v, tr)}")
    print(f"    HOLD {fmt(v, hr)}")
    ch = v.changed_from_anchor()
    print(f"    {len(ch)} inputs off anchor: {json.dumps(ch, default=str)[:220]}")

json.dump([{"rank": i, "timeframe": v.timeframe, "changed": v.changed_from_anchor(),
            "overrides": v.overrides, "tune": tr, "hold": hr}
           for i, (v, tr, hr) in enumerate(final, 1)], open(OUT, "w"), indent=1, default=str)
print(f"\nwrote {len(final)} survivors to {OUT}   total {time.time()-t0:.0f}s")
