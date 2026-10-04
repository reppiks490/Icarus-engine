# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.bars: load and annotate intraday bars (DST-correct, bar-open indexed)
"""Canonical intraday bar frames for the CL lab.

Canonical frame: index ``ts_open`` (tz-aware UTC, bar OPEN time), float columns
open/high/low/close/volume. ``data/mnq_*_full.csv`` stores bar CLOSE times in
``ts`` (first bar after the daily halt is stamped 18:05 ET), so ``load_csv``
shifts by one bar. Yahoo/Coinbase frames from ``cl_lab.feeds`` already use
bar-open times and can go straight into :func:`annotate`.
"""
from __future__ import annotations

import pandas as pd

ET = "America/New_York"
RTH_START_MIN = 9 * 60 + 30   # 09:30 ET
RTH_END_MIN = 16 * 60         # 16:00 ET (exclusive: last 5m bar opens 15:55)
GLOBEX_OPEN_HOUR = 18         # ET clock >= 18:00 belongs to the next session date
COLUMNS = ("open", "high", "low", "close", "volume")


def load_csv(path, tf_minutes: int = 5, stamp: str = "close") -> pd.DataFrame:
    """Read a ts,open,high,low,close,volume CSV into a canonical bar-open frame."""
    if stamp not in ("close", "open"):
        raise ValueError("stamp must be 'close' or 'open'")
    raw = pd.read_csv(path)
    ts = pd.to_datetime(raw["ts"], utc=True)
    if stamp == "close":
        ts = ts - pd.Timedelta(minutes=tf_minutes)
    out = raw[list(COLUMNS)].astype(float)
    out.index = pd.DatetimeIndex(ts, name="ts_open")
    if out.index.has_duplicates:
        raise ValueError(f"duplicate bar timestamps in {path}")
    return out.sort_index()


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """Add ET clock, Globex session date and RTH flag (tz conversion, never fixed offsets)."""
    if df.index.tz is None:
        raise ValueError("index must be tz-aware UTC bar-open times")
    out = df.copy()
    et = out.index.tz_convert(ET)
    minute = et.hour * 60 + et.minute
    cal = et.tz_localize(None).normalize()
    roll = pd.to_timedelta((et.hour >= GLOBEX_OPEN_HOUR).astype(int), unit="D")
    out["et"] = et
    out["minute_et"] = minute
    out["session_date"] = (cal + roll).date
    out["rth"] = (minute >= RTH_START_MIN) & (minute < RTH_END_MIN)
    return out
