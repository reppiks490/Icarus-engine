# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.sessions: RTH session arrays with strictly causal per-day context
"""Day x slot arrays of RTH bars plus per-day context computed only from the past.

Every per-day scalar for day ``d`` uses days ``< d`` only, except ``on_*`` which
are the overnight (18:00 ET prior evening -> 09:30 ET) bars of the same session
and are fully known at 09:30 ET, before the first RTH bar opens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .bars import RTH_START_MIN

N_SLOTS = 78
SLOT_MIN = 5


def slot_of(hhmm: str) -> int:
    """Index of the RTH 5-minute bar that OPENS at ``hhmm`` ET (09:30 -> 0, 15:55 -> 77)."""
    h, m = (int(x) for x in hhmm.split(":"))
    s = (h * 60 + m - RTH_START_MIN) // SLOT_MIN
    if not 0 <= s <= N_SLOTS:
        raise ValueError(hhmm)
    return s


@dataclass
class Sessions:
    dates: np.ndarray
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    V: np.ndarray
    ts_open: np.ndarray
    complete: np.ndarray
    prev_close: np.ndarray
    prev_high: np.ndarray
    prev_low: np.ndarray
    on_high: np.ndarray
    on_low: np.ndarray
    on_close: np.ndarray
    atr14: np.ndarray
    vwap: np.ndarray
    n_slots: int = N_SLOTS
    slot_minutes: int = SLOT_MIN
    cache: dict = field(default_factory=dict, repr=False)

    @property
    def D(self) -> int:
        return len(self.dates)

    # ---- causal helpers shared by grammar families (memoised per Sessions) ----
    def regime_ok(self, regime: str) -> np.ndarray:
        """Eligibility mask. rv_d = mean of prior 20 sessions' RTH range/prev_close; ref = median of prior 250 rv (>=60)."""
        key = ("regime", regime)
        if key in self.cache:
            return self.cache[key]
        if regime == "all":
            ok = np.ones(self.D, bool)
        else:
            rng = (np.nanmax(self.H, axis=1) - np.nanmin(self.L, axis=1)) / self.prev_close
            rv = np.full(self.D, np.nan)
            for d in range(self.D):
                w = rng[max(0, d - 20):d]
                w = w[np.isfinite(w)]
                if len(w) >= 20:
                    rv[d] = w.mean()
            ok = np.zeros(self.D, bool)
            for d in range(self.D):
                hist = rv[max(0, d - 250):d]
                hist = hist[np.isfinite(hist)]
                if np.isfinite(rv[d]) and len(hist) >= 60:
                    ref = np.median(hist)
                    ok[d] = rv[d] > ref if regime == "vol_hi" else rv[d] <= ref
            if regime not in ("vol_hi", "vol_lo"):
                raise ValueError(regime)
        self.cache[key] = ok
        return ok

    def trailing_stat(self, name: str, values: np.ndarray, fn, window: int = 60, min_obs: int = 20) -> np.ndarray:
        """fn(values[d-window:d] finite) for each d; NaN until ``min_obs`` prior finite values exist."""
        key = ("trail", name, window, min_obs)
        if key in self.cache:
            return self.cache[key]
        out = np.full(self.D, np.nan)
        for d in range(self.D):
            w = values[max(0, d - window):d]
            w = w[np.isfinite(w)]
            if len(w) >= min_obs:
                out[d] = fn(w)
        self.cache[key] = out
        return out


