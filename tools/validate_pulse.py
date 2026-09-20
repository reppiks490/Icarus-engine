"""Run Astra's PulseStrategy through this session's permutation null.

The question: does the edge in `icarus_engine/strategy/pulse.py` survive a tape
whose sequence has been destroyed but whose bar-by-bar distribution is intact?

Both engines are driven over the identical bars, and the surrogate tapes are
built by the same `shuffle_bars` used on the Icarus engine, so the two results
are directly comparable. `use_session` is switched off for both: the synthetic
tape runs on a 24/7 UTC clock with no RTH, and session gating would otherwise
reject nearly every bar for reasons unrelated to the strategy's edge.
"""

from __future__ import annotations

import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icarus.backtest import shuffle_bars
from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from icarus_engine.emulator import Emulator
from icarus_engine.pine.timeframe import Bar as PulseBar
from icarus_engine.strategy.inputs import Inputs
from icarus_engine.strategy.pulse import PulseStrategy

# Neutral higher/lower-timeframe context. Held constant so that every run --
# observed and surrogate alike -- sees the same external bias, which is what
# makes the comparison fair. A real run feeds these from actual HTF series.
HTF_NEUTRAL = [(0.0, 0.5)] * 5
LTF_NEUTRAL = [(0.0, 10.0, 0.5)] * 2


def to_pulse_bars(bars) -> list[PulseBar]:
    return [PulseBar(int(b.ts.timestamp()), b.open, b.high, b.low, b.close, b.volume)
            for b in bars]


def run_pulse(bars, *, tf_minutes: int, mintick: float = 0.25,
              point_value: float = 2.0, capital: float = 100_000.0,
              tpsl_mode: str = "ATR-Based", **overrides) -> dict:
    """Drive PulseStrategy over a tape and summarise the closed trades."""
    # "Fixed Points" carries NQ-sized distances (15/30/45 pts). On a 20m MNQ tape
    # a 45-point stop sits INSIDE one bar's range, which produces same-bar exits
    # and tests the sizing, not the strategy. ATR-based scales to the instrument,
    # which is the only way this is a fair read on the signal itself.
    inp = Inputs(use_session=False, use_entry_window=False, use_eod_flat=False,
                 use_session_bias=False, use_hour_breach=False, midday_mode="Off",
                 tpsl_mode=tpsl_mode, point_value=point_value, **overrides)
    em = Emulator(capital, 0.37, mintick, point_value)
    strat = PulseStrategy(inp, em, mintick=mintick, tf_minutes=tf_minutes)

    for index, bar in enumerate(to_pulse_bars(bars)):
        em.process_bar(bar, index)
        strat.on_bar(bar, index, HTF_NEUTRAL, LTF_NEUTRAL)

    closed = list(em.closed)
    if not closed:
        return {"trades": 0, "net": 0.0, "expectancy": 0.0, "win_rate": 0.0}

    # ClosedTrade.profit is net of commission -- Pine's strategy.closedtrades.profit
    pnl = [float(t.profit) for t in closed]
    wins = [p for p in pnl if p > 0]
    from collections import Counter
    return {
        "trades": len(closed),
        "net": sum(pnl),
        "expectancy": st.fmean(pnl),
        "win_rate": 100.0 * len(wins) / len(closed),
        "mean_bars": st.fmean([t.bars for t in closed]),
        "mean_runup": st.fmean([t.runup for t in closed]),
        "mean_dd": st.fmean([t.drawdown for t in closed]),
        "exits": dict(Counter(t.exit_comment for t in closed).most_common(6)),
    }


def permutation_null(bars, *, runs: int, tf_minutes: int, seed: int = 3, **kw) -> dict:
    observed = run_pulse(bars, tf_minutes=tf_minutes, **kw)
    rng = random.Random(seed)
    beats, nulls = 0, []
    for _ in range(runs):
        surrogate = shuffle_bars(bars, rng)
        res = run_pulse(surrogate, tf_minutes=tf_minutes, **kw)
        nulls.append(res["net"])
        if res["net"] >= observed["net"]:
            beats += 1
    return {
        "observed": observed,
        "p_value": (beats + 1) / (runs + 1),
        "null_median_net": st.median(nulls) if nulls else 0.0,
        "null_best_net": max(nulls) if nulls else 0.0,
        "runs": runs,
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12000
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    tf = sys.argv[3] if len(sys.argv) > 3 else "20m"
    minutes = int(tf.rstrip("m"))

    src = synthetic_for(AssetClass.MICRO_FUTURES, n, seed=11, minutes=2)
    tape = resample(src, tf)
    print(f"pulse.py on {len(tape)} x {tf} MNQ bars, {runs} shuffled surrogates\n")

    mode = sys.argv[4] if len(sys.argv) > 4 else "ATR-Based"
    print(f"TP/SL mode: {mode}\n")
    out = permutation_null(tape, runs=runs, tf_minutes=minutes, tpsl_mode=mode)
    o = out["observed"]
    print(f"OBSERVED   trades {o['trades']:4d}  net ${o['net']:+12,.0f}  "
          f"per-trade ${o['expectancy']:+9,.0f}  win {o['win_rate']:5.1f}%  "
          f"hold {o.get('mean_bars',0):.1f} bars")
    print(f"           exits: {o.get('exits', {})}")
    print(f"NULL       median ${out['null_median_net']:+12,.0f}   "
          f"best of {out['runs']} ${out['null_best_net']:+12,.0f}")
    print(f"\np = {out['p_value']:.4f}   "
          f"{'SURVIVES the null' if out['p_value'] <= 0.05 else 'does NOT separate from shuffled noise'}")
