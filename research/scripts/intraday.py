"""Is the real-data edge intraday, or is it overnight carry wearing a label?

`run_pulse` pins use_session/use_eod_flat off, which is right for a 24/7
synthetic tape and wrong here: on real MNQ it lets a position sit through the
daily halt. Measured on the held-out span, 28.5% of legs crossed a calendar
day and carried +$38,897 while the 71.5% that stayed intraday lost $24,410.
So the gate is the experiment, and it has to be driven directly.
"""
import sys; sys.path.insert(0,'/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from tools.htf_context import ContextProvider
from tools.metrics import analyse
from tools.validate_pulse import to_pulse_bars
from icarus_engine.emulator import Emulator
from icarus_engine.strategy.inputs import Inputs
from icarus_engine.strategy.pulse import PulseStrategy

SPLIT = datetime(2025,10,1,tzinfo=timezone.utc)

def run(bars, tf, mode, **gate):
    inp = Inputs(use_entry_window=False, use_session_bias=False, use_hour_breach=False,
                 midday_mode="Off", tpsl_mode=mode, point_value=2.0,
                 sess_window="0530-1530", **gate)
    em = Emulator(100_000.0, 0.37, 0.25, 2.0)
    strat = PulseStrategy(inp, em, mintick=0.25, tf_minutes=tf)
    ctx = ContextProvider(bars, f"{tf}m")
    for i, b in enumerate(to_pulse_bars(bars)):
        em.process_bar(b, i)
        h, l = ctx.at(b.ts)
        strat.on_bar(b, i, h, l)
    if not em.closed:
        return {"trades": 0}
    span = max((bars[-1].ts - bars[0].ts).total_seconds()/86400.0, 1e-9)
    return analyse(list(em.closed), span_days=span).as_dict()

GATES = (
    ("free-running (as reported)", dict(use_session=False, use_eod_flat=False)),
    ("session gate only",          dict(use_session=True,  use_eod_flat=False)),
    ("session + FLAT at close",    dict(use_session=True,  use_eod_flat=True)),
)

print(f"{'tf':>4s} {'mode':>10s} {'gating':>26s} {'span':>5s} {'n':>5s} {'win%':>6s} "
      f"{'exp$':>9s} {'PF':>6s} {'hold':>6s} {'tpgap':>6s} {'net$':>11s}")
print("-"*112)
for tf in (10, 20):
    bars = load_csv(f"data/mnq_{tf}m_full.csv")
    segs = (("TUNE",[b for b in bars if b.ts<SPLIT]), ("HOLD",[b for b in bars if b.ts>=SPLIT]))
    for mode in ("ATR-Based","Fixed Points"):
        for label, gate in GATES:
            for nm, seg in segs:
                try:
                    r = run(seg, tf, mode, **gate)
                except Exception as e:
                    print(f"{tf:>3d}m {mode[:10]:>10s} {label:>26s} {nm:>5s}   ERROR {type(e).__name__}: {e}")
                    sys.stdout.flush(); continue
                print(f"{tf:>3d}m {mode[:10]:>10s} {label:>26s} {nm:>5s} {r.get('trades',0):5d} "
                      f"{r.get('win_rate',0):6.1f} {r.get('expectancy',0):+9.2f} "
                      f"{r.get('profit_factor',0):6.2f} {r.get('mean_hold',0):6.1f} "
                      f"{r.get('tp_gap_pp',0):6.1f} {r.get('net',0):+11,.0f}")
                sys.stdout.flush()
        print()
