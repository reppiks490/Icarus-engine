import sys, statistics as st; sys.path.insert(0,'/home/user/Icarus-engine')
from icarus.strategy import IcarusEngine
from icarus.data import synthetic_for
from icarus.config import AssetClass, profile_for
from icarus.timeframe import resample
from icarus.indicators import clamp
import icarus.signal as S

orig = S.ConfluenceEngine._location_score

def continuation(direction, price, vwap):
    """Location scored for a CONTINUATION setup, not a mean-reversion one.

    Icarus trades a failed sweep plus a structure break -- after a low is raided
    and reclaimed, price is SUPPOSED to be pushing away from value. Demanding a
    discount penalised exactly the setups where the move had already started.
    Reward displacement in the trade's direction, roll off once it is stretched.
    """
    dev = vwap.deviation(price)
    if dev == 0.0 and vwap.value is None:
        return 0.5
    confirm = direction * dev              # positive == moving our way
    if confirm <= 0.0:
        return clamp(0.5 + 0.18 * confirm)          # still inside value: mild penalty
    return clamp(0.5 + 0.5 * min(confirm, 2.0) / 2.0 - 0.22 * max(0.0, confirm - 3.0))

def invert(direction, price, vwap):
    return 1.0 - orig(direction, price, vwap)

def run(fn, seed, tf):
    S.ConfluenceEngine._location_score = staticmethod(fn)
    bars = resample(synthetic_for(AssetClass.MICRO_FUTURES,150000,seed=seed,minutes=2), tf)
    eng = IcarusEngine(AssetClass.MICRO_FUTURES, exit_policy="hybrid", timeframe=tf)
    for b in bars: eng.on_bar(b)
    t=eng.blotter.trades
    if len(t)<25: return None
    r=[x.r for x in t]
    return dict(n=len(t), exp=st.fmean(r), sumr=sum(r),
                win=100*sum(1 for x in r if x>0)/len(t),
                dd=100*eng.blotter.max_drawdown/eng.blotter.starting_equity)

print(f"{'variant':>13s} {'tf':>4s} | {'TUNE n':>7s} {'expR':>8s} {'win%':>6s} {'DD%':>6s}"
      f" | {'HOLD n':>7s} {'expR':>8s} {'win%':>6s} {'DD%':>6s}")
for tf in ("2m","5m","10m"):
    for name,fn in (("original",orig),("pure-invert",invert),("continuation",continuation)):
        a=run(fn,11,tf); b=run(fn,41,tf)
        f=lambda d:(f"{d['n']:7d} {d['exp']:+8.3f} {d['win']:6.1f} {d['dd']:6.2f}" if d else "     (too few trades)   ")
        print(f"{name:>13s} {tf:>4s} | {f(a)} | {f(b)}")
    print()
S.ConfluenceEngine._location_score = staticmethod(orig)
