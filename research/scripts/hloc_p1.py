"""H-LOC P1/P3: continuous lambda on `_location_score`, real MNQ, TUNE vs HOLD.

score_loc(L) = 0.5 + L * (orig - 0.5).  L=+1 is shipped behaviour, L=0 makes the
layer abstain at a flat 0.5, L=-1 is the inversion N-001 proposed.
"""
import sys, time, json
sys.path.insert(0, '/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from icarus.strategy import IcarusEngine
from icarus.config import AssetClass
from tools.metrics import analyse, from_icarus
import icarus.signal as S

ORIG = S.ConfluenceEngine._location_score
SPLIT = datetime(2025, 10, 1, tzinfo=timezone.utc)
LAMBDAS = (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0)


def patched(lam):
    def f(direction, price, vwap):
        return 0.5 + lam * (ORIG(direction, price, vwap) - 0.5)
    return staticmethod(f)


def run(bars, tf, policy, lam, min_score=None):
    S.ConfluenceEngine._location_score = patched(lam)
    try:
        eng = IcarusEngine(AssetClass.MICRO_FUTURES, exit_policy=policy, timeframe=f"{tf}m")
        if min_score is not None:
            eng.confluence.min_score = min_score
        for b in bars:
            eng.on_bar(b)
        trades = eng.blotter.trades
        if not trades:
            return {"trades": 0, "net": 0.0, "expectancy": 0.0, "win_rate": 0.0,
                    "profit_factor": 0.0, "max_drawdown": 0.0}
        span = max((bars[-1].ts - bars[0].ts).total_seconds() / 86400.0, 1e-9)
        return analyse(from_icarus(trades, bars), span_days=span).as_dict()
    finally:
        S.ConfluenceEngine._location_score = staticmethod(ORIG)


def fmt(r):
    return (f"n={r['trades']:5d} win={r.get('win_rate',0):5.1f}% exp=${r.get('expectancy',0):+8.2f} "
            f"PF={r.get('profit_factor',0):5.2f} net=${r.get('net',0):+10,.0f} "
            f"DD=${r.get('max_drawdown',0):+9,.0f}")


if __name__ == "__main__":
    policy = sys.argv[1] if len(sys.argv) > 1 else "hybrid"
    tfs = [int(x) for x in sys.argv[2:]] or [20, 10, 5, 30]
    out = {}
    for tf in tfs:
        bars = load_csv(f"/home/user/Icarus-engine/data/mnq_{tf}m_full.csv")
        segs = (("TUNE", [b for b in bars if b.ts < SPLIT]), ("HOLD", [b for b in bars if b.ts >= SPLIT]))
        print(f"\n=== {tf}m  policy={policy} ===")
        sys.stdout.flush()
        for lam in LAMBDAS:
            line = f"  L={lam:+5.2f} "
            for name, seg in segs:
                t0 = time.time()
                r = run(seg, tf, policy, lam)
                out[f"{tf}|{policy}|{lam}|{name}"] = r
                line += f" | {name} {fmt(r)}"
            print(line)
            sys.stdout.flush()
    json.dump(out, open(f"/tmp/claude-0/-home-user-Icarus-engine/134e69c0-9376-5c62-9fa5-dfe829f5f315/scratchpad/p1_{policy}.json", "w"), indent=0)
