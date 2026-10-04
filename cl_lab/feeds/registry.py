# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.feeds.registry: feed catalogue and incremental cache refresh
"""refresh_all(cache_dir) fetches every feed, merges it into ``cache_dir/<name>.csv.gz``
and returns a JSON-safe manifest. It never raises for a feed failure: the error is
recorded and the other feeds continue. Raw rows are written ONLY under cache_dir."""
from __future__ import annotations

import os

import pandas as pd

from .. import store
from . import sources
from .http import FeedError

BINANCE_START = "2024-09"   # aligns with the committed MNQ tape (2024-09-20 onward)

FEEDS = [
    dict(name="btcusdt_5m", kind="binance", symbol="BTCUSDT", interval="5m", intraday=True),
    dict(name="ethusdt_5m", kind="binance", symbol="ETHUSDT", interval="5m", intraday=True),
    dict(name="btcusd_cb_5m", kind="coinbase", product="BTC-USD", intraday=True),
    *[dict(name=f"fred_{s.lower()}", kind="fred", series=s, intraday=False)
      for s in ("DGS10", "DGS2", "T10Y2Y", "DFF", "VIXCLS")],
    *[dict(name=f"cboe_{n.lower()}", kind="cboe", index=n, intraday=False)
      for n in ("VIX", "VIX9D", "VIX3M", "VVIX", "SKEW")],
    dict(name="cftc_tff_nasdaq", kind="cftc", intraday=False),
]


def _months(start: str, end_exclusive: pd.Period):
    p = pd.Period(start, "M")
    while p < end_exclusive:
        yield p
        p += 1


def refresh_binance(old: pd.DataFrame, symbol, interval, now: pd.Timestamp, max_requests=80):
    """Backfill complete months from BINANCE_START, then daily files of the current month up to yesterday."""
    frames, used, notes = [], 0, []
    cur = pd.Period(now.tz_convert("UTC").tz_localize(None), "M")
    have = set() if old is None or old.empty else set(old.index.tz_convert("UTC").strftime("%Y-%m-%d"))
    for m in _months(BINANCE_START, cur):
        last_day = m.end_time.strftime("%Y-%m-%d")
        if last_day in have or used >= max_requests:
            continue
        try:
            used += 1
            frames.append(sources.fetch_binance_bulk(symbol, interval, str(m)))
        except FeedError as e:
            notes.append(f"{m}: {e}")
            if "404" in str(e):  # monthly archive not published yet: fall back to that month's daily files
                d = m.start_time
                while d <= m.end_time.normalize() and used < max_requests:
                    ds = d.strftime("%Y-%m-%d")
                    if ds not in have:
                        try:
                            used += 1
                            frames.append(sources.fetch_binance_bulk(symbol, interval, ds))
                        except FeedError as e2:
                            notes.append(f"{ds}: {e2}")
                    d += pd.Timedelta(days=1)
    day = cur.start_time
    yday = (now.tz_convert("UTC").tz_localize(None).normalize() - pd.Timedelta(days=1))
    while day <= yday and used < max_requests:
        ds = day.strftime("%Y-%m-%d")
        if ds not in have:
            try:
                used += 1
                frames.append(sources.fetch_binance_bulk(symbol, interval, ds))
            except FeedError as e:
                notes.append(f"{ds}: {e}")
        day += pd.Timedelta(days=1)
    new = pd.concat(frames) if frames else pd.DataFrame()
    return store.merge_frames(old, new), used, notes


def _fetch(feed, old, now):
    k = feed["kind"]
    if k == "binance":
        return refresh_binance(old, feed["symbol"], feed["interval"], now)
    if k == "coinbase":
        df = sources.fetch_coinbase(feed["product"], 300, start=now - pd.Timedelta(days=3), end=now)
        return store.merge_frames(old, df), None, []
    if k == "fred":
        return store.merge_frames(old, sources.fetch_fred(feed["series"])), 1, []
    if k == "cboe":
        return store.merge_frames(old, sources.fetch_cboe(feed["index"])), 1, []
    if k == "cftc":
        df = sources.fetch_cftc_tff()
        if old is not None and not old.empty:
            df = pd.concat([old.reset_index(), df.reset_index()]).drop_duplicates(["date", "code"], keep="last")
            df = df.set_index("date").sort_index()
        return df, 1, []
    raise ValueError(k)


def refresh_all(cache_dir, only=None, now=None) -> dict:
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    os.makedirs(cache_dir, exist_ok=True)
    out = {"schema": "cl_lab.feeds.manifest/1", "generated_at": now.isoformat(), "feeds": {}}
    for feed in FEEDS:
        if only and feed["name"] not in only:
            continue
        path = os.path.join(cache_dir, f"{feed['name']}.csv.gz")
        intraday = feed["intraday"]
        try:
            old = store.load_frame(path, intraday=intraday) if feed["kind"] != "cftc" else _load_cftc(path)
            df, used, notes = _fetch(feed, old, now)
            if df is None or df.empty:
                raise FeedError("no rows")
            store.save_frame(df, path)
            ent = store.manifest_entry(feed["name"], df, "ok", intraday=intraday and feed["kind"] != "cftc")
            ent["requests"], ent["notes"] = used, notes[:10]
        except Exception as e:  # recorded, never raised: one dead feed must not stop the lab
            ent = store.manifest_entry(feed["name"], None, "error", error=f"{type(e).__name__}: {e}")
        ent["kind"] = feed["kind"]
        out["feeds"][feed["name"]] = ent
    return out


def _load_cftc(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, compression="gzip", index_col=0, dtype={"code": str})
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index), name="date")
    return df
