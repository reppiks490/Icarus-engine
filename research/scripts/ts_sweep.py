import sys; sys.path.insert(0,'/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from tools.htf_context import ContextProvider
from tools.validate_pulse import to_pulse_bars
from tools.metrics import analyse
from tools.time_stop import TimeStop
from icarus_engine.emulator import Emulator
from icarus_engine.strategy.inputs import Inputs
from icarus_engine.strategy.pulse import PulseStrategy

SPLIT = datetime(2025,10,1,tzinfo=timezone.utc)

def run(bars, tf, mode, min_hold=0, max_hold=0, **gate):
    inp = Inputs(use_entry_window=False, use_session_bias=False, use_hour_breach=False,
                 midday_mode="Off", tpsl_mode=mode, point_value=2.0, **gate)
    em = Emulator(100_000.0, 0.37, 0.25, 2.0)
    ts = TimeStop(em, min_hold=min_hold, max_hold=max_hold)
    strat = PulseStrategy(inp, em, mintick=0.25, tf_minutes=tf)
    ctx = ContextProvider(bars, f"{tf}m")
    for i, b in enumerate(to_pulse_bars(bars)):
        em.process_bar(b, i)
        ts.on_bar(i)
        h, l = ctx.at(b.ts)
        strat.on_bar(b, i, h, l)
    if not em.closed:
        return {"trades": 0}, ts.stats
    span = max((bars[-1].ts - bars[0].ts).total_seconds()/86400.0, 1e-9)
    return analyse(list(em.closed), span_days=span).as_dict(), ts.stats

print(f"{'tf':>4s} {'min':>4s} {'max':>5s} {'span':>5s} {'n':>5s} {'win%':>6s} {'exp$':>9s} "
      f"{'PF':>6s} {'hold':>6s} {'ovn%':>6s} {'net$':>11s}  bit?")
print("-"*100)
for tf in (5, 10, 20):
    bars = load_csv(f"data/mnq_{tf}m_full.csv")
    segs = (("TUNE",[b for b in bars if b.ts<SPLIT]), ("HOLD",[b for b in bars if b.ts>=SPLIT]))
    for mn, mx in ((0,0),(16,0),(32,0),(48,0),(64,0),(0,32),(0,64),(0,128),(32,128),(32,64)):
        for nm, seg in segs:
            try:
                r, st = run(seg, tf, "ATR-Based", min_hold=mn, max_hold=mx,
                            use_session=False, use_eod_flat=False)
            except Exception as e:
                print(f"{tf:>3d}m {mn:>4d} {mx:>5d} {nm:>5s}  ERROR {type(e).__name__}: {e}")
                sys.stdout.flush(); continue
            bit = f"d{st.deferred_targets}/r{st.restored_targets}/c{st.forced_closes}"
            print(f"{tf:>3d}m {mn:>4d} {mx:>5d} {nm:>5s} {r.get('trades',0):5d} "
                  f"{r.get('win_rate',0):6.1f} {r.get('expectancy',0):+9.2f} "
                  f"{r.get('profit_factor',0):6.2f} {r.get('mean_hold',0):6.1f} "
                  f"{r.get('overnight_rate',0):6.1f} {r.get('net',0):+11,.0f}  {bit}")
            sys.stdout.flush()
    print()
