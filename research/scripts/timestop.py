"""Time stops as a real input, because the band table cannot prove anything.

Slicing finished trades by how long they lasted showed win rate climbing from
28% to 88% with hold length on every timeframe, flipping at ~32 bars. That
looks like an edge and is close to a tautology: a trade survives to 64 bars
BECAUSE it never hit its stop, so losers are removed by construction and the
long bands are pre-selected winners.

The honest version changes behaviour instead of filtering outcomes:

  MIN hold   refuse to take any exit before N bars -- the stop still works,
             but targets and signal exits wait. If duration causes the edge,
             forcing trades to stay in should help. If the bands were
             selection, this destroys the result, because now the losers that
             used to terminate early are held to full loss.

  MAX hold   force flat at N bars. If the edge lives in the long tail, cutting
             it should hurt in proportion.

Both are implementable on a live chart, which the band table is not.
"""
import sys; sys.path.insert(0,'/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from tools.htf_context import ContextProvider
from tools.validate_pulse import to_pulse_bars
from tools.metrics import analyse
from icarus_engine.emulator import Emulator
from icarus_engine.strategy.inputs import Inputs
from icarus_engine.strategy.pulse import PulseStrategy

SPLIT = datetime(2025,10,1,tzinfo=timezone.utc)

def run(bars, tf, mode, min_hold=0, max_hold=0, **gate):
    """Drive pulse.py, then apply the time stop at the emulator's exit layer."""
    inp = Inputs(use_entry_window=False, use_session_bias=False, use_hour_breach=False,
                 midday_mode="Off", tpsl_mode=mode, point_value=2.0, **gate)
    em = Emulator(100_000.0, 0.37, 0.25, 2.0)
    strat = PulseStrategy(inp, em, mintick=0.25, tf_minutes=tf)
    ctx = ContextProvider(bars, f"{tf}m")

    real_exit = em.exit
    state = {"i": 0}

    def gated_exit(eid, entry_id, **kw):
        # MIN hold: suppress every non-stop exit until the trade is old enough.
        # The protective stop is left alone -- a time stop that also removes the
        # stop is not a time stop, it is unlimited risk.
        if min_hold:
            entry_bar = None
            for p in getattr(em, "open_positions", []) or []:
                entry_bar = getattr(p, "entry_bar", None)
            if entry_bar is not None and state["i"] - entry_bar < min_hold:
                kw.pop("limit", None)
        return real_exit(eid, entry_id, **kw)

    em.exit = gated_exit
    for i, b in enumerate(to_pulse_bars(bars)):
        state["i"] = i
        em.process_bar(b, i)
        if max_hold:
            for p in list(getattr(em, "open_positions", []) or []):
                eb = getattr(p, "entry_bar", None)
                if eb is not None and i - eb >= max_hold:
                    try: em.close_all("TIME")
                    except Exception: pass
        h, l = ctx.at(b.ts)
        strat.on_bar(b, i, h, l)
    if not em.closed:
        return {"trades": 0}
    span = max((bars[-1].ts - bars[0].ts).total_seconds()/86400.0, 1e-9)
    return analyse(list(em.closed), span_days=span).as_dict()

print(f"{'tf':>4s} {'min':>4s} {'max':>5s} {'span':>5s} {'n':>5s} {'win%':>6s} {'exp$':>9s} "
      f"{'PF':>6s} {'hold':>6s} {'ovn%':>6s} {'net$':>11s}")
print("-"*92)
for tf in (5, 10):
    bars = load_csv(f"data/mnq_{tf}m_full.csv")
    segs = (("TUNE",[b for b in bars if b.ts<SPLIT]), ("HOLD",[b for b in bars if b.ts>=SPLIT]))
    for mn, mx in ((0,0),(16,0),(32,0),(48,0),(0,32),(0,64),(0,128),(32,128)):
        for nm, seg in segs:
            try:
                r = run(seg, tf, "ATR-Based", min_hold=mn, max_hold=mx,
                        use_session=False, use_eod_flat=False)
            except Exception as e:
                print(f"{tf:>3d}m {mn:>4d} {mx:>5d} {nm:>5s}  ERROR {type(e).__name__}: {e}")
                sys.stdout.flush(); continue
            print(f"{tf:>3d}m {mn:>4d} {mx:>5d} {nm:>5s} {r.get('trades',0):5d} "
                  f"{r.get('win_rate',0):6.1f} {r.get('expectancy',0):+9.2f} "
                  f"{r.get('profit_factor',0):6.2f} {r.get('mean_hold',0):6.1f} "
                  f"{r.get('overnight_rate',0):6.1f} {r.get('net',0):+11,.0f}")
            sys.stdout.flush()
    print()
