# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.feeds.registry: feed catalogue and incremental cache refresh
"""refresh_all(cache_dir) fetches every feed, merges it into cache_dir/<name>.csv.gz
and returns a JSON-safe manifest. It never raises for a feed failure: the error is
recorded and the other feeds continue. Raw rows are written ONLY under cache_dir."""
from __future__ import annotations

import os

import pandas as pd

from .. import store
from . import databento as databento_feed, sources
from .http import FeedError

BINANCE_START = "2024-09"

# Continuous CME corpus families. Presence in this catalogue does NOT authorize
# a paid request. Scheduled Databento downloads additionally require an explicit
# CL_DATABENTO_ROOTS allowlist and are bounded by one aggregate refresh budget.
DATABENTO_FUTURES_ROOTS = (
    "NQ", "MNQ", "ES", "MES", "YM", "MYM", "RTY", "M2K",
    "GC", "MGC", "SI", "SIL", "PL", "PA", "BTC", "MBT",
)

FEEDS = [
    dict(name="btcusdt_5m", kind="binance", symbol="BTCUSDT", interval="5m", intraday=True),
    dict(name="ethusdt_5m", kind="binance", symbol="ETHUSDT", interval="5m", intraday=True),
    dict(name="btcusd_cb_5m", kind="coinbase", product="BTC-USD", intraday=True),
    *[dict(name=f"fred_{s.lower()}", kind="fred", series=s, intraday=False)
      for s in ("DGS10", "DGS2", "T10Y2Y", "DFF", "VIXCLS")],
    *[dict(name=f"cboe_{n.lower()}", kind="cboe", index=n, intraday=False)
      for n in ("VIX", "VIX9D", "VIX3M", "VVIX", "SKEW")],
    dict(name="cftc_tff_nasdaq", kind="cftc", intraday=False),
    *[dict(name=f"databento_{root.lower()}_5m", kind="databento", root=root, intraday=True)
      for root in DATABENTO_FUTURES_ROOTS],
]


def _months(start: str, end_exclusive: pd.Period):
    p = pd.Period(start, "M")
    while p < end_exclusive:
        yield p
        p += 1


