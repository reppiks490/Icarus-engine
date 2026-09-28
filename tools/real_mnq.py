"""Drive both engines over the real MNQ tape and report against the goal.

Everything before this ran on `synthetic_for()`. That tape is calibrated and
deterministic, which makes it good for catching regressions and useless for
deciding whether an edge is real. This is the first read on actual ticks.

The two-tape rule still holds, but on real data "two tapes" cannot mean two
seeds -- it means two disjoint spans, earliest for tuning and the most recent
year held out. A result that only clears on the first span is a curve fit with
a date on it.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icarus.config import AssetClass
from icarus.data import load_csv
from icarus.strategy import IcarusEngine
from tools.goal import Goal
from tools.htf_context import ContextProvider
from tools.metrics import analyse, from_icarus
from tools.validate_pulse import run_pulse

TAPE_FOR = lambda tf: Path(__file__).resolve().parent.parent / "data" / f"mnq_{tf}m_full.csv"
SPLIT = datetime(2025, 10, 1, tzinfo=timezone.utc)   # ~50/50 by session count


def _span_days(bars) -> float:
    return max((bars[-1].ts - bars[0].ts).total_seconds() / 86400.0, 1e-9)


def run_icarus(bars, policy: str, timeframe: str = "20m") -> dict:
    engine = IcarusEngine(AssetClass.MICRO_FUTURES, exit_policy=policy, timeframe=timeframe)
    for bar in bars:
        engine.on_bar(bar)
    trades = engine.blotter.trades
    if not trades:
        return {"error": "no trades", "trades": 0}
    return analyse(from_icarus(trades, bars), span_days=_span_days(bars)).as_dict()


def line(tag: str, r: dict) -> str:
    if r.get("error") or not r.get("trades"):
        return f"  {tag:<22s} {r.get('error', 'no trades')}"
    return (
        f"  {tag:<20s} n={r['trades']:4d} tpd={r.get('trades_per_day', 0):4.2f} "
        f"win={r.get('win_rate', 0):5.1f}% exp=${r.get('expectancy', 0):+8.2f} "
        f"PF={r.get('profit_factor', 0):5.2f} hold={r.get('mean_hold', 0):5.1f} "
        f"maxDD=${r.get('max_drawdown', 0):+9,.0f} net=${r.get('net', 0):+,.0f}"
    )


def main(tf: int = 20) -> None:
    bars = load_csv(str(TAPE_FOR(tf)))
    tune = [b for b in bars if b.ts < SPLIT]
    hold = [b for b in bars if b.ts >= SPLIT]
    print(f"REAL MNQ {tf}m CONTINUOUS -- {len(bars)} bars, {len({b.ts.date() for b in bars})} sessions")
    print(f"  TUNE {tune[0].ts.date()} .. {tune[-1].ts.date()}  {len(tune)} bars")
    print(f"  HOLD {hold[0].ts.date()} .. {hold[-1].ts.date()}  {len(hold)} bars\n")

    results: dict[str, tuple[dict, dict]] = {}

    print("--- icarus/ (my engine) ---")
    for policy in ("pulse", "suite", "hybrid"):
        rt, rh = run_icarus(tune, policy, f"{tf}m"), run_icarus(hold, policy, f"{tf}m")
        results[f"icarus:{policy}"] = (rh, rt)
        print(line(f"{policy} TUNE", rt))
        print(line(f"{policy} HOLD", rh))

    print("\n--- icarus_engine/strategy/pulse.py (Astra's, HTF context on) ---")
    for mode in ("ATR-Based", "Fixed Points"):
        out = []
        for name, seg in (("TUNE", tune), ("HOLD", hold)):
            ctx = ContextProvider(seg, f"{tf}m")
            r = run_pulse(seg, tf_minutes=tf, tpsl_mode=mode, context=ctx)
            out.append(r)
            print(line(f"{mode[:9]} {name}", r))
        results[f"pulse:{mode}"] = (out[1], out[0])

    goal = Goal()
    print("\n--- goal verdict (HOLD is what counts; TUNE must agree) ---")
    for tag, (rh, rt) in results.items():
        verdict = "QUALIFIES" if goal.clears(rh, rt) else "no"
        win = rh.get("win_rate", 0.0)
        print(f"  {tag:<24s} {verdict:<10s} hold-win={win:5.1f}%  n={rh.get('trades', 0)}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
