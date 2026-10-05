# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.feeds.registry: feed catalogue and incremental cache refresh
"""refresh_all(cache_dir) fetches every feed, merges it into ``cache_dir/<name>.csv.gz``
and returns a JSON-safe manifest. It never raises for a feed failure: the error is
recorded and the other feeds continue. Raw rows are written ONLY under cache_dir."""
from __future__ import annotations

import os

import pandas as pd

from .. import store
from . import databento as databento_feed, databento_budget, sources
from .http import FeedError

BINANCE_START = "2024-09"   # aligns with the committed MNQ tape (2024-09-20 onward)

# Core continuous-futures corpus. Keep this exact registered ICARUS universe as
# the first spending priority.
DATABENTO_FUTURES_ROOTS = (
    "NQ", "MNQ", "ES", "MES", "YM", "MYM", "RTY", "M2K",
    "GC", "MGC", "SI", "SIL", "PL", "PA", "BTC", "MBT",
)

# Wider market-intelligence corpus. These are not automatically promoted to
# tradable ICARUS assets; they are context/evidence feeds. The initial 25-month
# OHLCV pass is still protected by CL_DATABENTO_MAX_USD_PER_FEED. With 16 core +
# 19 context feeds and the workflow's $3 cap, the hard theoretical maximum for
# one empty-cache refresh is $105 before any request that exceeds its cap is
# rejected.
DATABENTO_INTELLIGENCE_FUTURES = (
    # CFE volatility term structure / volatility microstructure.
    ("VX", "XCBF.PITCH", "volatility"),
    ("VXM", "XCBF.PITCH", "volatility"),
    # Rates / policy expectations.
    ("ZN", "GLBX.MDP3", "rates"),
    ("ZB", "GLBX.MDP3", "rates"),
    ("ZF", "GLBX.MDP3", "rates"),
    ("ZT", "GLBX.MDP3", "rates"),
    ("SR3", "GLBX.MDP3", "rates"),
    # Energy / inflation / growth.
    ("CL", "GLBX.MDP3", "energy"),
    ("MCL", "GLBX.MDP3", "energy"),
    ("NG", "GLBX.MDP3", "energy"),
    # Industrial metal / growth sensitivity.
    ("HG", "GLBX.MDP3", "industrial_metals"),
    # FX risk / dollar sensitivity.
    ("6E", "GLBX.MDP3", "fx"),
    ("6J", "GLBX.MDP3", "fx"),
    ("6B", "GLBX.MDP3", "fx"),
    ("6A", "GLBX.MDP3", "fx"),
    ("DX", "IFUS.IMPACT", "dollar_index"),
    # Agricultural inflation / broad commodity regime.
    ("ZC", "GLBX.MDP3", "agriculture"),
    ("ZS", "GLBX.MDP3", "agriculture"),
    ("ZW", "GLBX.MDP3", "agriculture"),
)

# CL 2026-10-04, owner decision: VXM and DX bars come from key #2 (secondary) over 15 months; VX is not
# requested (its history costs far more than the key #1 per-asset cap; VXM tracks the same index).
DATABENTO_SKIPPED = frozenset({"VX"})
DATABENTO_LANE_OVERRIDES = {
    "VXM": dict(account="secondary", start="2025-07-01T00:00:00Z", max_usd=20.0),
    "DX": dict(account="secondary", start="2025-07-01T00:00:00Z", max_usd=20.0),
}

