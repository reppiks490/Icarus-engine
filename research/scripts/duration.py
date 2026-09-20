"""Is the duration edge measured in BARS or in WALL-CLOCK HOURS?

On the 20m tape the win rate climbs monotonically with bars held and peaks at
80% beyond 64 bars -- but 64 bars at 20m is 21 hours, so that band is overnight
carry and cannot be traded intraday. The distinction decides everything: if the
edge is in BARS, a 5m chart reaches 64 bars in 5.3 hours and the same regime
fits inside a session. If it is in HOURS, it is a swing edge and no timeframe
change rescues it.

Same buckets, run on every timeframe, reported both ways.
"""
import sys; sys.path.insert(0,'/home/user/Icarus-engine')
from datetime import datetime, timezone
from collections import defaultdict
import statistics as st
from icarus.data import load_csv
from tools.htf_context import ContextProvider
from tools.validate_pulse import to_pulse_bars
from icarus_engine.emulator import Emulator
from icarus_engine.strategy.inputs import Inputs
from icarus_engine.strategy.pulse import PulseStrategy
from tools.metrics import assemble

SPLIT = datetime(2025,10,1,tzinfo=timezone.utc)
BAR_BANDS  = ((0,4),(4,8),(8,16),(16,32),(32,64),(64,128),(128,10**9))
HOUR_BANDS = ((0,1),(1,2),(2,4),(4,8),(8,16),(16,32),(32,10**9))

def run(bars, tf, mode):
    inp = Inputs(use_session=False, use_entry_window=False, use_eod_flat=False,
                 use_session_bias=False, use_hour_breach=False, midday_mode="Off",
                 tpsl_mode=mode, point_value=2.0)
    em = Emulator(100_000.0, 0.37, 0.25, 2.0)
    strat = PulseStrategy(inp, em, mintick=0.25, tf_minutes=tf)
    ctx = ContextProvider(bars, f"{tf}m")
    for i, b in enumerate(to_pulse_bars(bars)):
        em.process_bar(b, i)
        h, l = ctx.at(b.ts)
        strat.on_bar(b, i, h, l)
    return assemble(list(em.closed))

def table(positions, tf, key, bands, unit):
    rows = []
    total = sum(p.profit for p in positions) or 1.0
    for lo, hi in bands:
        sel = [p for p in positions if lo <= key(p, tf) < hi]
        if not sel: continue
        pr = [p.profit for p in sel]
        label = f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"
        rows.append((label, len(sel), 100*sum(1 for x in pr if x>0)/len(sel),
                     st.fmean(pr), sum(pr), 100*sum(pr)/total))
    print(f"    {'band('+unit+')':>12s} {'n':>5s} {'win%':>7s} {'exp$':>10s} {'net$':>12s} {'%net':>8s}")
    for label,n,w,e,net,share in rows:
        print(f"    {label:>12s} {n:5d} {w:7.1f} {e:+10.2f} {net:+12,.0f} {share:+8.1f}")

for mode in ("ATR-Based","Fixed Points"):
    for tf in (5,10,20,30):
        bars = load_csv(f"data/mnq_{tf}m_full.csv")
        hold = [b for b in bars if b.ts>=SPLIT]
        pos = run(hold, tf, mode)
        if len(pos) < 30:
            print(f"\n{mode} {tf}m: only {len(pos)} positions, skipping"); continue
        print(f"\n=== {mode}  {tf}m  held-out  ({len(pos)} positions) ===")
        print("  by BARS held:")
        table(pos, tf, lambda p,t: p.bars_held, BAR_BANDS, "bars")
        print("  by HOURS held:")
        table(pos, tf, lambda p,t: p.bars_held*t/60.0, HOUR_BANDS, "hrs")
        sys.stdout.flush()
