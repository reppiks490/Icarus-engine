"""Yahoo Finance chart API — keyless bars for CME futures (NQ=F, ES=F, YM=F, GC=F, SI=F, PL=F, PA=F, BTC=F).

Limits of the public endpoint (documented, not worked around):
  * 1-minute bars only for the last 30 days, 7 days per request; 5m/15m/30m for
    60 days; 1h for 730 days; 1d unlimited.
  * Minutes with no trades are returned as nulls (skipped) or as flat zero-volume rows (skipped).
  * CME data on Yahoo is DELAYED by 10 minutes (measured 600-605 s on NQ/ES/GC/BTC futures;
    `meta.exchangeDataDelayedBy` is absent for futures). `meta.regularMarketTime` is the feed's
    own clock; the runtime closes bars on that clock, never on the wall clock.
  * Every 1-minute response ends with a "quote row" (timestamp = regularMarketTime, not minute
    aligned, O=H=L=C=last price, volume 0) and, before it, the feed's still-forming minute.
    `_bars` drops the quote row; `recent_ex` reports `feed_time` so callers can drop the forming
    minute (closed <=> ts + 60 <= feed_time).
  * `NQ=F` is Yahoo's front contract by EXPIRY; TradingView's `NQ1!` rolls by volume ~the Tuesday
    of expiry week - see `contracts.py` for the roll rule and contract-specific tickers.
A real-time feed (Databento, a broker API, TradingView alerts through icarus_bridge) plugs in
through the same `candles/recent_ex/ticker` interface.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from ..pine.timeframe import Bar

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) icarus-engine/0.3", "Accept": "application/json"}
_INTERVAL = {60: "1m", 120: "2m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h", 86400: "1d"}
_MAX_SPAN = {60: 7 * 86400, 120: 60 * 86400, 300: 60 * 86400, 900: 60 * 86400, 1800: 60 * 86400, 3600: 730 * 86400, 86400: 3650 * 86400}
_MAX_BACK = {60: 29 * 86400 + 3600, 120: 59 * 86400 + 3600, 300: 59 * 86400 + 3600, 900: 59 * 86400 + 3600, 1800: 59 * 86400 + 3600, 3600: 729 * 86400, 86400: 40 * 365 * 86400}   # Yahoo rejects (422) requests at the exact edge
_MAX_BYTES = 32 << 20


class Yahoo:
    BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
    GRANULARITIES = (60, 120, 300, 900, 1800, 3600, 86400)

    def __init__(self, min_interval: float = 0.35):
        self._last = 0.0
        self.min_interval = min_interval
        self._meta: Dict[str, dict] = {}
        self.requests = 0

    def _get(self, url: str, timeout: float = 15.0, retries: int = 3):
        last = None
        for k in range(retries):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                    self._last = time.time()
                    self.requests += 1
                    if not r.geturl().startswith("https://"):
                        raise RuntimeError(f"Yahoo redirected to a non-https URL: {r.geturl()}")
                    raw = r.read(_MAX_BYTES + 1)
                    if len(raw) > _MAX_BYTES:
                        raise RuntimeError("Yahoo response too large")
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as ex:              # 429 / 5xx → honour Retry-After, then back off
                last = ex
                self._last = time.time()
                ra = ex.headers.get("Retry-After") if ex.headers else None
                try:
                    time.sleep(min(float(ra), 30.0) if ra else 1.5 * (k + 1))
                except ValueError:
                    time.sleep(1.5 * (k + 1))
            except Exception as ex:                           # transient network error → back off
                last = ex
                self._last = time.time()
                time.sleep(1.5 * (k + 1))
        raise RuntimeError(f"Yahoo GET failed: {last}")

    def _chart(self, symbol: str, interval: str, **params) -> dict:
        q = dict(interval=interval, includePrePost="false", events="")
        q.update({k: v for k, v in params.items() if v is not None})
        d = self._get(f"{self.BASE}{urllib.parse.quote(symbol)}?{urllib.parse.urlencode(q)}")
        res = (d.get("chart") or {}).get("result") or []
        if not res:
            err = (d.get("chart") or {}).get("error")
            raise RuntimeError(f"Yahoo: no data for {symbol} {interval}: {err}")
        self._meta[symbol] = res[0].get("meta") or {}
        return res[0]

    @staticmethod
    def _bars(res: dict, granularity: int = 60) -> List[Bar]:
        """Rows with a complete OHLC, aligned to the granularity (drops Yahoo's non-aligned quote row) and,
        for intraday granularities, carrying at least one trade (drops flat zero-volume placeholder rows)."""
        ts = res.get("timestamp") or []
        q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        o, h, l, c, v = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
        intraday = granularity < 86400
        out = []
        for i, t in enumerate(ts):
            if i >= len(c) or c[i] is None or o[i] is None or h[i] is None or l[i] is None:
                continue
            t = int(t)
            if intraday and t % granularity != 0:
                continue
            vol = float(v[i] or 0.0) if i < len(v) else 0.0
            if intraday and vol == 0.0 and o[i] == h[i] == l[i] == c[i]:
                continue
            out.append(Bar(t, float(o[i]), float(h[i]), float(l[i]), float(c[i]), vol))
        out.sort(key=lambda b: b.ts)
        return out

    # ── Feed interface ──
    def mintick(self, symbol: str) -> float:
        """Yahoo's chart API does not carry tick sizes; the asset registry does (assets.REGISTRY)."""
        from ..assets import REGISTRY
        for spec in REGISTRY.values():
            if spec.ticker == symbol:
                return spec.mintick
        raise ValueError(f"tick size for {symbol} unknown - add it to assets.REGISTRY")

    def meta(self, symbol: str) -> dict:
        if symbol not in self._meta:
            try:
                self._chart(symbol, "1d", range="5d")
            except Exception:
                return {}
        return self._meta.get(symbol, {})

    def ticker(self, symbol: str) -> Optional[float]:
        try:
            res = self._chart(symbol, "1m", range="1d")
            m = res.get("meta") or {}
            if m.get("regularMarketPrice") is not None:
                return float(m["regularMarketPrice"])
            bars = self._bars(res)
            return bars[-1].c if bars else None
        except Exception:
            m = self._meta.get(symbol) or {}
            return float(m["regularMarketPrice"]) if m.get("regularMarketPrice") else None

    def candles(self, symbol: str, granularity: int, start_ts: int, end_ts: int) -> List[Bar]:
        """Bars with open time in [start_ts, end_ts), ascending; paged per Yahoo's per-request limits."""
        iv = _INTERVAL[granularity]
        now = int(time.time())
        start_ts = max(int(start_ts), now - _MAX_BACK[granularity])
        out: Dict[int, Bar] = {}
        t0 = start_ts
        while t0 < end_ts:
            t1 = min(t0 + _MAX_SPAN[granularity], int(end_ts))
            res = self._chart(symbol, iv, period1=t0, period2=t1)
            for b in self._bars(res, granularity):
                if start_ts <= b.ts < end_ts:
                    out[b.ts] = b
            t0 = t1
        return [out[k] for k in sorted(out)]

    def recent_ex(self, symbol: str, granularity: int = 60, since_ts: Optional[int] = None) -> Tuple[List[Bar], int, Optional[float]]:
        """(bars, feed_time, last_price): the latest bars (from `since_ts` - 15 min when given, else 5 days),
        the feed's clock (`regularMarketTime`, epoch) and its last price. A bar is CLOSED on the feed's side
        only when `bar.ts + granularity <= feed_time`; the caller decides."""
        iv = _INTERVAL[granularity]
        now = int(time.time())
        if since_ts:
            res = self._chart(symbol, iv, period1=max(int(since_ts) - 900, now - _MAX_BACK[granularity]), period2=now + 120)
        else:
            res = self._chart(symbol, iv, range="5d" if granularity <= 300 else "1mo")
        m = res.get("meta") or {}
        feed_time = int(m.get("regularMarketTime") or 0)
        px = float(m["regularMarketPrice"]) if m.get("regularMarketPrice") is not None else None
        return self._bars(res, granularity), feed_time, px

    def recent(self, symbol: str, granularity: int = 60) -> List[Bar]:
        return self.recent_ex(symbol, granularity)[0]

    def daily_volume(self, symbol: str, days: int = 5) -> List[Tuple[int, float, float]]:
        """(ts, close, volume) of the last completed daily bars - used by the contract-roll rule."""
        res = self._chart(symbol, "1d", range=f"{max(days, 2)}d")
        return [(b.ts, b.c, b.v) for b in self._bars(res, 86400)]
