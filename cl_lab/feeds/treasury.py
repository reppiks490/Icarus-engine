"""Keyless U.S. Treasury fiscal/auction data for ICARUS macro research.

Raw rows stay in the CL Actions cache.  The module keeps release/record dates explicit
and never maps future/upcoming auction rows into historical feature frames.
"""
from __future__ import annotations

import json
import pandas as pd

from .http import FeedError, get_bytes

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

DATASETS = {
    "operating_cash": {
        "endpoint": "/v1/accounting/dts/operating_cash_balance",
        "date_field": "record_date",
        "date_fields": ("record_date",),
        "identity": ("record_date", "account_type", "src_line_nbr"),
        "revision_days": 35,
    },
    "auctions": {
        "endpoint": "/v1/accounting/od/auctions_query",
        "date_field": "auction_date",
        "date_fields": ("record_date", "announcement_date", "auction_date", "issue_date", "maturity_date"),
        "identity": ("auction_date", "cusip"),
        "revision_days": 370,
    },
    "debt_to_penny": {
        "endpoint": "/v2/accounting/od/debt_to_penny",
        "date_field": "record_date",
        "date_fields": ("record_date",),
        "identity": ("record_date",),
        "revision_days": 35,
    },
}

TEXT_HINTS = {
    "account_type", "cusip", "security_type", "security_term", "original_security_term",
    "security_term_week_year", "security_term_day_month", "maturing_security_type",
    "record_fiscal_year", "record_fiscal_quarter", "record_calendar_year",
    "record_calendar_quarter", "record_calendar_month",
}

def parse_records(records, dataset: str) -> pd.DataFrame:
    spec = DATASETS[dataset]
    date_fields = set(spec["date_fields"])
    rows = []
    for rec in records:
        row = {"dataset": dataset}
        for key, value in rec.items():
            if key in date_fields:
                row[key] = pd.to_datetime(value, errors="coerce")
            elif key in TEXT_HINTS:
                row[key] = value
            else:
                numeric = pd.to_numeric(value, errors="coerce")
                row[key] = numeric if pd.notna(numeric) else value
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    date_field = spec["date_field"]
    if date_field not in out or out[date_field].isna().all():
        raise FeedError(f"Treasury {dataset}: no usable {date_field}")
    out = out.sort_values(date_field).set_index(date_field)
    out.index.name = "date"
    return out

def fetch_dataset(dataset: str, since=None, page_size=10000, max_pages=50) -> pd.DataFrame:
    spec = DATASETS[dataset]
    frames = []
    for page in range(1, max_pages + 1):
        params = {
            "sort": spec["date_field"],
            "page[size]": page_size,
            "page[number]": page,
        }
        if since is not None:
            ds = pd.Timestamp(since).strftime("%Y-%m-%d")
            params["filter"] = f"{spec['date_field']}:gte:{ds}"
        raw = get_bytes(BASE + spec["endpoint"], params)
        payload = json.loads(raw)
        records = payload.get("data") or []
        if not records:
            break
        frames.append(parse_records(records, dataset))
        meta = payload.get("meta") or {}
        total_pages = meta.get("total-pages") or meta.get("total_pages")
        if total_pages is not None:
            try:
                if page >= int(total_pages):
                    break
            except (TypeError, ValueError):
                pass
        if len(records) < page_size:
            break
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()

def _dedupe(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    spec = DATASETS[dataset]
    flat = df.reset_index()
    keys = []
    for key in spec["identity"]:
        if key == spec["date_field"] and "date" in flat.columns:
            keys.append("date")
        elif key in flat.columns:
            keys.append(key)
    if not keys:
        keys = ["date"]
    flat = flat.drop_duplicates(keys, keep="last")
    return flat.set_index("date").sort_index()

def derive_features(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy().sort_index()
    if dataset == "operating_cash" and "close_today_bal" in out:
        grp = out["account_type"] if "account_type" in out else pd.Series("all", index=out.index)
        close = pd.to_numeric(out["close_today_bal"], errors="coerce")
        out["feature_cash_1d_change"] = close.groupby(grp).diff()
        out["feature_cash_5d_change"] = close.groupby(grp).diff(5)
    elif dataset == "auctions" and "bid_to_cover_ratio" in out:
        btc = pd.to_numeric(out["bid_to_cover_ratio"], errors="coerce")
        grp = out["security_term"] if "security_term" in out else pd.Series("all", index=out.index)
        mean = btc.groupby(grp).transform(lambda s: s.rolling(20, min_periods=5).mean())
        std = btc.groupby(grp).transform(lambda s: s.rolling(20, min_periods=5).std())
        out["feature_bid_to_cover_z20"] = (btc - mean) / std.replace(0, pd.NA)
    elif dataset == "debt_to_penny":
        for col in ("debt_held_public_amt", "tot_pub_debt_out_amt"):
            if col in out:
                v = pd.to_numeric(out[col], errors="coerce")
                out[f"feature_{col}_1d_change"] = v.diff()
    return out

def refresh(old: pd.DataFrame, dataset: str) -> tuple[pd.DataFrame, str]:
    spec = DATASETS[dataset]
    since = None
    if old is not None and not old.empty:
        since = old.index.max() - pd.Timedelta(days=int(spec["revision_days"]))
    fresh = fetch_dataset(dataset, since=since)
    if fresh.empty and (old is None or old.empty):
        raise FeedError(f"Treasury {dataset}: zero rows")
    combined = pd.concat([old, fresh]) if old is not None and not old.empty else fresh
    combined = _dedupe(combined, dataset)
    combined = derive_features(combined, dataset)
    note = f"dataset={dataset};revision_window_start={since.date() if since is not None else 'full-history'}"
    return combined, note