def _databento_policy() -> tuple[set[str], float, str | None]:
    """Return selected roots, total USD cap, and any configuration error.

    DATABENTO_API_KEY proves authentication only. It is deliberately not treated
    as permission to spend on all catalogued futures.
    """
    raw = (os.environ.get("CL_DATABENTO_ROOTS") or "").strip()
    selected = {x.strip().upper() for x in raw.split(",") if x.strip()}
    unknown = sorted(selected - set(DATABENTO_FUTURES_ROOTS))
    if unknown:
        return set(), 0.0, "unknown CL_DATABENTO_ROOTS: " + ",".join(unknown)
    try:
        cap = float(os.environ.get("CL_DATABENTO_MAX_USD_PER_REFRESH") or "1.00")
    except ValueError:
        return selected, 0.0, "CL_DATABENTO_MAX_USD_PER_REFRESH must be numeric"
    if cap < 0:
        return selected, 0.0, "CL_DATABENTO_MAX_USD_PER_REFRESH must be >= 0"
    return selected, cap, None


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
            if "404" in str(e):
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
    yday = now.tz_convert("UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
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
    if k == "databento":
        raise RuntimeError("Databento feeds must pass refresh_all paid-request policy")
    raise ValueError(k)


def _databento_base_entry(feed, old, status: str, error: str | None = None) -> dict:
    ent = store.manifest_entry(feed["name"], old, status, error=error, intraday=True)
    ent.update(
        kind="databento",
        root=feed["root"],
        dataset="GLBX.MDP3",
        continuous_symbol=databento_feed.continuous_symbol(feed["root"]),
    )
    return ent


def refresh_all(cache_dir, only=None, now=None) -> dict:
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    os.makedirs(cache_dir, exist_ok=True)
    selected_roots, total_cap, policy_error = _databento_policy()
    db_key_present = bool((os.environ.get("DATABENTO_API_KEY") or "").strip())
    db_spend = 0.0
    out = {
        "schema": "cl_lab.feeds.manifest/1",
        "generated_at": now.isoformat(),
        "feeds": {},
        "databento_budget": {
            "key_configured": db_key_present,
            "selected_roots": sorted(selected_roots),
            "max_usd_per_refresh": total_cap,
            "estimated_spend_usd": 0.0,
            "remaining_usd": total_cap,
            "policy_error": policy_error,
        },
    }
    for feed in FEEDS:
        if only and feed["name"] not in only:
            continue
        path = os.path.join(cache_dir, f"{feed['name']}.csv.gz")
        intraday = feed["intraday"]

        if feed["kind"] == "databento":
            old = store.load_frame(path, intraday=True)
            if not db_key_present:
                status = "cached" if old is not None and not old.empty else "unconfigured"
                ent = _databento_base_entry(
                    feed, old, status,
                    error=None if status == "cached" else "DATABENTO_API_KEY not configured",
                )
                ent["selected"] = feed["root"] in selected_roots
                out["feeds"][feed["name"]] = ent
                continue
            if policy_error:
                ent = _databento_base_entry(feed, old, "blocked", error=policy_error)
                ent["selected"] = False
                out["feeds"][feed["name"]] = ent
                continue
            if feed["root"] not in selected_roots:
                status = "cached" if old is not None and not old.empty else "configured_dormant"
                ent = _databento_base_entry(feed, old, status)
                ent["selected"] = False
                out["feeds"][feed["name"]] = ent
                continue

            remaining = max(0.0, total_cap - db_spend)
            try:
                df, meta = databento_feed.fetch_continuous_5m(
                    feed["root"], old, now, budget_cap_usd=remaining
                )
                merged = store.merge_frames(old, df)
                if merged is None or merged.empty:
                    raise FeedError("no rows")
                store.save_frame(merged, path)
                if meta.get("request_performed"):
                    db_spend += float(meta.get("estimated_cost_usd") or 0.0)
                ent = store.manifest_entry(feed["name"], merged, "ok", intraday=True)
                ent.update(
                    requests=1 if meta.get("request_performed") else 0,
                    notes=[
                        f"symbol={meta.get('symbol')}",
                        f"estimated_cost_usd={meta.get('estimated_cost_usd', 0.0):.6f}",
                        f"request_performed={bool(meta.get('request_performed'))}",
                        f"range={meta.get('start')}..{meta.get('end')}",
                    ],
                    estimated_cost_usd=float(meta.get("estimated_cost_usd") or 0.0),
                    selected=True,
                )
            except Exception as e:
                ent = _databento_base_entry(
                    feed, old, "error", error=f"{type(e).__name__}: {e}"
                )
                ent["selected"] = True
            ent.update(
                root=feed["root"],
                dataset="GLBX.MDP3",
                continuous_symbol=databento_feed.continuous_symbol(feed["root"]),
            )
            out["feeds"][feed["name"]] = ent
            continue

        try:
            old = store.load_frame(path, intraday=intraday) if feed["kind"] != "cftc" else _load_cftc(path)
            df, used, notes = _fetch(feed, old, now)
            if df is None or df.empty:
                raise FeedError("no rows")
            store.save_frame(df, path)
            ent = store.manifest_entry(feed["name"], df, "ok", intraday=intraday and feed["kind"] != "cftc")
            ent["requests"], ent["notes"] = used, notes[:10]
        except Exception as e:
            ent = store.manifest_entry(feed["name"], None, "error", error=f"{type(e).__name__}: {e}")
        ent["kind"] = feed["kind"]
        out["feeds"][feed["name"]] = ent

    out["databento_budget"]["estimated_spend_usd"] = round(db_spend, 6)
    out["databento_budget"]["remaining_usd"] = round(max(0.0, total_cap - db_spend), 6)
    return out


def _load_cftc(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, compression="gzip", index_col=0, dtype={"code": str})
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index), name="date")
    return df
