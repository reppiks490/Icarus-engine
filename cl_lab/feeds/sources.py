# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.feeds.sources: keyless public feeds (parsers split from fetchers)
"""Keyless sources verified live from a US cloud IP on 2026-10-04 (CL research notes,
costs_conventions_data_feeds.md): FRED fredgraph.csv, Cboe CDN CSVs (307 -> cdn-api),
CFTC PRE Socrata TFF (gpe5-46if), Coinbase Exchange candles, Binance public bulk
klines (data.binance.vision). Yahoo is deliberately NOT used: its terms ban
automated collection and it returned HTTP 429 to cloud IPs.

Licensing: raw rows stay in the Actions cache only; the repo gets derived
statistics and manifests (row counts, coverage, sha256).
"""
from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pandas as pd

from .http import FeedError, get_bytes

BAR_COLS = ["open", "high", "low", "close", "volume"]


def _intraday(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index.name = "ts_open"
    return df


# ---------------- FRED ----------------
def parse_fred(raw: bytes, series_id: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), na_values=["."], keep_default_na=True)
    date_col = "observation_date" if "observation_date" in df.columns else "DATE"
    out = pd.DataFrame({series_id: pd.to_numeric(df[series_id], errors="coerce").to_numpy()},
                       index=pd.to_datetime(df[date_col]).dt.normalize())
    out.index.name = "date"
    return out


def fetch_fred(series_id: str) -> pd.DataFrame:
    return parse_fred(get_bytes("https://fred.stlouisfed.org/graph/fredgraph.csv", {"id": series_id}), series_id)


