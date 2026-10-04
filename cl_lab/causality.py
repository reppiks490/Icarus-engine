# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.causality: reusable look-ahead checks for any rule run function
"""prefix_violations: trades of the first K sessions must not change when later
sessions are removed. intraday_violations: entries at or before a cut must not change
when every bar after the cut is replaced by garbage. Both take ``trades_fn(sess)``."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import bars, sessions

ET = "America/New_York"


def synth_frame(n_sessions=140, seed=3, start="2025-02-03"):
    """Random-walk 5m bars from 18:00 ET prior evening to 17:00 ET, weekdays, across a DST change."""
    rng = np.random.default_rng(seed)
    stamps, px, rows = [], 20000.0, []
    for d in pd.bdate_range(start, periods=n_sessions):
        t0 = pd.Timestamp(d.date()) - pd.Timedelta(hours=6)
        for k in range(276):
            stamps.append((t0 + pd.Timedelta(minutes=5 * k)).tz_localize(ET))
            o = px
            c = round((o + rng.normal(0, 3.0)) * 4) / 4
            h = max(o, c) + round(abs(rng.normal(0, 1.5)) * 4) / 4
            lo = min(o, c) - round(abs(rng.normal(0, 1.5)) * 4) / 4
            rows.append((o, h, lo, c, float(rng.integers(50, 500))))
            px = c
    df = pd.DataFrame(rows, columns=list(bars.COLUMNS))
    df.index = pd.DatetimeIndex(stamps).tz_convert("UTC").rename("ts_open")
    return df


def _key_day(trs, day, max_entry):
    return [(t.day, t.entry_slot, t.direction, t.entry_px) for t in trs if t.day == day and t.entry_slot <= max_entry]


def prefix_violations(frame, trades_fn, cuts=(90, 120), prepare=None):
    a = bars.annotate(frame)
    full = sessions.build_sessions(a)
    if prepare:
        prepare(full)
    ref = trades_fn(full)
    bad = []
    for K in cuts:
        s = sessions.build_sessions(a[a.session_date.isin(set(full.dates[:K]))])
        if prepare:
            prepare(s)
        got = [tuple(t.__dict__.values()) for t in trades_fn(s) if t.day < K]
        want = [tuple(t.__dict__.values()) for t in ref if t.day < K]
        if got != want:
            bad.append(K)
    return bad


def intraday_violations(frame, trades_fn, pairs, seed=99, prepare=None):
    a0, rng = bars.annotate(frame), np.random.default_rng(seed)
    base = sessions.build_sessions(a0)
    if prepare:
        prepare(base)
    ref = trades_fn(base)
    bad = []
    for d, s in pairs:
        m = (a0.session_date == base.dates[d]) & a0.rth & (((a0.minute_et - 570) // 5) > s)
        a = a0.copy()
        n = int(m.sum())
        o = rng.uniform(15000, 25000, n)
        c = o + rng.normal(0, 50, n)
        a.loc[m, "open"], a.loc[m, "close"] = o, c
        a.loc[m, "high"], a.loc[m, "low"] = np.maximum(o, c) + 30, np.minimum(o, c) - 30
        a.loc[m, "volume"] = rng.integers(1, 10_000, n).astype(float)
        s2 = sessions.build_sessions(a)
        if prepare:
            prepare(s2)
        if _key_day(ref, d, s) != _key_day(trades_fn(s2), d, s):
            bad.append((d, s))
    return bad
