import sys, time; sys.path.insert(0,'/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from tools.validate_pulse import permutation_null

SPLIT = datetime(2025,10,1,tzinfo=timezone.utc)
bars = load_csv("data/mnq_20m_full.csv")
segs = {"TUNE":[b for b in bars if b.ts<SPLIT], "HOLD":[b for b in bars if b.ts>=SPLIT], "ALL":bars}

for name in ("HOLD","ALL"):
    seg = segs[name]
    t0=time.time()
    print(f"=== pulse.py ATR-Based 20m, REAL MNQ, {name} span ({len(seg)} bars), 60 surrogates ===")
    sys.stdout.flush()
    res = permutation_null(seg, runs=60, tf_minutes=20, tpsl_mode="ATR-Based",
                           context_source=seg, chart_tf="20m")
    o = res["observed"]
    print(f"OBSERVED  n={o['trades']}  net=${o['net']:+,.0f}  win={o['win_rate']:.1f}%  "
          f"exp=${o['expectancy']:+.2f}  PF={o['profit_factor']:.2f}  hold={o['mean_hold']:.1f}")
    print(f"NULL      median ${res['null_median_net']:+,.0f}   best of 60 ${res['null_best_net']:+,.0f}")
    print(f"p = {res['p_value']:.4f}   (floor {1/61:.4f})   {'SURVIVES' if res['p_value']<=0.05 else 'FAILS'}")
    print(f"({time.time()-t0:.0f}s)\n")
    sys.stdout.flush()
