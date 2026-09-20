"""Market-data feeds (stdlib only, no API keys).

  coinbase  Coinbase Exchange public REST — the same prints TradingView shows for
            COINBASE:BTCUSD, so a parity check against a TradingView chart of the
            same symbol compares like with like. History is paged (300 candles per
            call) so warm-up depth is not limited.
  kraken    fallback for live 1-minute candles / last price.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from ..pine.timeframe import Bar

UA = {"User-Agent": "icarus-engine/0.1 (+local paper trading)"}


def http_json(url: str, timeout: float = 10.0, retries: int = 3):
    last: Optional[Exception] = None
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as ex:            # network hiccup / 429 → back off and retry
            last = ex
            time.sleep(0.6 * (k + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def normalize_symbol(sym: str) -> str:
    """'btc' / 'BTCUSD' / 'BTC-USD' / 'COINBASE:BTCUSD' / 'BTC/USD' -> 'BTC-USD'."""
    s = sym.strip().upper()
    if ":" in s:
        s = s.split(":", 1)[1]
    s = s.replace("/", "-").replace("_", "-")
    for q in ("USDT", "USDC", "USD"):
        if s.endswith("-" + q):
            return s[: -len(q) - 1] + "-USD"
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)] + "-USD"
    return s + "-USD"


class Coinbase:
    BASE = "https://api.exchange.coinbase.com"
    GRANULARITIES = (60, 300, 900, 3600, 21600, 86400)

    def product(self, product: str) -> Dict:
        return http_json(f"{self.BASE}/products/{product}")

    def mintick(self, product: str) -> float:
        try:
            return float(self.product(product).get("quote_increment") or 0.01)
        except Exception:
            return 0.01

    def ticker(self, product: str) -> Optional[float]:
        try:
            return float(http_json(f"{self.BASE}/products/{product}/ticker", timeout=6, retries=2)["price"])
        except Exception:
            return None

    def candles(self, product: str, granularity: int, start_ts: int, end_ts: int) -> List[Bar]:
        """All candles with open time in [start_ts, end_ts), ascending. Empty minutes are absent."""
        assert granularity in self.GRANULARITIES, granularity
        out: Dict[int, Bar] = {}
        span = granularity * 300                         # 300 candles per request
        t0 = int(start_ts) - (int(start_ts) % granularity)
        while t0 < end_ts:
            t1 = min(t0 + span, int(end_ts))
            q = urllib.parse.urlencode({
                "granularity": granularity,
                "start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
                "end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t1)),
            })
            rows = http_json(f"{self.BASE}/products/{product}/candles?{q}")
            for r in rows:                                  # [time, low, high, open, close, volume]
                ts = int(r[0])
                if start_ts <= ts < end_ts:
                    out[ts] = Bar(ts, float(r[3]), float(r[2]), float(r[1]), float(r[4]), float(r[5]))
            t0 = t1
            time.sleep(0.12)                                # public rate limit: 10 req/s
        return [out[k] for k in sorted(out)]

    def recent(self, product: str, granularity: int = 60) -> List[Bar]:
        rows = http_json(f"{self.BASE}/products/{product}/candles?granularity={granularity}", timeout=6, retries=2)
        bars = [Bar(int(r[0]), float(r[3]), float(r[2]), float(r[1]), float(r[4]), float(r[5])) for r in rows]
        bars.sort(key=lambda b: b.ts)
        return bars


class Kraken:
    BASE = "https://api.kraken.com/0/public"
    ALIAS = {"BTC": "XBT", "DOGE": "XDG"}

    def pair(self, product: str) -> str:
        base = product.split("-")[0]
        return self.ALIAS.get(base, base) + "USD"

    def recent(self, product: str, interval_min: int = 1) -> List[Bar]:
        data = http_json(f"{self.BASE}/OHLC?pair={self.pair(product)}&interval={interval_min}", timeout=8, retries=2)
        res = data.get("result", {})
        key = next((k for k in res.keys() if k != "last"), None)
        if not key:
            return []
        bars = [Bar(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6])) for r in res[key]]
        bars.sort(key=lambda b: b.ts)
        return bars

    def ticker(self, product: str) -> Optional[float]:
        try:
            data = http_json(f"{self.BASE}/Ticker?pair={self.pair(product)}", timeout=6, retries=2)
            res = data.get("result", {})
            key = next(iter(res.keys()))
            return float(res[key]["c"][0])
        except Exception:
            return None
