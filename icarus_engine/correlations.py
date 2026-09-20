"""Observed DXY associations from bounded, timestamped Yahoo snapshots.

The vendor's US Dollar Index is identified explicitly. These hourly snapshots
are not an ICE direct feed, future knowledge, or evidence of predictive lead.
"""
from __future__ import annotations

import json
import time
from urllib.parse import quote, urlencode

from .assets import REGISTRY
from .advisory import _iso
from .research import return_correlation


def _snapshot(sources, ticker):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(ticker, safe="") + "?" + urlencode(
        {"interval": "1h", "range": "1mo", "includePrePost": "false"})
    raw, _, received = sources._fetch(url, {"User-Agent": "Mozilla/5.0 IcarusResearch/1.0"})
    response = json.loads(raw)
    rows = (response.get("chart") or {}).get("result") or []
    if len(rows) != 1 or rows[0].get("meta", {}).get("symbol") != ticker:
        raise ValueError("correlation response instrument mismatch")
    row = rows[0]
    clock = row["meta"].get("regularMarketTime")
    if type(clock) is not int or clock <= 0:
        raise ValueError("correlation source lacks a feed clock")
    timestamps = row.get("timestamp") or []
    quotes = ((row.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quotes.get("close") or []
    if len(timestamps) != len(closes) or len(timestamps) > 2000:
        raise ValueError("invalid bounded hourly series")
    points = []
    for ts, close in zip(timestamps, closes):
        if type(ts) is not int or ts < 0:
            raise ValueError("invalid source timestamp")
        if ts % 3600 or ts + 3600 > min(clock, received // 10**9) or close is None:
            continue
        if isinstance(close, bool):
            raise ValueError("invalid close")
        price = float(close)
        # return_correlation validates finite positive prices before computation.
        points.append((ts + 3600, received // 10**9, price))
    if not points:
        raise ValueError("no completed hourly observations on the feed clock")
    return_correlation(points, points, as_of=received // 10**9)
    points.sort()
    record = sources._record("yahoo-dxy", "prices", ticker, ticker + ":hourly:" + str(points[-1][0]),
        url, received, {"ticker": ticker, "interval_seconds": 3600,
                       "closes": [[t, price] for t, _, price in points]},
        observed_at=_iso(points[-1][0]), report_family="vendor-hourly-snapshot")
    # Keep a revision's first known availability on repeated retrieval.
    return record, [(t, record["received_ns"] // 10**9, price) for t, _, price in points]


def collect_dxy(sources, options):
    sources._options(options, ("assets", "min_pairs"))
    assets = sources._assets(options)
    if any(asset not in REGISTRY for asset in assets):
        raise ValueError("unmapped asset for DXY comparison")
    minimum = options.get("min_pairs", 20)
    if type(minimum) is not int or not 2 <= minimum <= 1000:
        raise ValueError("min_pairs must be from 2 to 1000")
    dollar, right = _snapshot(sources, "DX-Y.NYB")
    records = []
    for asset in assets:
        instrument, left = _snapshot(sources, REGISTRY[asset].ticker)
        received = time.time_ns()  # This derived observation is computed now.
        result = return_correlation(left, right, as_of=received // 10**9, min_pairs=minimum)
        common = sorted({p[0] for p in left} & {p[0] for p in right})
        coefficient = result["correlation"]
        data = {"asset": asset, "asset_vendor_ticker": REGISTRY[asset].ticker,
                "benchmark_vendor_ticker": "DX-Y.NYB", "benchmark": "US Dollar Index (DXY), Yahoo vendor snapshot",
                "source_record_ids": [instrument["id"], dollar["id"]],
                "source_urls": [instrument["source_url"], dollar["source_url"]],
                "pairs": result["pairs"], "correlation": coefficient, "reason": result["reason"], "min_pairs": minimum,
                "window_start": common[0] if common else None, "window_end": common[-1] if common else None,
                "base_interval_seconds": 3600, "return_intervals": "identical observed start and end timestamps; gaps not filled",
                "direction": "unavailable" if coefficient is None else "positive" if coefficient > 0 else "negative" if coefficient < 0 else "zero",
                "caveats": ["Association does not establish prediction or causality.",
                            "Historical snapshots were first available to this system at receipt.",
                            "Yahoo futures are vendor continuous series; contract rolls can distort returns.",
                            "Spot BTC here is Yahoo BTC-USD, not the Coinbase execution stream.",
                            "Not a licensed ICE real-time or futures tick feed."]}
        record = sources._record("yahoo-dxy", "correlation", asset + ":DX-Y.NYB",
            asset + ":DXY:" + str(data["window_end"]), instrument["source_url"], received, data,
            assets=[asset], observed_at=_iso(common[-1]) if common else None,
            values={"pearson": coefficient} if coefficient is not None else {},
            units={"pearson": "unitless"} if coefficient is not None else {}, report_family="aligned-hourly-simple-returns")
        records.append(record)
    return records, {"benchmark": "DX-Y.NYB", "mapped_assets": assets,
                     "source": "Yahoo historical vendor snapshots", "real_time_licensed": False}