def _cum_vwap(H, L, C, V):
    tp = (H + L + C) / 3.0
    have = np.isfinite(tp)
    pv = np.where(have & np.isfinite(V), tp * V, 0.0).cumsum(axis=1)
    vv = np.where(have & np.isfinite(V), V, 0.0).cumsum(axis=1)
    cnt = have.cumsum(axis=1)
    mean_tp = np.where(have, tp, 0.0).cumsum(axis=1) / np.maximum(cnt, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        vw = np.where(vv > 0, pv / np.where(vv > 0, vv, 1.0), mean_tp)
    vw[cnt == 0] = np.nan
    return vw


def build_sessions(adf: pd.DataFrame) -> Sessions:
    """Build Sessions from an :func:`cl_lab.bars.annotate` frame (5-minute bars)."""
    rth = adf[adf["rth"]]
    dates = np.array(sorted(set(rth["session_date"])), dtype=object)
    D = len(dates)
    pos = {d: i for i, d in enumerate(dates)}
    shape = (D, N_SLOTS)
    O, H, L, C, V = (np.full(shape, np.nan) for _ in range(5))
    ts = np.full(shape, -1, dtype=np.int64)
    di = np.fromiter((pos[d] for d in rth["session_date"]), dtype=np.int64, count=len(rth))
    sj = ((rth["minute_et"].to_numpy() - RTH_START_MIN) // SLOT_MIN).astype(np.int64)
    for arr, col in ((O, "open"), (H, "high"), (L, "low"), (C, "close"), (V, "volume")):
        arr[di, sj] = rth[col].to_numpy()
    ts[di, sj] = rth.index.asi8
    complete = np.isfinite(C).all(axis=1)

    last_c = np.array([row[np.isfinite(row)][-1] if np.isfinite(row).any() else np.nan for row in C])
    day_hi = np.nanmax(H, axis=1)
    day_lo = np.nanmin(L, axis=1)
    prev_close = np.r_[np.nan, last_c[:-1]]
    prev_high = np.r_[np.nan, day_hi[:-1]]
    prev_low = np.r_[np.nan, day_lo[:-1]]

    on = adf[(~adf["rth"]) & ((adf["minute_et"] < RTH_START_MIN) | (adf["minute_et"] >= 18 * 60))]
    on = on[on["session_date"].isin(pos)]
    on_high = np.full(D, np.nan)
    on_low = np.full(D, np.nan)
    on_close = np.full(D, np.nan)
    if len(on):
        g = on.groupby("session_date", sort=True)
        hi, lo, cl = g["high"].max(), g["low"].min(), g["close"].last()
        for d, v in hi.items():
            on_high[pos[d]] = v
        for d, v in lo.items():
            on_low[pos[d]] = v
        for d, v in cl.items():
            on_close[pos[d]] = v

    tr = np.maximum(day_hi, prev_close) - np.minimum(day_lo, prev_close)
    tr = np.where(np.isfinite(prev_close), tr, day_hi - day_lo)
    atr14 = np.full(D, np.nan)
    for d in range(14, D):
        w = tr[d - 14:d]
        if np.isfinite(w).all():
            atr14[d] = w.mean()
    return Sessions(dates=dates, O=O, H=H, L=L, C=C, V=V, ts_open=ts, complete=complete,
                    prev_close=prev_close, prev_high=prev_high, prev_low=prev_low,
                    on_high=on_high, on_low=on_low, on_close=on_close, atr14=atr14,
                    vwap=_cum_vwap(H, L, C, V))


def slot_array(sess: Sessions, adf: pd.DataFrame, col: str) -> np.ndarray:
    """D x 78 array of ``col`` aligned to ``sess`` (CL 2026-10-04; e.g. Binance taker_buy_volume)."""
    rth = adf[adf["rth"]]
    pos = {d: i for i, d in enumerate(sess.dates)}
    out = np.full((sess.D, N_SLOTS), np.nan)
    keep = rth["session_date"].map(lambda d: d in pos).to_numpy(bool)
    rth = rth[keep]
    di = np.fromiter((pos[d] for d in rth["session_date"]), dtype=np.int64, count=len(rth))
    sj = ((rth["minute_et"].to_numpy() - RTH_START_MIN) // SLOT_MIN).astype(np.int64)
    out[di, sj] = rth[col].to_numpy(float)
    return out
