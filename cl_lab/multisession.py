# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.multisession: time-exit holds across sessions with daily mark-to-market
"""Entry at the OPEN of slot s0 on session d0, or at that session's last available RTH close
when s0 == CLOSE; exit likewise on a later (d1, s1). No stops. Daily P&L is marked at each
session's last RTH close, so the per-session values telescope to the trade total; the
round-trip cost is charged half on the entry session and half on the exit session.

``daily_weights`` is the daily-close analogue for an index series (no intraday bars)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Result

CLOSE = 78


@dataclass(frozen=True)
class HoldTrade:
    day: int
    entry_slot: int
    entry_px: float
    exit_day: int
    exit_slot: int
    exit_px: float
    direction: int
    reason: str


def last_close(sess) -> np.ndarray:
    key = ("ms", "last_close")
    if key not in sess.cache:
        sess.cache[key] = np.array([row[np.isfinite(row)][-1] if np.isfinite(row).any() else np.nan for row in sess.C])
    return sess.cache[key]


def price_at(sess, d, s):
    return float(last_close(sess)[d]) if s == CLOSE else float(sess.O[d, s])


def spans_unadjusted_roll(sess, d0, d1) -> bool:
    for a, b in sess.cache.get("roll_unadjusted_windows", ()):
        if sess.dates[d0] <= b and sess.dates[d1] >= a:
            return True
    return False


def hold_trade(sess, d0, s0, d1, s1, direction, reason="time"):
    """A HoldTrade, or None when a referenced price is missing or the hold spans an unadjusted roll."""
    if not (0 <= d0 <= d1 < sess.D) or (d1 == d0 and s1 <= s0) or direction == 0:
        return None
    p0, p1 = price_at(sess, d0, s0), price_at(sess, d1, s1)
    if not (np.isfinite(p0) and np.isfinite(p1)):
        return None
    if d1 > d0 and spans_unadjusted_roll(sess, d0, d1):
        return None
    return HoldTrade(int(d0), int(s0), p0, int(d1), int(s1), p1, int(np.sign(direction)), reason)


def to_result(trades, sess, cost) -> Result:
    D = sess.D
    cols = ["day", "date", "entry_slot", "exit_day", "exit_slot", "direction", "entry_px", "exit_px",
            "gross_pts", "net_pts", "net_usd", "net_ret", "reason"]
    daily, dret = np.zeros(D), np.zeros(D)
    if not trades:
        return Result(pd.DataFrame(columns=cols), daily, daily.copy(), 0, dret)
    mark = pd.Series(last_close(sess)).ffill().to_numpy()
    rows = []
    for t in trades:
        rt = float(cost.trade_cost_points(np.array([t.entry_px]))[0])
        g = t.direction
        if t.exit_day == t.day:
            alloc = {t.day: g * (t.exit_px - t.entry_px) - rt}
        else:
            alloc = {t.day: g * (mark[t.day] - t.entry_px) - rt / 2}
            for d in range(t.day + 1, t.exit_day):
                alloc[d] = g * (mark[d] - mark[d - 1])
            alloc[t.exit_day] = g * (t.exit_px - mark[t.exit_day - 1]) - rt / 2
        for d, v in alloc.items():
            daily[d] += v
            dret[d] += v / t.entry_px
        gross = g * (t.exit_px - t.entry_px)
        rows.append(dict(t.__dict__, date=sess.dates[t.day], gross_pts=gross, net_pts=gross - rt,
                         net_usd=(gross - rt) * cost.point_value, net_ret=(gross - rt) / t.entry_px))
    return Result(pd.DataFrame(rows)[cols], daily, daily * cost.point_value, len(trades), dret)


def daily_weights(ret: np.ndarray, w: np.ndarray, cost_bp_rt: float) -> np.ndarray:
    """Net daily return of holding weight w[t] from close t-1 to close t. Changing the weight at
    close t (from w[t] to w[t+1]) costs |w[t+1] - w[t]| * half the round trip, charged to day t."""
    w = np.asarray(w, float)
    nxt = np.r_[w[1:], 0.0]
    return w * np.nan_to_num(ret) - np.abs(nxt - w) * cost_bp_rt / 2 / 1e4
