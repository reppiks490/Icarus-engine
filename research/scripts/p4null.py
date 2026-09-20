"""H-LOC P4 -- permutation null on pulse.py at the best lambda, and at shipped.

Same machinery as scratchpad/pulse_null.txt (tools/validate_pulse.permutation_null,
icarus.backtest.shuffle_bars), but with real causal HTF/LTF context REBUILT FROM
EACH SURROGATE, so no sequence information leaks back into the null.
"""
from __future__ import annotations
import json, sys, time
sys.path.insert(0, '/home/user/Icarus-engine')
from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from tools.validate_pulse import permutation_null

TF    = sys.argv[1] if len(sys.argv) > 1 else "20m"
RUNS  = int(sys.argv[2]) if len(sys.argv) > 2 else 60
LAMS  = [float(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [1.0, -1.0]
SEEDS = [int(x) for x in sys.argv[4].split(",")] if len(sys.argv) > 4 else [11, 41]
BARS  = int(sys.argv[5]) if len(sys.argv) > 5 else 60_000
OUT   = sys.argv[6] if len(sys.argv) > 6 else "/tmp/p4null.json"

minutes = int(TF.rstrip("m"))
out = {"tf": TF, "runs": RUNS, "bars_2m": BARS, "results": {}}
t0 = time.time()
for seed in SEEDS:
    src = synthetic_for(AssetClass.MICRO_FUTURES, BARS, seed=seed, minutes=2)
    tape = resample(src, TF)
    print(f"\nseed {seed}: pulse.py on {len(tape)} x {TF} MNQ bars, {RUNS} surrogates, "
          f"real HTF context rebuilt per surrogate", flush=True)
    for lam in LAMS:
        res = permutation_null(tape, runs=RUNS, tf_minutes=minutes, tpsl_mode="ATR-Based",
                               context_source=src, chart_tf=TF, vwap_vote_lambda=lam)
        o = res["observed"]
        print(f"  lam={lam:+.2f}  n={o['trades']:4d}  net=${o['net']:+12,.0f}  "
              f"per-trade=${o['expectancy']:+9,.0f}  win={o['win_rate']:5.1f}%  "
              f"hold={o.get('mean_hold',0):5.1f}  |  null median ${res['null_median_net']:+12,.0f}  "
              f"best ${res['null_best_net']:+12,.0f}  p={res['p_value']:.4f}  "
              f"(floor {1/(RUNS+1):.4f})   [{time.time()-t0:.0f}s]", flush=True)
        out["results"][f"seed{seed}_lam{lam:+.2f}"] = {
            "observed": o, "p_value": res["p_value"],
            "null_median_net": res["null_median_net"], "null_best_net": res["null_best_net"],
            "floor": 1.0 / (RUNS + 1)}
        json.dump(out, open(OUT, "w"), indent=1, default=str)
print(f"\ntotal {time.time()-t0:.0f}s -> {OUT}")
