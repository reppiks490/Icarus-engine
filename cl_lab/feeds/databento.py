# ChatGPT — 2026-10-04 — optional Databento continuous-futures corpus feed for CL Lab
"""Cost-gated Databento historical ingestion for the CL research corpus.

This module is intentionally separate from trading execution. It downloads only
continuous CME OHLCV into the ephemeral CL cache, never commits raw vendor rows,
and estimates request cost before any historical download.

Environment:
- DATABENTO_API_KEY: primary credential, required for the broad OHLCV lane.
- DATABENTO_API_KEY_SECONDARY: optional isolated credential for depth-data planning.
- DATABENTO_API_KEY_THIRD: optional third isolated credential for depth-data planning.
- CL_DATABENTO_OHLCV_ACCOUNT: primary|secondary|third (default primary).
- DATABENTO_DATASET: must remain GLBX.MDP3 (default).
- DATABENTO_ROLL_RULE: v, n, or c (default v).
- CL_DATABENTO_START: first uncached timestamp (default 2024-09-01T00:00:00Z).
- CL_DATABENTO_HISTORICAL_LAG_MINUTES: safety lag behind the vendor's
  historical availability watermark (default 500 minutes).
- CL_DATABENTO_MAX_USD_PER_FEED: hard estimated-cost cap per refresh request
  (default 1.00 USD). Raise only intentionally after reviewing the estimate.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from .http import FeedError

DATASET = "GLBX.MDP3"
SUPPORTED_DATASETS = ("GLBX.MDP3", "XCBF.PITCH", "IFUS.IMPACT")
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


def _normalize_account(account: str | None) -> str:
    value = (account or "primary").strip().lower()
    if value not in ("primary", "secondary", "third"):
        raise FeedError("Databento account must be primary, secondary, or third")
    return value


def api_key_env(account: str | None = None) -> str:
    return {"primary": "DATABENTO_API_KEY", "secondary": "DATABENTO_API_KEY_SECONDARY", "third": "DATABENTO_API_KEY_THIRD"}[_normalize_account(account)]


def account_configured(account: str | None = None) -> bool:
    return bool((os.environ.get(api_key_env(account)) or "").strip())


def historical_client(api_key: str | None = None, *, account: str | None = None) -> Any:
    env_name = api_key_env(account)
    key = (api_key or os.environ.get(env_name) or "").strip()
    if not key:
        raise FeedError(f"{env_name} not configured")
    try:
        import databento as db  # type: ignore
    except Exception as ex:
        raise FeedError("Databento SDK unavailable; install databento>=0.87,<1") from ex
    return db.Historical(key)


def _client(api_key: str | None = None, *, account: str | None = None) -> Any:
    # Backward-compatible private alias used by older callers/tests.
    return historical_client(api_key, account=account)


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
    keep = list(BAR_COLS) + (["instrument_id"] if "instrument_id" in df.columns else [])  # CL: exact roll points
    out = df[keep].apply(pd.to_numeric, errors="coerce")
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
    if "instrument_id" in one_minute.columns:  # CL 2026-10-04: contract of the bar's last minute (roll audit)
        out["instrument_id"] = r["instrument_id"].last()
    out.index.name = "ts_open"
    return out.dropna(subset=["open", "high", "low", "close"])


def fetch_continuous_5m(
    root: str,
    old: pd.DataFrame | None,
    now: pd.Timestamp,
    *,
    client: Any = None,
    dataset: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch an incremental cost-gated continuous contract and return 5m bars.

    Existing cache is deliberately re-fetched from its last 5m bucket so the
    final bucket can be corrected without creating a gap.
    """
    dataset = (dataset or os.environ.get("DATABENTO_DATASET") or DATASET).strip()
    if dataset not in SUPPORTED_DATASETS:
        raise FeedError(
            f"unsupported Databento futures dataset {dataset!r}; "
            f"supported={','.join(SUPPORTED_DATASETS)}"
        )
    symbol = continuous_symbol(root)
    now = pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    # Historical usage access can lag wall-clock time even when cost estimation
    # succeeds. Keep a safety margin behind the vendor watermark so a paid request
    # cannot fail after passing the cost gate merely because the terminal range is
    # still subscription-only/live. The observed account watermark on 2026-10-04
    # was ~8 hours; default to 500 minutes (8h20m) and make it configurable.
    try:
        historical_lag_minutes = int(os.environ.get("CL_DATABENTO_HISTORICAL_LAG_MINUTES") or "500")
    except ValueError as ex:
        raise FeedError("CL_DATABENTO_HISTORICAL_LAG_MINUTES must be an integer") from ex
    if historical_lag_minutes < 0:
        raise FeedError("CL_DATABENTO_HISTORICAL_LAG_MINUTES must be >= 0")
    end = (now - pd.Timedelta(minutes=historical_lag_minutes)).floor("10min")
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

    account = (os.environ.get("CL_DATABENTO_OHLCV_ACCOUNT") or "primary").strip().lower()
    if account not in ("primary", "secondary", "third"):
        raise FeedError("CL_DATABENTO_OHLCV_ACCOUNT must be primary, secondary, or third")
    client = client or historical_client(account=account)
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
    if estimate > cap + 1e-12:
        raise FeedError(
            f"Databento estimated cost ${estimate:.6f} for {symbol} exceeds "
            f"CL_DATABENTO_MAX_USD_PER_FEED=${cap:.2f}; no data requested"
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
        "cost_cap_usd": cap,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "request_performed": True,
        "historical_lag_minutes": historical_lag_minutes,
        "account": account,
        "api_key_env": api_key_env(account),
    }
