# ChatGPT — 2026-10-04 — optional Databento continuous-futures corpus feed for CL Lab
"""Cost-gated Databento historical ingestion for the CL research corpus.

This module is intentionally separate from trading execution. It downloads only
continuous CME OHLCV into the ephemeral CL cache, never commits raw vendor rows,
and estimates request cost before any historical download.

Environment:
- DATABENTO_API_KEY: required to activate the feed.
- DATABENTO_DATASET: must remain GLBX.MDP3 (default).
- DATABENTO_ROLL_RULE: v, n, or c (default v).
- CL_DATABENTO_START: first uncached timestamp (default 2024-09-01T00:00:00Z).
- CL_DATABENTO_MAX_USD_PER_FEED: hard estimated-cost cap per individual request
  (default 1.00 USD). Raise only intentionally after reviewing the estimate.
- CL_DATABENTO_MAX_USD_PER_REFRESH: enforced by the registry across all selected
  Databento roots in one refresh (default 1.00 USD total).
- CL_DATABENTO_ROOTS: explicit comma-separated paid-feed allowlist. A key alone
  does not authorize scheduled historical downloads.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from .http import FeedError

DATASET = "GLBX.MDP3"
BAR_COLS = ("open", "high", "low", "close", "volume")
DEFAULT_START = "2024-09-01T00:00:00Z"


def continuous_symbol(root: str, roll_rule: str | None = None) -> str:
    root = str(root).strip().upper()
    if not root or not root.replace("_", "").isalnum():
        raise ValueError(f"invalid Databento futures root {root!r}")
    rule = (roll_rule or os.environ.get("DATABENTO_ROLL_RULE") or "v").strip().lower()
    if rule not in ("v", "n", "c"):
        raise ValueError("DATABENTO_ROLL_RULE must be v, n, or c")
    return f"{root}.{rule}.0"


def _client(api_key: str | None = None) -> Any:
    key = (api_key or os.environ.get("DATABENTO_API_KEY") or "").strip()
    if not key:
        raise FeedError("DATABENTO_API_KEY not configured")
    try:
        import databento as db  # type: ignore
    except Exception as ex:
        raise FeedError("Databento SDK unavailable; install databento>=0.87,<1") from ex
    return db.Historical(key)


def _as_ohlcv_1m(store: Any) -> pd.DataFrame:
    """Normalize a Databento DBNStore/to_df result to UTC bar-open OHLCV."""
    try:
        raw = store.to_df()
    except Exception as ex:
        raise FeedError(f"Databento response conversion failed: {type(ex).__name__}: {ex}") from ex
    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=BAR_COLS, index=pd.DatetimeIndex([], tz="UTC", name="ts_open"))
    df = raw.copy()
    if "ts_event" in df.columns:
        idx = pd.to_datetime(df.pop("ts_event"), utc=True)
    else:
        idx = pd.to_datetime(df.index, utc=True)
    missing = [c for c in BAR_COLS if c not in df.columns]
    if missing:
        raise FeedError("Databento OHLCV response missing columns: " + ", ".join(missing))
    out = df[list(BAR_COLS)].apply(pd.to_numeric, errors="coerce")
    out.index = pd.DatetimeIndex(idx, name="ts_open")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=["open", "high", "low", "close"])


def resample_5m(one_minute: pd.DataFrame) -> pd.DataFrame:
    if one_minute.empty:
        return one_minute.copy()
    r = one_minute.resample("5min", origin="epoch", label="left", closed="left")
    out = pd.DataFrame({
        "open": r["open"].first(),
        "high": r["high"].max(),
        "low": r["low"].min(),
        "close": r["close"].last(),
        "volume": r["volume"].sum(),
    })
    out.index.name = "ts_open"
    return out.dropna(subset=["open", "high", "low", "close"])


def fetch_continuous_5m(
    root: str,
    old: pd.DataFrame | None,
    now: pd.Timestamp,
    *,
    client: Any = None,
    budget_cap_usd: float | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch an incremental cost-gated continuous contract and return 5m bars.

    Existing cache is deliberately re-fetched from its last 5m bucket so the
    final bucket can be corrected without creating a gap.
    """
    dataset = (os.environ.get("DATABENTO_DATASET") or DATASET).strip()
    if dataset != DATASET:
        raise FeedError(f"CL futures corpus requires {DATASET}, got {dataset!r}")
    symbol = continuous_symbol(root)
    now = pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    # Keep historical requests on a complete 10-minute boundary; this avoids
    # paying for/recording a partially formed terminal 5m bar.
    end = now.floor("10min")
    if old is not None and not old.empty:
        last = pd.Timestamp(old.index[-1])
        start = last.tz_localize("UTC") if last.tzinfo is None else last.tz_convert("UTC")
    else:
        start = pd.Timestamp(os.environ.get("CL_DATABENTO_START") or DEFAULT_START)
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    if end <= start:
        return pd.DataFrame(columns=BAR_COLS, index=pd.DatetimeIndex([], tz="UTC", name="ts_open")), {
            "symbol": symbol,
            "estimated_cost_usd": 0.0,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "request_performed": False,
        }

    client = client or _client()
    kwargs = dict(
        dataset=dataset,
        symbols=symbol,
        schema="ohlcv-1m",
        stype_in="continuous",
        start=start.isoformat(),
        end=end.isoformat(),
    )
    try:
        estimate = float(client.metadata.get_cost(**kwargs))
    except Exception as ex:
        raise FeedError(f"Databento cost estimate failed for {symbol}: {type(ex).__name__}: {ex}") from ex
    try:
        cap = float(os.environ.get("CL_DATABENTO_MAX_USD_PER_FEED") or "1.00")
    except ValueError as ex:
        raise FeedError("CL_DATABENTO_MAX_USD_PER_FEED must be numeric") from ex
    if cap < 0:
        raise FeedError("CL_DATABENTO_MAX_USD_PER_FEED must be >= 0")
    if budget_cap_usd is not None:
        try:
            remaining = float(budget_cap_usd)
        except (TypeError, ValueError) as ex:
            raise FeedError("Databento refresh budget must be numeric") from ex
        if remaining < 0:
            raise FeedError("Databento refresh budget must be >= 0")
        effective_cap = min(cap, remaining)
    else:
        remaining = None
        effective_cap = cap
    if estimate > effective_cap + 1e-12:
        scope = (
            f"remaining refresh budget=${effective_cap:.6f}"
            if remaining is not None and effective_cap < cap
            else f"CL_DATABENTO_MAX_USD_PER_FEED=${cap:.2f}"
        )
        raise FeedError(
            f"Databento estimated cost ${estimate:.6f} for {symbol} exceeds {scope}; no data requested"
        )
    try:
        store = client.timeseries.get_range(**kwargs)
    except Exception as ex:
        raise FeedError(f"Databento historical request failed for {symbol}: {type(ex).__name__}: {ex}") from ex
    frame = resample_5m(_as_ohlcv_1m(store))
    return frame, {
        "symbol": symbol,
        "dataset": dataset,
        "roll_rule": symbol.split(".")[-2],
        "schema_source": "ohlcv-1m",
        "schema_output": "ohlcv-5m-derived",
        "estimated_cost_usd": estimate,
        "cost_cap_usd": effective_cap,
        "per_feed_cost_cap_usd": cap,
        "refresh_budget_cap_usd": remaining,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "request_performed": True,
    }
