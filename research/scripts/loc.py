import sys, statistics as st; sys.path.insert(0,'/home/user/Icarus-engine')
from icarus.strategy import IcarusEngine
from icarus.data import synthetic_for
from icarus.config import AssetClass, profile_for
from icarus.timeframe import resample
from dataclasses import replace
import icarus.signal as S

# c_location's top quintile WINS LESS than its bottom quintile, on both tapes
# (-0.162 / -0.146). It carries weight 0.70. Test: is the component inverted,
# or merely useless? Decide on P&L, not on win rate -- F-001's lesson.
orig = S.ConfluenceEngine._location_score
def inverted(direction, price, vwap):
    return 1.0 - orig(direction, price, vwap)

def run(mode, weight, seed):
    S.ConfluenceEngine._location_score = staticmethod(inverted if mode=="invert" else orig)
    base = profile_for(AssetClass.MICRO_FUTURES)
    prof = replace(base, weights=replace(base.weights, location=weight))
    bars = resample(synthetic_for(AssetClass.MICRO_FUTURES,150000,seed=seed,minutes=2),"2m")
    eng = IcarusEngine(prof, exit_policy="hybrid", timeframe="2m")
    for b in bars: eng.on_bar(b)
    t=eng.blotter.trades
    if len(t)<30: return None
    r=[x.r for x in t]
    return dict(n=len(t), exp=st.fmean(r), sumr=sum(r),
                win=100*sum(1 for x in r if x>0)/len(t),
                dd=100*eng.blotter.max_drawdown/eng.blotter.starting_equity)

print(f"{'mode':>8s} {'w':>5s} | {'TUNE n':>7s} {'expR':>8s} {'sumR':>9s} {'win%':>6s} {'DD%':>6s}"
      f" | {'HOLD n':>7s} {'expR':>8s} {'sumR':>9s} {'win%':>6s} {'DD%':>6s}")
for mode,w in (("normal",0.70),("normal",0.35),("normal",0.00),
               ("invert",0.35),("invert",0.70),("invert",1.05)):
    a=run(mode,w,11); b=run(mode,w,41)
    f=lambda d: (f"{d['n']:7d} {d['exp']:+8.3f} {d['sumr']:+9.2f} {d['win']:6.1f} {d['dd']:6.2f}"
                 if d else "        (too few trades)        ")
    print(f"{mode:>8s} {w:5.2f} | {f(a)} | {f(b)}")
S.ConfluenceEngine._location_score = staticmethod(orig)
