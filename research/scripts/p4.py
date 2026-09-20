"""H-LOC P4 -- does the lambda treatment transfer to Astra's pulse.py?

pulse.py's location analogue is the VWAP confluence vote (vote index 2,
`above_vwap` for longs / `below_vwap` for shorts). NOTE THE SIGN: pulse.py
already scores location for CONTINUATION -- a long wants price ABOVE value --
which is the OPPOSITE premise to Icarus's `_location_score`. So lambda = +1
(shipped) is pulse's continuation premise and lambda = -1 is Icarus's
mean-reversion premise.

Run with real causal HTF/LTF context, the shipped ATR-Based sizing, on the
same two seeds as everything else.
"""
from __future__ import annotations
import json, sys, time
sys.path.insert(0, '/home/user/Icarus-engine')
from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from tools.htf_context import ContextProvider
from tools.validate_pulse import run_pulse

SEED = int(sys.argv[1])
OUT  = sys.argv[2]
BARS = 110_000
LAMS = (-1.0, -0.5, 0.0, 0.5, 1.0)
TFS  = ("2m", "5m", "10m", "20m")

t0 = time.time()
src = synthetic_for(AssetClass.MICRO_FUTURES, BARS, seed=SEED, minutes=2)
out = {"seed": SEED, "bars": BARS, "scan": {}}
for tf in TFS:
    tape = resample(src, tf)
    ctx = ContextProvider(src, tf)
    out["scan"][tf] = {}
    for lam in LAMS:
        r = run_pulse(tape, tf_minutes=int(tf.rstrip("m")), tpsl_mode="ATR-Based",
                      context=ctx, vwap_vote_lambda=lam)
        days = max((tape[-1].ts - tape[0].ts).total_seconds() / 86400.0, 1e-9)
        r["trades_per_day"] = r.get("trades", 0) / days
        out["scan"][tf][f"{lam:+.2f}"] = r
        print(f"[seed {SEED}] {tf:>3s} lam={lam:+.2f} n={r.get('trades',0):4d} "
              f"win={r.get('win_rate',0):5.1f}% exp=${r.get('expectancy',0):+9,.0f} "
              f"hold={r.get('mean_hold',0):5.1f} net=${r.get('net',0):+12,.0f} "
              f"({time.time()-t0:.0f}s)", flush=True)
        json.dump(out, open(OUT, "w"), indent=1, default=str)
print(f"[seed {SEED}] DONE {time.time()-t0:.0f}s", flush=True)
