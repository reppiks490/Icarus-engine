import sys, time; sys.path.insert(0,'/home/user/Icarus-engine')
t0=time.time()
from icarus.strategy import IcarusEngine
from icarus.data import synthetic_for
from icarus.config import AssetClass
from icarus.timeframe import resample
print(f"import {time.time()-t0:.1f}s", flush=True)
t=time.time(); src=synthetic_for(AssetClass.MICRO_FUTURES,150000,seed=11,minutes=2); print(f"synth 150k {time.time()-t:.1f}s", flush=True)
for tf in ("2m","30m"):
    t=time.time(); bars=resample(src,tf); print(f"resample {tf} -> {len(bars)} bars {time.time()-t:.1f}s", flush=True)
    t=time.time(); eng=IcarusEngine(AssetClass.MICRO_FUTURES, exit_policy="hybrid", timeframe=tf)
    for b in bars: eng.on_bar(b)
    print(f"  run {tf}: {len(eng.blotter.trades)} trades, {time.time()-t:.1f}s", flush=True)
