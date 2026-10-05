# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.external: read-only use of the external data fabric cache
"""The external-data-fabric workflow (Tiingo, FMP, EODHD; other lane) stores raw payloads in its own
Actions cache (``.external_data_cache``). The CL lab restores that cache read-only, so using it costs
no API calls. Only derived daily series leave this module."""
from __future__ import annotations

import gzip
import json
import os

import pandas as pd

MEGA8 = ("NVDA", "AAPL", "MSFT", "AVGO", "AMZN", "META", "GOOGL", "TSLA")


def _read(path):
    try:
        with open(path, "rb") as f:
            return json.loads(gzip.decompress(f.read()).decode("utf-8"))
    except (OSError, ValueError):
        return None


def tiingo_closes(root: str, symbols=MEGA8) -> pd.DataFrame:
    """Adjusted daily closes (date index, one column per symbol) from the cached Tiingo EOD payloads."""
    cols = {}
    for s in symbols:
        rows = _read(os.path.join(root, "tiingo", "eod", f"{s}.json.gz"))
        if not isinstance(rows, list) or not rows:
            continue
        f = pd.DataFrame(rows)
        if "date" not in f:
            continue
        col = "adjClose" if "adjClose" in f else "close"
        idx = pd.to_datetime(f["date"], utc=True, errors="coerce").dt.tz_localize(None).dt.normalize()
        cols[s] = pd.Series(pd.to_numeric(f[col], errors="coerce").to_numpy(), index=idx).groupby(level=0).last()
    return pd.DataFrame(cols).sort_index()


def breadth(closes: pd.DataFrame, min_names: int = 5) -> pd.Series:
    """Fraction of the megacaps (with a price on both days) that closed up on each date; NaN when
    fewer than ``min_names`` have data. Dated by the session it describes; consumers must lag it."""
    if closes.empty:
        return pd.Series(dtype=float)
    r = closes.pct_change(fill_method=None)
    n = r.notna().sum(axis=1)
    out = (r > 0).sum(axis=1) / n.where(n > 0)
    return out.where(n >= min_names).dropna().rename("MEGA8_UP_FRAC")
