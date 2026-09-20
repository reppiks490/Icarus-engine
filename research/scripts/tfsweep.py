import sys, time; sys.path.insert(0,'/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from tools.htf_context import ContextProvider
from tools.validate_pulse import run_pulse
from tools.goal import Goal

SPLIT = datetime(2025,10,1,tzinfo=timezone.utc)
goal = Goal()
print(f"{'tf':>4s} {'mode':>10s} {'span':>5s} {'n':>5s} {'win%':>6s} {'exp$':>9s} {'PF':>6s} {'hold':>6s} {'net$':>11s} {'tp1%':>6s} {'tp2%':>6s} {'gap':>6s} {'strk':>5s}")
print("-"*100)
for tf in (5,10,20,30):
    bars = load_csv(f"data/mnq_{tf}m_full.csv")
    tune=[b for b in bars if b.ts<SPLIT]; hold=[b for b in bars if b.ts>=SPLIT]
    for mode in ("ATR-Based","Fixed Points"):
        res={}
        for nm,seg in (("TUNE",tune),("HOLD",hold)):
            t0=time.time()
            r=run_pulse(seg, tf_minutes=tf, tpsl_mode=mode, context=ContextProvider(seg,f"{tf}m"))
            res[nm]=r
            print(f"{tf:>3d}m {mode[:10]:>10s} {nm:>5s} {r.get('trades',0):5d} {r.get('win_rate',0):6.1f} "
                  f"{r.get('expectancy',0):+9.2f} {r.get('profit_factor',0):6.2f} {r.get('mean_hold',0):6.1f} "
                  f"{r.get('net',0):+11,.0f} {r.get('tp1_rate',0):6.1f} {r.get('tp2_rate',0):6.1f} "
                  f"{r.get('tp_gap_pp',0):6.1f} {r.get('streak_ratio',0):5.2f}   ({time.time()-t0:.0f}s)")
            sys.stdout.flush()
        h,t=res["HOLD"],res["TUNE"]
        print(f"     -> goal: {'QUALIFIES' if goal.clears(h,t) else 'no'}")
        sys.stdout.flush()
