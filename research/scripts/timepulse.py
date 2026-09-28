import sys, time; sys.path.insert(0,'/home/user/Icarus-engine')
from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from tools.htf_context import ContextProvider
from tools.validate_pulse import run_pulse
src=synthetic_for(AssetClass.MICRO_FUTURES,110000,seed=11,minutes=2)
for tf,n in (("2m",30000),("20m",110000)):
    sub=src[:n]
    t=time.time(); tape=resample(sub,tf); ctx=ContextProvider(sub,tf); print(f"{tf} tape {len(tape)} ctx {time.time()-t:.1f}s",flush=True)
    t=time.time(); r=run_pulse(tape, tf_minutes=int(tf.rstrip('m')), tpsl_mode="ATR-Based", context=ctx)
    print(f"  run {tf}: n={r['trades']} win={r['win_rate']:.1f} {time.time()-t:.1f}s",flush=True)
