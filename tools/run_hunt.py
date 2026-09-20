"""Run the goal-directed hunt and report every variant that clears the bar."""
from __future__ import annotations

import json, random, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from tools.goal import GOAL, TARGET_COUNT
from tools.htf_context import ContextProvider
from tools.hunt import climb, _eval_worker
from tools.sweep_pulse import CONTEXTS, TAPES, load_meta, run_stage

TIMEFRAMES = ("2m", "3m", "5m", "10m", "15m", "20m", "30m")
FULL_2M    = 110_000
ITER       = int(sys.argv[1]) if len(sys.argv) > 1 else 14
OUT        = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/hunt.json")

t0 = time.time()
print("building tune + held-out tapes with real HTF context...", flush=True)
tune_src = synthetic_for(AssetClass.MICRO_FUTURES, FULL_2M, seed=11, minutes=2)
hold_src = synthetic_for(AssetClass.MICRO_FUTURES, FULL_2M, seed=41, minutes=2)
for tf in TIMEFRAMES:
    TAPES[("tune", tf)] = resample(tune_src, tf)
    TAPES[("hold", tf)] = resample(hold_src, tf)
    CONTEXTS[("tune", tf)] = ContextProvider(tune_src, tf)
    CONTEXTS[("hold", tf)] = ContextProvider(hold_src, tf)
print(f"  {(TAPES[('tune','10m')][-1].ts - TAPES[('tune','10m')][0].ts).days} days  ({time.time()-t0:.0f}s)\n", flush=True)

print(f"GOAL: win>={GOAL.min_win_rate}% on BOTH tapes, n>={GOAL.min_trades:.0f}, "
      f"hold>={GOAL.min_hold_bars} bars, tpd {GOAL.min_trades_per_day}-{GOAL.max_trades_per_day}\n", flush=True)

meta = load_meta()
rng = random.Random(4242)
print(f"climbing on the TUNING tape only ({ITER} steps)...", flush=True)
best = climb(TIMEFRAMES, meta, iterations=ITER, width=3, workers=4, rng=rng)

# Only now does held-out data get touched.
print(f"\nvalidating {len(best)} climbed points on HELD-OUT data...", flush=True)
held = run_stage([v for v, _ in best], "hold", 4)
tune_by = {v.key(): r for v, r in best}

rows = []
for variant, hold in held:
    tune = tune_by[variant.key()]
    rows.append((variant, tune, hold, GOAL.clears(hold, tune)))
rows.sort(key=lambda x: -GOAL.score(x[2]))

qualified = [r for r in rows if r[3]]
print("\n" + "=" * 104)
print(f"{len(qualified)} VARIANTS CLEAR THE GOAL ON HELD-OUT DATA   (target: more than {TARGET_COUNT})")
print("=" * 104)
for i, (v, tr, hr, _) in enumerate(qualified[:25], 1):
    print(f"#{i:02d} {v.timeframe:>4s}  HOLD win={hr['win_rate']:5.1f}%  n={hr['trades']:4d}  "
          f"tpd={hr['trades_per_day']:4.2f}  hold={hr['mean_bars']:5.1f}b  "
          f"exp=${hr['expectancy']:+8,.0f}  net=${hr['net']:+11,.0f}")
    print(f"     {'':4s}  TUNE win={tr['win_rate']:5.1f}%  n={tr['trades']:4d}  "
          f"exp=${tr['expectancy']:+8,.0f}")
    print(f"     changed: {json.dumps(v.changed_from_anchor(), default=str)[:200]}")

if not qualified:
    print("\nNone cleared. Closest misses and exactly what they failed:")
    for v, tr, hr, _ in rows[:8]:
        print(f"  {v.timeframe:>4s} win={hr.get('win_rate',0):5.1f}% n={hr.get('trades',0):4d} "
              f"-> {', '.join(GOAL.shortfall(hr))}")

json.dump([{"timeframe": v.timeframe, "changed": v.changed_from_anchor(),
            "overrides": v.overrides, "tune": tr, "hold": hr, "clears": ok}
           for v, tr, hr, ok in rows], open(OUT, "w"), indent=1, default=str)
print(f"\nwrote {len(rows)} evaluated points to {OUT}   total {time.time()-t0:.0f}s")
