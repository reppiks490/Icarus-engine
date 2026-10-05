# ChatGPT — 2026-10-04 — multi-provider external intelligence fabric
"""Collect high-value non-Databento market context with strict provider budgets.

Providers:
- FMP: event/calendar context that is available on the connected/free tier.
- EODHD: trade-by-trade US equity tape, sampled in high-information windows.
- Tiingo: long-history adjusted EOD, IEX intraday context, and tagged news.

Raw/licensed payloads stay under the Actions cache. Only compact derived manifests
are intended for git/UI. Secrets are read from environment and never persisted.

Research only: no execution or production-decision authority.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

UA = "icarus-external-data-fabric/1.0 (+https://github.com/reppiks490/Icarus-engine)"
NY = ZoneInfo("America/New_York")
DEFAULT_UNIVERSE = ("QQQ", "SPY", "NVDA", "AAPL", "MSFT", "AVGO", "AMZN", "META", "GOOGL", "TSLA")
EODHD_TICK_UNIVERSE = DEFAULT_UNIVERSE[:8]
TIINGO_INTRADAY_UNIVERSE = DEFAULT_UNIVERSE[:6]


class ProviderError(RuntimeError):
    pass


def _utc_now(now: Any = None) -> pd.Timestamp:
    x = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    return x.tz_localize("UTC") if x.tzinfo is None else x.tz_convert("UTC")


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_json_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    provider: str,
    timeout: int = 45,
    retries: int = 2,
) -> Any:
    """HTTP JSON GET whose raised errors never echo token-bearing URLs."""
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
    full = url + (("?" + query) if query else "")
    req = urllib.request.Request(full, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as ex:
            last = f"{provider} HTTP {ex.code}"
            if ex.code not in (429, 500, 502, 503, 504):
                raise ProviderError(last) from ex
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as ex:
            last = f"{provider} {type(ex).__name__}"
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise ProviderError(last or f"{provider} request failed")


def _write_gz_json(path: str | Path, obj: Any) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    compressed = gzip.compress(payload, compresslevel=6)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(compressed)
    os.replace(tmp, path)
    return {"sha256": _sha_bytes(compressed), "bytes": len(compressed)}


def _read_gz_json(path: str | Path, default: Any = None) -> Any:
    try:
        return json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8"))
    except Exception:
        return default


def _previous_weekday(now: pd.Timestamp) -> dt.date:
    local = now.tz_convert(NY)
    day = local.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def _manifest_base(provider: str, status: str, now: pd.Timestamp) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": status,
        "generated_at": now.isoformat(),
        "execution_authorized": False,
        "production_decision_authorized": False,
    }


def collect_fmp(cache_dir: str, now: pd.Timestamp, api_key: str | None) -> dict[str, Any]:
    """Use FMP free-tier calls only where they provide nonredundant event value."""
    if not (api_key or "").strip():
        return {**_manifest_base("fmp", "unconfigured", now), "credential_env": "FMP_API_KEY", "calls": 0}

    out = _manifest_base("fmp", "ok", now)
    out.update(credential_env="FMP_API_KEY", call_budget=20, calls=0, datasets={})
    base = "https://financialmodelingprep.com/stable"
    start = now.date() - dt.timedelta(days=1)
    end = now.date() + dt.timedelta(days=21)

    # Verified accessible on the user's current FMP free tier.
    try:
        data = _safe_json_get(
            f"{base}/earnings-calendar",
            params={"from": start.isoformat(), "to": end.isoformat(), "apikey": api_key},
            provider="FMP",
        )
        out["calls"] += 1
        cache_meta = _write_gz_json(Path(cache_dir) / "fmp" / "earnings_calendar.json.gz", data)
        events = data if isinstance(data, list) else []
        focus = [x for x in events if str(x.get("symbol", "")).upper() in DEFAULT_UNIVERSE]
        out["datasets"]["earnings_calendar"] = {
            "status": "ok",
            "rows": len(events),
            "focus_rows": len(focus),
            "focus": focus[:30],
            "cache": cache_meta,
        }
    except Exception as ex:
        out["datasets"]["earnings_calendar"] = {"status": "error", "error": str(ex)[:180]}
        out["status"] = "partial"

    # One low-cost capability probe for company profile. If the free tier denies it,
    # do not fan out further calls.
    try:
        prof = _safe_json_get(
            f"{base}/profile",
            params={"symbol": "QQQ", "apikey": api_key},
            provider="FMP",
        )
        out["calls"] += 1
        out["datasets"]["profile_probe"] = {"status": "ok", "rows": len(prof) if isinstance(prof, list) else 1}
    except Exception as ex:
        out["datasets"]["profile_probe"] = {"status": "plan_limited", "error": str(ex)[:180]}

    return out


def summarize_eodhd_ticks(payload: Any) -> dict[str, Any]:
    if payload == []:
        return {"ticks": 0}
    if not isinstance(payload, dict):
        raise ValueError("unexpected EODHD tick payload")
    prices = list(payload.get("price") or [])
    shares = list(payload.get("shares") or [])
    ts = list(payload.get("ts") or [])
    mkt = list(payload.get("mkt") or [])
    sale = list(payload.get("sl") or [])
    n = min(len(prices), len(shares), len(ts))
    if n <= 0:
        return {"ticks": 0}
    p = [float(x) for x in prices[:n]]
    s = [max(0, int(x)) for x in shares[:n]]
    total = sum(s)
    vwap = sum(px * sz for px, sz in zip(p, s)) / total if total else None
    venues = collections.Counter(str(x) for x in mkt[:n])
    off = sum(s[i] for i in range(min(n, len(mkt))) if str(mkt[i]) == "D")
    odd = sum(s[i] for i in range(min(n, len(sale))) if "I" in str(sale[i]))
    return {
        "ticks": n,
        "shares": total,
        "vwap": vwap,
        "price_first": p[0],
        "price_last": p[-1],
        "price_min": min(p),
        "price_max": max(p),
        "return_bps": ((p[-1] / p[0] - 1.0) * 10000.0) if p[0] else None,
        "off_exchange_share_pct": (100.0 * off / total) if total else None,
        "odd_lot_share_pct": (100.0 * odd / total) if total else None,
        "venues": dict(venues.most_common(12)),
        "first_ts_ms": int(ts[0]),
        "last_ts_ms": int(ts[n - 1]),
        "truncated_at_limit": n >= 10000,
    }


def collect_eodhd(cache_dir: str, now: pd.Timestamp, token: str | None) -> dict[str, Any]:
    if not (token or "").strip():
        return {**_manifest_base("eodhd", "unconfigured", now), "credential_env": "EODHD_API_TOKEN", "calls": 0}

    out = _manifest_base("eodhd", "ok", now)
    out.update(credential_env="EODHD_API_TOKEN", call_budget=18, calls=0, datasets={}, symbols=list(EODHD_TICK_UNIVERSE))
    day = _previous_weekday(now)
    windows = (("open", dt.time(9, 30), dt.time(10, 0)), ("close", dt.time(15, 30), dt.time(16, 0)))
    rows = []
    failures = 0

    for symbol in EODHD_TICK_UNIVERSE:
        for role, t0, t1 in windows:
            if out["calls"] >= out["call_budget"]:
                break
            start_local = dt.datetime.combine(day, t0, NY)
            end_local = dt.datetime.combine(day, t1, NY)
            params = {
                "s": symbol,
                "from": int(start_local.timestamp()),
                "to": int(end_local.timestamp()),
                "limit": 10000,
                "api_token": token,
                "fmt": "json",
            }
            try:
                payload = _safe_json_get("https://eodhd.com/api/ticks/", params=params, provider="EODHD")
                out["calls"] += 1
                raw_meta = _write_gz_json(Path(cache_dir) / "eodhd" / day.isoformat() / f"{symbol}_{role}.json.gz", payload)
                summary = summarize_eodhd_ticks(payload)
                rows.append({"symbol": symbol, "window": role, "date": day.isoformat(), **summary, "cache": raw_meta})
            except Exception as ex:
                out["calls"] += 1
                failures += 1
                rows.append({"symbol": symbol, "window": role, "date": day.isoformat(), "status": "error", "error": str(ex)[:160]})
    out["datasets"]["tick_windows"] = {
        "status": "ok" if failures == 0 else ("partial" if failures < len(rows) else "error"),
        "date": day.isoformat(),
        "rows": rows,
        "failed_requests": failures,
        "strategy": "09:30-10:00 and 15:30-16:00 America/New_York; max 10,000 ticks/window",
    }
    if failures:
        out["status"] = "partial"
    return out


def summarize_tiingo_eod(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        return {"rows": 0}
    frame = pd.DataFrame(rows)
    if "date" not in frame:
        return {"rows": len(frame)}
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values("date")
    close_col = "adjClose" if "adjClose" in frame else ("close" if "close" in frame else None)
    out = {"rows": int(len(frame)), "first": frame["date"].iloc[0].isoformat(), "last": frame["date"].iloc[-1].isoformat()}
    if close_col:
        c = pd.to_numeric(frame[close_col], errors="coerce").dropna()
        if len(c) >= 2:
            out["total_return_pct"] = float((c.iloc[-1] / c.iloc[0] - 1.0) * 100.0)
            ret = c.pct_change().dropna()
            if len(ret) >= 20:
                out["realized_vol_20d_pct"] = float(ret.tail(20).std(ddof=1) * math.sqrt(252) * 100.0)
    if "volume" in frame:
        v = pd.to_numeric(frame["volume"], errors="coerce").dropna()
        if len(v):
            out["avg_volume_20d"] = float(v.tail(20).mean())
    return out


def summarize_tiingo_intraday(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        return {"bars": 0}
    frame = pd.DataFrame(rows)
    out = {"bars": int(len(frame))}
    if "date" in frame:
        d = pd.to_datetime(frame["date"], utc=True, errors="coerce").dropna()
        if len(d):
            out.update(first=d.iloc[0].isoformat(), last=d.iloc[-1].isoformat())
    if {"high", "low", "close"} <= set(frame.columns):
        high = pd.to_numeric(frame["high"], errors="coerce")
        low = pd.to_numeric(frame["low"], errors="coerce")
        close = pd.to_numeric(frame["close"], errors="coerce")
        good = pd.concat([high, low, close], axis=1).dropna()
        if len(good):
            out["range_pct"] = float((good.iloc[:, 0].max() - good.iloc[:, 1].min()) / max(abs(good.iloc[:, 2].iloc[-1]), 1e-12) * 100.0)
    return out


def collect_tiingo(cache_dir: str, now: pd.Timestamp, token: str | None) -> dict[str, Any]:
    if not (token or "").strip():
        return {**_manifest_base("tiingo", "unconfigured", now), "credential_env": "TIINGO_API_TOKEN", "calls": 0}

    out = _manifest_base("tiingo", "ok", now)
    out.update(credential_env="TIINGO_API_TOKEN", call_budget=40, calls=0, datasets={})
    headers = {"Authorization": f"Token {token}"}
    eod = {}
    failures = 0

    for symbol in DEFAULT_UNIVERSE:
        path = Path(cache_dir) / "tiingo" / "eod" / f"{symbol}.json.gz"
        prior = _read_gz_json(path, [])
        if isinstance(prior, list) and prior:
            dates = [pd.Timestamp(x.get("date")) for x in prior if x.get("date")]
            start = (max(dates).date() + dt.timedelta(days=1)).isoformat() if dates else "2008-01-01"
        else:
            start = "2008-01-01"
        try:
            merged = prior if isinstance(prior, list) else []
            if pd.Timestamp(start).date() > now.date():
                fresh = []
            else:
                fresh = _safe_json_get(
                    f"https://api.tiingo.com/tiingo/daily/{symbol}/prices",
                    params={"startDate": start, "endDate": now.date().isoformat()},
                    headers=headers,
                    provider="Tiingo",
                )
                out["calls"] += 1
            if isinstance(fresh, list) and fresh:
                by_date = {str(x.get("date"))[:10]: x for x in merged if x.get("date")}
                for x in fresh:
                    if x.get("date"):
                        by_date[str(x["date"])[:10]] = x
                merged = [by_date[k] for k in sorted(by_date)]
            raw_meta = _write_gz_json(path, merged)
            eod[symbol] = {**summarize_tiingo_eod(merged), "cache": raw_meta}
        except Exception as ex:
            out["calls"] += 1
            failures += 1
            eod[symbol] = {"status": "error", "error": str(ex)[:160]}
    out["datasets"]["eod"] = {"status": "ok" if failures == 0 else "partial", "symbols": eod}

    intraday = {}
    start = (now - pd.Timedelta(days=7)).date().isoformat()
    for symbol in TIINGO_INTRADAY_UNIVERSE:
        try:
            rows = _safe_json_get(
                f"https://api.tiingo.com/iex/{symbol}/prices",
                params={"startDate": start, "resampleFreq": "5min", "columns": "open,high,low,close,volume"},
                headers=headers,
                provider="Tiingo",
            )
            out["calls"] += 1
            raw_meta = _write_gz_json(Path(cache_dir) / "tiingo" / "iex" / f"{symbol}.json.gz", rows)
            intraday[symbol] = {**summarize_tiingo_intraday(rows), "cache": raw_meta}
        except Exception as ex:
            out["calls"] += 1
            intraday[symbol] = {"status": "error", "error": str(ex)[:160]}
            failures += 1
    out["datasets"]["iex_5m"] = {"status": "ok" if all("error" not in x for x in intraday.values()) else "partial", "symbols": intraday}

    try:
        news = _safe_json_get(
            "https://api.tiingo.com/tiingo/news",
            params={"tickers": ",".join(DEFAULT_UNIVERSE), "limit": 100},
            headers=headers,
            provider="Tiingo",
        )
        out["calls"] += 1
        raw_meta = _write_gz_json(Path(cache_dir) / "tiingo" / "news" / "latest.json.gz", news)
        out["datasets"]["news"] = {
            "status": "ok",
            "articles": len(news) if isinstance(news, list) else 0,
            "cache": raw_meta,
            "recent": [
                {k: x.get(k) for k in ("publishedDate", "crawlDate", "title", "source", "tickers", "tags")}
                for x in (news[:25] if isinstance(news, list) else [])
            ],
        }
    except Exception as ex:
        out["calls"] += 1
        failures += 1
        out["datasets"]["news"] = {"status": "error", "error": str(ex)[:160]}

    if failures:
        out["status"] = "partial"
    return out


def build_cross_provider_summary(fmp: dict[str, Any], eodhd: dict[str, Any], tiingo: dict[str, Any]) -> dict[str, Any]:
    tick_rows = (((eodhd.get("datasets") or {}).get("tick_windows") or {}).get("rows") or [])
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in tick_rows:
        if row.get("status") == "error":
            continue
        sym = row.get("symbol")
        if not sym:
            continue
        rec = by_symbol.setdefault(sym, {"windows": 0, "shares": 0, "ticks": 0, "off_exchange_weighted": 0.0})
        rec["windows"] += 1
        rec["shares"] += int(row.get("shares") or 0)
        rec["ticks"] += int(row.get("ticks") or 0)
        if row.get("off_exchange_share_pct") is not None:
            rec["off_exchange_weighted"] += float(row["off_exchange_share_pct"]) * max(int(row.get("shares") or 0), 1)
    for rec in by_symbol.values():
        rec["off_exchange_share_pct"] = (
            rec.pop("off_exchange_weighted") / rec["shares"] if rec["shares"] else None
        )

    upcoming = (((fmp.get("datasets") or {}).get("earnings_calendar") or {}).get("focus") or [])
    return {
        "schema": "icarus.external_data.summary/1",
        "universe": list(DEFAULT_UNIVERSE),
        "equity_tick_pressure": by_symbol,
        "upcoming_focus_earnings": upcoming,
        "provider_status": {x["provider"]: x.get("status") for x in (fmp, eodhd, tiingo)},
        "research_only": True,
        "execution_authorized": False,
    }


def run(cache_dir: str, out_path: str, now: Any = None) -> dict[str, Any]:
    now = _utc_now(now)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    fmp = collect_fmp(cache_dir, now, os.environ.get("FMP_API_KEY"))
    eodhd = collect_eodhd(cache_dir, now, os.environ.get("EODHD_API_TOKEN"))
    tiingo = collect_tiingo(cache_dir, now, os.environ.get("TIINGO_API_TOKEN"))
    result = {
        "schema": "icarus.external_data.fabric/1",
        "generated_at": now.isoformat(),
        "providers": {"fmp": fmp, "eodhd": eodhd, "tiingo": tiingo},
        "summary": build_cross_provider_summary(fmp, eodhd, tiingo),
        "raw_storage": "Actions/local cache only; raw vendor payloads are not committed",
        "execution_authorized": False,
        "production_decision_authorized": False,
    }
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=1, sort_keys=True, default=str) + "\n"
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, p)
    print(json.dumps({
        "providers": result["summary"]["provider_status"],
        "fmp_calls": fmp.get("calls", 0),
        "eodhd_calls": eodhd.get("calls", 0),
        "tiingo_calls": tiingo.get("calls", 0),
    }))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=".external_data_cache")
    ap.add_argument("--out", default="automation_intelligence/cl_lab/external_data_fabric.json")
    ap.add_argument("--now", default=None)
    a = ap.parse_args(argv)
    run(a.cache, a.out, a.now)


if __name__ == "__main__":
    main()
