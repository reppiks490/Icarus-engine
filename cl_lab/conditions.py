# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.conditions: causal day-level conditioners for the edge explorer
"""Day filters known before the RTH open of day d: prior-session shape, the
overnight gap/range (known at 09:30 ET), day of week, and external daily series
(e.g. Cboe VIX) taken from the last observation dated strictly before d."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _prev_ext(sess, name):
    """External daily series aligned causally: value of the last date < session date."""
    ser = sess.cache.get(("ext", name))
    if ser is None or len(ser) == 0:
        return None
    s = ser.dropna().sort_index()
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(sess.dates)))
    pos = s.index.searchsorted(idx, side="left") - 1
    vals = np.where(pos >= 0, s.to_numpy()[np.clip(pos, 0, None)], np.nan)
    return vals.astype(float)


def _trail_median(sess, key, x, window):
    return sess.trailing_stat(key, x, np.median, window, min(window, 20))


def mask(sess, cond: str) -> np.ndarray:
    key = ("cond", cond)
    if key in sess.cache:
        return sess.cache[key]
    D = sess.D
    out = np.ones(D, bool)
    if cond == "none":
        pass
    elif cond in ("prev_up", "prev_down"):
        last_c = np.r_[np.nan, sess.C[:-1, -1]]
        first_o = np.r_[np.nan, sess.O[:-1, 0]]
        up = last_c > first_o
        out = up if cond == "prev_up" else (last_c < first_o)
    elif cond in ("gap_up", "gap_down"):
        g = sess.on_close - sess.prev_close
        out = g > 0 if cond == "gap_up" else g < 0
    elif cond in ("on_wide", "on_narrow"):
        r = sess.on_high - sess.on_low
        med = _trail_median(sess, "cond|on_range", r, 60)
        out = (r > med) if cond == "on_wide" else (r <= med)
    elif cond in ("dow_mon", "dow_fri", "dow_mid"):
        dow = pd.to_datetime(pd.Series(sess.dates)).dt.dayofweek.to_numpy()
        out = {"dow_mon": dow == 0, "dow_fri": dow == 4, "dow_mid": (dow >= 1) & (dow <= 3)}[cond]
    elif cond in ("vix_high", "vix_low"):
        v = _prev_ext(sess, "VIX_close")
        if v is None:
            out = np.zeros(D, bool)
        else:
            med = _trail_median(sess, "cond|vix", v, 250)
            out = (v > med) if cond == "vix_high" else (v <= med)
    elif cond in ("vix_inverted", "vix_contango"):
        a, b = _prev_ext(sess, "VIX9D_close"), _prev_ext(sess, "VIX_close")
        if a is None or b is None:
            out = np.zeros(D, bool)
        else:
            out = (a > b) if cond == "vix_inverted" else (a <= b)
    else:
        raise ValueError(cond)
    out = np.asarray(out, bool) & np.isfinite(np.where(out, 1.0, 1.0))
    sess.cache[key] = out
    return out


CONDITIONS = ("none", "prev_up", "prev_down", "gap_up", "gap_down", "on_wide", "on_narrow",
              "dow_mon", "dow_fri", "dow_mid", "vix_high", "vix_low", "vix_inverted", "vix_contango")