# ---------------- Cboe ----------------
def parse_cboe(raw: bytes, name: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [c.strip().upper() for c in df.columns]
    idx = pd.to_datetime(df["DATE"], format="%m/%d/%Y")
    vals = df.drop(columns=["DATE"])
    if vals.shape[1] == 1:
        vals.columns = [f"{name}_close"]
    else:
        vals.columns = [f"{name}_{c.lower()}" for c in vals.columns]
    out = vals.apply(pd.to_numeric, errors="coerce")
    out.index = pd.DatetimeIndex(idx, name="date")
    return out


def fetch_cboe(name: str) -> pd.DataFrame:
    return parse_cboe(get_bytes(f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{name}_History.csv"), name)


# ---------------- CFTC TFF ----------------
TFF_PREFIXES = ("dealer_positions_", "asset_mgr_positions_", "lev_money_positions_",
                "other_rept_positions_", "nonrept_positions_")


def parse_cftc(raw: bytes) -> pd.DataFrame:
    recs = json.loads(raw)
    rows, found = [], set()
    for r in recs:
        row = {"date": pd.to_datetime(r.get("report_date_as_yyyy_mm_dd")).normalize(),
               "code": r.get("cftc_contract_market_code"), "market": r.get("market_and_exchange_names"),
               "open_interest_all": pd.to_numeric(r.get("open_interest_all"), errors="coerce")}
        for k, v in r.items():
            if k.startswith(TFF_PREFIXES):
                row[k] = pd.to_numeric(v, errors="coerce")
                found.add(k)
        rows.append(row)
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(["date", "code"]).set_index("date")
    out.attrs["numeric_fields_found"] = sorted(found)
    return out


def fetch_cftc_tff(codes=("209742", "209747", "20974+"), limit=20000) -> pd.DataFrame:
    where = " OR ".join(f"cftc_contract_market_code='{c}'" for c in codes)
    raw = get_bytes("https://publicreporting.cftc.gov/resource/gpe5-46if.json",
                    {"$where": where, "$order": "report_date_as_yyyy_mm_dd", "$limit": limit})
    return parse_cftc(raw)


CFTC_DATASETS = {
    "tff": "gpe5-46if",
    "disaggregated": "72hh-3qpy",
}

CFTC_ID_FIELDS = {
    "report_date_as_yyyy_mm_dd", "cftc_contract_market_code",
    "market_and_exchange_names", "contract_market_name", "commodity_name",
    "commodity_group_name", "commodity_subgroup_name",
}

def parse_cftc_report(raw: bytes, report_kind: str) -> pd.DataFrame:
    """Parse a CFTC Socrata report while preserving every numeric research field.

    This intentionally does not hard-code only long/short columns: CFTC also publishes
    changes, percent-of-open-interest, trader counts and concentration measures. Keeping
    numeric fields makes the cache forward-compatible with useful CFTC additions.
    """
    recs = json.loads(raw)
    rows = []
    for r in recs:
        row = {
            "date": pd.to_datetime(r.get("report_date_as_yyyy_mm_dd")).normalize(),
            "code": r.get("cftc_contract_market_code"),
            "market": r.get("market_and_exchange_names"),
            "contract_market": r.get("contract_market_name"),
            "commodity": r.get("commodity_name"),
            "commodity_group": r.get("commodity_group_name"),
            "commodity_subgroup": r.get("commodity_subgroup_name"),
            "report_kind": report_kind,
        }
        for k, v in r.items():
            if k in CFTC_ID_FIELDS:
                continue
            n = pd.to_numeric(v, errors="coerce")
            if pd.notna(n) or v in (None, ""):
                row[k] = n
        rows.append(row)
    out = pd.DataFrame(rows)
    if len(out):
        out["code"] = out["code"].astype("string")
        out = out.sort_values(["date", "code"]).set_index("date")
    return out

def fetch_cftc_report(report_kind: str, since=None, page_size=50000, max_pages=8) -> pd.DataFrame:
    """Fetch complete CFTC TFF/disaggregated history, then incremental revision windows.

    Initial TFF fits in one 50k page. Disaggregated history is paginated. Once cached,
    callers can pass since (normally latest cached report minus 35 days) so weekly
    refreshes re-read a revision window instead of downloading the entire dataset.
    """
    dataset = CFTC_DATASETS[report_kind]
    frames = []
    for page in range(max_pages):
        params = {
            "$order": "report_date_as_yyyy_mm_dd,cftc_contract_market_code",
            "$limit": page_size,
            "$offset": page * page_size,
        }
        if since is not None:
            ds = pd.Timestamp(since).strftime("%Y-%m-%d")
            params["$where"] = f"report_date_as_yyyy_mm_dd >= '{ds}T00:00:00.000'"
        raw = get_bytes(f"https://publicreporting.cftc.gov/resource/{dataset}.json", params)
        recs = json.loads(raw)
        if not recs:
            break
        frames.append(parse_cftc_report(json.dumps(recs).encode(), report_kind))
        if len(recs) < page_size:
            break
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()

def derive_cftc_position_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add generic net/gross/OI-normalized positioning, momentum and acceleration."""
    if df is None or df.empty:
        return df
    out = df.copy().sort_index()
    oi = pd.to_numeric(out.get("open_interest_all"), errors="coerce")
    long_cols = [c for c in out.columns if "positions_long" in c]
    for lc in long_cols:
        sc = lc.replace("positions_long", "positions_short")
        if sc not in out.columns:
            continue
        tag = lc.replace("_positions_long", "").replace("positions_long", "long")
        net_col = f"feature_{tag}_net"
        gross_col = f"feature_{tag}_gross"
        netoi_col = f"feature_{tag}_net_oi"
        longv = pd.to_numeric(out[lc], errors="coerce")
        shortv = pd.to_numeric(out[sc], errors="coerce")
        out[net_col] = longv - shortv
        out[gross_col] = longv + shortv
        out[netoi_col] = out[net_col] / oi.replace(0, np.nan)
        if "code" in out.columns:
            g = out.groupby("code", sort=False)[net_col]
            out[f"{net_col}_1w_change"] = g.diff()
            out[f"{net_col}_accel"] = g.diff().groupby(out["code"], sort=False).diff()
    return out


# ---------------- Coinbase ----------------
def parse_coinbase(raw: bytes) -> pd.DataFrame:
    arr = json.loads(raw)
    if isinstance(arr, dict):
        raise FeedError(f"coinbase error: {arr.get('message')}")
    if not arr:
        return pd.DataFrame(columns=BAR_COLS, index=pd.DatetimeIndex([], tz="UTC", name="ts_open"))
    a = np.asarray(arr, dtype=float)  # [time, low, high, open, close, volume], newest first
    df = pd.DataFrame({"open": a[:, 3], "high": a[:, 2], "low": a[:, 1], "close": a[:, 4], "volume": a[:, 5]},
                      index=pd.to_datetime(a[:, 0].astype(np.int64), unit="s", utc=True))
    return _intraday(df)


def fetch_coinbase(product="BTC-USD", granularity=300, start=None, end=None, max_pages=20) -> pd.DataFrame:
    end = pd.Timestamp.now(tz="UTC").floor("min") if end is None else pd.Timestamp(end)
    start = end - pd.Timedelta(days=2) if start is None else pd.Timestamp(start)
    step = pd.Timedelta(seconds=granularity * 300)
    frames, hi = [], end
    for _ in range(max_pages):
        lo = max(start, hi - step)
        raw = get_bytes(f"https://api.exchange.coinbase.com/products/{product}/candles",
                        {"granularity": granularity, "start": lo.isoformat(), "end": hi.isoformat()})
        frames.append(parse_coinbase(raw))
        if lo <= start:
            break
        hi = lo
    out = pd.concat(frames) if frames else parse_coinbase(b"[]")
    return _intraday(out)


# ---------------- Binance public bulk data ----------------
def parse_binance_zip(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        df = pd.read_csv(z.open(name), header=None)
    if not np.issubdtype(df[0].dtype, np.number):  # tolerate a header row
        df = df.iloc[1:].astype(float)
    t = df[0].astype(np.int64)
    unit = np.where(t > 10**14, "us", "ms")  # spot data from 2025-01-01 is in microseconds
    ts = pd.to_datetime(np.where(unit == "us", t // 1000, t), unit="ms", utc=True)
    out = pd.DataFrame({"open": df[1].astype(float).to_numpy(), "high": df[2].astype(float).to_numpy(),
                        "low": df[3].astype(float).to_numpy(), "close": df[4].astype(float).to_numpy(),
                        "volume": df[5].astype(float).to_numpy(),
                        "taker_buy_volume": df[9].astype(float).to_numpy()}, index=ts)
    return _intraday(out)


def fetch_binance_bulk(symbol="BTCUSDT", interval="5m", period="2026-08", market="spot") -> pd.DataFrame:
    kind = "monthly" if len(period) == 7 else "daily"
    url = (f"https://data.binance.vision/data/{market}/{kind}/klines/{symbol}/{interval}/"
           f"{symbol}-{interval}-{period}.zip")
    return parse_binance_zip(get_bytes(url, retries=1))
