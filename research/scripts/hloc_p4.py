"""H-LOC P4: the same lambda treatment on pulse.py's VWAP vote.

pulse.py's location analogue is the VWAP confluence vote (`above_vwap` /
`below_vwap`, vote slot 2). `Inputs.vwap_vote_lambda` scales it: +1 is the
script as shipped, 0 abstains with half weight to each side, -1 flips it.
"""
import sys, time, json
sys.path.insert(0, '/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from tools.htf_context import ContextProvider
from tools.validate_pulse import run_pulse

SPLIT = datetime(2025, 10, 1, tzinfo=timezone.utc)
LAMBDAS = (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0)
SCR = "/tmp/claude-0/-home-user-Icarus-engine/134e69c0-9376-5c62-9fa5-dfe829f5f315/scratchpad"


def fmt(r):
    return (f"n={r.get('trades',0):5d} win={r.get('win_rate',0):5.1f}% exp=${r.get('expectancy',0):+8.2f} "
            f"PF={r.get('profit_factor',0):5.2f} net=${r.get('net',0):+11,.0f} hold={r.get('mean_hold',0):5.1f}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "ATR-Based"
    tfs = [int(x) for x in sys.argv[2:]] or [30, 20, 10, 5]
    out = {}
    for tf in tfs:
        bars = load_csv(f"/home/user/Icarus-engine/data/mnq_{tf}m_full.csv")
        segs = (("TUNE", [b for b in bars if b.ts < SPLIT]), ("HOLD", [b for b in bars if b.ts >= SPLIT]))
        ctx = {n: ContextProvider(s, f"{tf}m") for n, s in segs}
        print(f"\n=== pulse.py {tf}m  {mode} ===")
        sys.stdout.flush()
        for lam in LAMBDAS:
            line = f"  L={lam:+5.2f} "
            for name, seg in segs:
                t0 = time.time()
                r = run_pulse(seg, tf_minutes=tf, tpsl_mode=mode, context=ctx[name],
                              vwap_vote_lambda=lam)
                out[f"{tf}|{mode}|{lam}|{name}"] = r
                line += f" | {name} {fmt(r)}"
            print(line + f"   ({time.time()-t0:.0f}s)")
            sys.stdout.flush()
            json.dump(out, open(f"{SCR}/p4_{mode.replace(' ','_')}.json", "w"), indent=0)
