"""H-LOC P1 (horizon crossover) and P3 (threshold kill test) on the Icarus engine.

lambda blends the SHIPPED location score toward "no opinion" and past it:
    score_loc(lam) = 0.5 + lam * (original - 0.5)
lam=+1 is shipped, lam=0 is no opinion, lam=-1 is pure inversion.
"""
import json, statistics as st, sys, time
sys.path.insert(0, '/home/user/Icarus-engine')
from icarus.strategy import IcarusEngine
from icarus.data import synthetic_for
from icarus.config import AssetClass
from icarus.timeframe import resample
from icarus.indicators import clamp
import icarus.signal as S

ORIG = S.ConfluenceEngine._location_score
SEED = int(sys.argv[1])
OUT = sys.argv[2]
BARS = 150_000

def lam_fn(lam):
    def f(direction, price, vwap):
        return clamp(0.5 + lam * (ORIG(direction, price, vwap) - 0.5))
    return f

def summarise(eng):
    t = eng.blotter.trades
    if not t:
        return {"n": 0}
    r = [x.r for x in t]
    wins = [x for x in r if x > 0]
    return {
        "n": len(t),
        "exp": st.fmean(r),
        "sumr": sum(r),
        "win": 100.0 * len(wins) / len(t),
        "dd": 100.0 * eng.blotter.max_drawdown / eng.blotter.starting_equity,
        "hold": st.fmean([x.bars_held for x in t]),
        "mean_score": st.fmean([x.score for x in t]),
    }

def run(bars, tf, lam, min_score=None):
    S.ConfluenceEngine._location_score = staticmethod(lam_fn(lam))
    eng = IcarusEngine(AssetClass.MICRO_FUTURES, exit_policy="hybrid", timeframe=tf)
    if min_score is not None:
        eng.confluence.min_score = min_score
    for b in bars:
        eng.on_bar(b)
    S.ConfluenceEngine._location_score = staticmethod(ORIG)
    return summarise(eng)

t0 = time.time()
src = synthetic_for(AssetClass.MICRO_FUTURES, BARS, seed=SEED, minutes=2)
tapes = {}
for tf in ("2m", "3m", "5m", "10m", "20m", "30m"):
    tapes[tf] = resample(src, tf)
print(f"[seed {SEED}] tapes built {time.time()-t0:.0f}s", flush=True)

LAMS = (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0)
out = {"seed": SEED, "bars": BARS, "p1": {}, "p3": {}}

# --- P1: horizon crossover, shipped gate (profile min_confluence = 0.56) ---
for tf in ("2m", "3m", "5m", "10m", "20m", "30m"):
    out["p1"][tf] = {}
    for lam in LAMS:
        r = run(tapes[tf], tf, lam)
        out["p1"][tf][f"{lam:+.2f}"] = r
        print(f"[seed {SEED}] P1 {tf:>3s} lam={lam:+.2f} n={r.get('n',0):4d} "
              f"exp={r.get('exp',0):+.3f} win={r.get('win',0):.1f} dd={r.get('dd',0):.2f} "
              f"({time.time()-t0:.0f}s)", flush=True)
        json.dump(out, open(OUT, "w"), indent=1)

# --- P3: independently re-tune min_score at lam=+1 and lam=-1 ---
GRID = [round(0.45 + 0.025 * k, 3) for k in range(16)]      # 0.450 .. 0.825
for tf in ("2m", "5m"):
    out["p3"][tf] = {}
    for lam in (1.0, -1.0):
        out["p3"][tf][f"{lam:+.2f}"] = {}
        for ms in GRID:
            r = run(tapes[tf], tf, lam, min_score=ms)
            out["p3"][tf][f"{lam:+.2f}"][f"{ms:.3f}"] = r
            print(f"[seed {SEED}] P3 {tf:>3s} lam={lam:+.2f} ms={ms:.3f} "
                  f"n={r.get('n',0):4d} exp={r.get('exp',0):+.3f} win={r.get('win',0):.1f} "
                  f"dd={r.get('dd',0):.2f} ({time.time()-t0:.0f}s)", flush=True)
            json.dump(out, open(OUT, "w"), indent=1)

json.dump(out, open(OUT, "w"), indent=1)
print(f"[seed {SEED}] DONE {time.time()-t0:.0f}s", flush=True)
