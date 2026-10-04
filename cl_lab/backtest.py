# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.backtest: causal bracket simulation and per-day P&L
"""Execution model: entries/exits at bar OPEN prices of the next bar after a
decision, or at the session's last close. Stops/targets are checked from the
entry bar onward; a bar touching both counts as the stop (conservative); a bar
opening beyond the stop fills at its open (gap-through)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .costs import CostModel


@dataclass(frozen=True)
class Trade:
    day: int
    entry_slot: int
    entry_px: float
    exit_slot: int
    exit_px: float
    direction: int
    reason: str


def simulate_bracket(sess, d, entry_slot, direction, stop=np.nan, target=np.nan, exit_slot=78):
    """Return (exit_slot, exit_px, reason). exit_slot 78 means the close of bar 77."""
    O, H, L, C = sess.O[d], sess.H[d], sess.L[d], sess.C[d]
    has_stop, has_tgt = np.isfinite(stop), np.isfinite(target)
    last = min(exit_slot, sess.n_slots)
    for j in range(entry_slot, last):
        o, h, l = O[j], H[j], L[j]
        if direction > 0:
            if has_stop and (l <= stop):
                return j, (o if o < stop else stop), "stop"
            if has_tgt and (h >= target):
                return j, (o if o > target else target), "target"
        else:
            if has_stop and (h >= stop):
                return j, (o if o > stop else stop), "stop"
            if has_tgt and (l <= target):
                return j, (o if o < target else target), "target"
    if exit_slot >= sess.n_slots:
        return sess.n_slots, C[sess.n_slots - 1], "eod"
    return exit_slot, O[exit_slot], "time"


def bracket_trade(sess, d, entry_slot, direction, stop=np.nan, target=np.nan, exit_slot=78):
    xs, xp, why = simulate_bracket(sess, d, entry_slot, direction, stop, target, exit_slot)
    return Trade(d, entry_slot, float(sess.O[d, entry_slot]), xs, float(xp), int(direction), why)


@dataclass
class Result:
    trades: pd.DataFrame
    daily_net_pts: np.ndarray
    daily_net_usd: np.ndarray
    n_trades: int
    daily_net_ret: np.ndarray = None


def run(candidate, sess, cost: CostModel) -> Result:
    from .grammar import FAMILIES
    trades = FAMILIES[candidate.family].trades(sess, dict(candidate.params))
    return to_result(trades, sess, cost)


def to_result(trades, sess, cost: CostModel) -> Result:
    D = sess.D
    if not trades:
        cols = ["day", "date", "entry_slot", "exit_slot", "direction", "entry_px", "exit_px",
                "gross_pts", "net_pts", "net_usd", "reason"]
        return Result(pd.DataFrame(columns=cols), np.zeros(D), np.zeros(D), 0, np.zeros(D))
    t = pd.DataFrame([tr.__dict__ for tr in trades])
    t["date"] = [sess.dates[d] for d in t["day"]]
    t["gross_pts"] = t["direction"] * (t["exit_px"] - t["entry_px"])
    t["net_pts"] = t["gross_pts"] - cost.trade_cost_points(t["entry_px"].to_numpy())
    t["net_usd"] = t["net_pts"] * cost.point_value
    t["net_ret"] = t["net_pts"] / t["entry_px"]
    daily = np.zeros(D)
    np.add.at(daily, t["day"].to_numpy(), t["net_pts"].to_numpy())
    dret = np.zeros(D)
    np.add.at(dret, t["day"].to_numpy(), t["net_ret"].to_numpy())
    return Result(t, daily, daily * cost.point_value, len(t), dret)


def summary(res: Result) -> dict:
    t = res.trades
    if res.n_trades == 0:
        return dict(n_trades=0, win_rate=None, avg_net_pts=None, total_net_usd=0.0,
                    profit_factor=None, max_drawdown_usd=0.0, trades_per_day=0.0)
    wins = t.loc[t.net_usd > 0, "net_usd"].sum()
    losses = -t.loc[t.net_usd < 0, "net_usd"].sum()
    eq = np.cumsum(res.daily_net_usd)
    dd = float(np.max(np.maximum.accumulate(np.r_[0.0, eq])[1:] - eq)) if len(eq) else 0.0
    return dict(n_trades=int(res.n_trades), win_rate=float((t.net_usd > 0).mean()),
                avg_net_pts=float(t.net_pts.mean()), total_net_usd=float(t.net_usd.sum()),
                profit_factor=(float(wins / losses) if losses > 0 else None),
                max_drawdown_usd=dd, trades_per_day=float(res.n_trades / max(1, len(res.daily_net_usd))))