FEEDS = [
    dict(name="btcusdt_5m", kind="binance", symbol="BTCUSDT", interval="5m", intraday=True),
    dict(name="ethusdt_5m", kind="binance", symbol="ETHUSDT", interval="5m", intraday=True),
    dict(name="btcusd_cb_5m", kind="coinbase", product="BTC-USD", intraday=True),
    *[dict(name=f"fred_{s.lower()}", kind="fred", series=s, intraday=False)
      for s in ("DGS10", "DGS2", "T10Y2Y", "DFF", "VIXCLS", "NASDAQ100")],
    *[dict(name=f"cboe_{n.lower()}", kind="cboe", index=n, intraday=False)
      for n in ("VIX", "VIX9D", "VIX3M", "VVIX", "SKEW")],
    dict(name="cftc_tff_nasdaq", kind="cftc", intraday=False),
    *[dict(name=f"databento_{root.lower()}_5m", kind="databento", root=root,
           dataset="GLBX.MDP3", research_role="core", intraday=True)
      for root in DATABENTO_FUTURES_ROOTS],
    *[dict(name=f"databento_{root.lower()}_5m", kind="databento", root=root,
           dataset=dataset, research_role=role, intraday=True, **DATABENTO_LANE_OVERRIDES.get(root, {}))
      for root, dataset, role in DATABENTO_INTELLIGENCE_FUTURES if root not in DATABENTO_SKIPPED],
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


def _fetch(feed, old, now, max_usd=None, charge=None):
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
        df, meta = databento_feed.fetch_continuous_5m(
            feed["root"], old, now, dataset=feed.get("dataset") or "GLBX.MDP3",
            account=feed.get("account"), start_default=feed.get("start"),
            max_usd=max_usd if max_usd is not None else feed.get("max_usd"), charge=charge,
        )
        notes = [
            f"symbol={meta.get('symbol')}",
            f"estimated_cost_usd={meta.get('estimated_cost_usd', 0.0):.6f}",
            f"request_performed={bool(meta.get('request_performed'))}",
            f"range={meta.get('start')}..{meta.get('end')}",
            f"account={meta.get('account')}",
        ] + ([f"fitted_to_cap_from_estimate={meta['fitted_to_cap']['full_range_estimate_usd']:.4f}"]
             if meta.get("fitted_to_cap") else [])
        return store.merge_frames(old, df), 1 if meta.get("request_performed") else 0, notes
    raise ValueError(k)


def _corpus_lane(lanes, feed, ledger_dir, cache_dir):
    """CL 2026-10-05: OHLCV top-ups are recorded per account and may never push an account past its
    estimated credit (``databento_budget``); the depth sweep owns everything else."""
    acct = (feed.get("account") or os.environ.get("CL_DATABENTO_OHLCV_ACCOUNT") or "primary").strip().lower()
    lane_id = f"corpus:{acct}"
    if lane_id not in databento_budget.CORPUS_LANES:
        return None
    if lane_id not in lanes:
        lanes[lane_id] = databento_budget.Lane(lane_id, ledger_dir, mirror=cache_dir)
        lanes[lane_id].run_spent = 0.0
    return lanes[lane_id]


def _feed_cap(feed) -> float:
    if feed.get("max_usd") is not None:
        return float(feed["max_usd"])
    return float(os.environ.get("CL_DATABENTO_MAX_USD_PER_FEED") or "1.00")


def refresh_all(cache_dir, only=None, now=None, ledger_dir=None) -> dict:
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    os.makedirs(cache_dir, exist_ok=True)
    ledger_dir = ledger_dir or os.environ.get("CL_SPEND_LEDGER_DIR") or databento_budget.LEDGER_DIR
    lanes = {}
    out = {"schema": "cl_lab.feeds.manifest/1", "generated_at": now.isoformat(), "feeds": {}}
    for feed in FEEDS:
        if only and feed["name"] not in only:
            continue
        path = os.path.join(cache_dir, f"{feed['name']}.csv.gz")
        intraday = feed["intraday"]
        # Databento is optional/paid. Absence of a key is a dormant capability,
        # not a broken public-feed cycle; preserve any prior cache without error.
        key_env = databento_feed.api_key_env(feed.get("account")) if feed["kind"] == "databento" else None
        if feed["kind"] == "databento" and not (os.environ.get(key_env) or "").strip():
            old = store.load_frame(path, intraday=True)
            status = "cached" if old is not None and not old.empty else "unconfigured"
            ent = store.manifest_entry(
                feed["name"], old, status,
                error=None if status == "cached" else f"{key_env} not configured",
                intraday=True,
            )
            ent.update(kind="databento", root=feed["root"],
                       dataset=feed.get("dataset") or "GLBX.MDP3",
                       research_role=feed.get("research_role"),
                       continuous_symbol=databento_feed.continuous_symbol(feed["root"]))
            out["feeds"][feed["name"]] = ent
            continue
        try:
            old = store.load_frame(path, intraday=intraday) if feed["kind"] != "cftc" else _load_cftc(path)
            lane = _corpus_lane(lanes, feed, ledger_dir, cache_dir) if feed["kind"] == "databento" else None
            cap = charge = None
            if lane is not None:
                # Never past the account's uncommitted credit, and never more than the account's reserve in
                # one run: the sweep reads this ledger from git, so one in-flight run is all it cannot see.
                acct = databento_budget.account_of(lane.lane)
                allow = min(lane.remaining, databento_budget.RESERVE_USD.get(acct, 0.0) - lane.run_spent)
                if allow <= 1e-9:
                    raise FeedError(f"credit guard: {lane.lane} may not spend more on its account this run; "
                                    "top-up refused (databento_budget)")
                cap = min(_feed_cap(feed), allow)

                def charge(est, fn, lane=lane, name=feed["name"]):
                    lane.run_spent += est
                    return databento_budget.paid_request(lane, est, f"OHLCV {name}", now.isoformat(), fn,
                                                         log=est >= 0.05)
            df, used, notes = _fetch(feed, old, now, max_usd=cap, charge=charge)
            if df is None or df.empty:
                raise FeedError("no rows")
            store.save_frame(df, path)
            ent = store.manifest_entry(feed["name"], df, "ok", intraday=intraday and feed["kind"] != "cftc")
            ent["requests"], ent["notes"] = used, notes[:10]
        except Exception as e:  # recorded, never raised: one dead feed must not stop the lab
            ent = store.manifest_entry(feed["name"], None, "error", error=f"{type(e).__name__}: {e}")
        ent["kind"] = feed["kind"]
        if feed["kind"] == "databento":
            ent.update(root=feed["root"], dataset=feed.get("dataset") or "GLBX.MDP3",
                       research_role=feed.get("research_role"),
                       continuous_symbol=databento_feed.continuous_symbol(feed["root"]))
        out["feeds"][feed["name"]] = ent
    return out


def _load_cftc(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, compression="gzip", index_col=0, dtype={"code": str})
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index), name="date")
    return df
