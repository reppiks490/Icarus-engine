#!/usr/bin/env python3
"""Credential-free Yahoo connectivity probe for the expanded futures registry.

This is evidence tooling, not an execution gate. A provider/network failure is
encoded in JSON instead of being mistaken for a missing contract identity.
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Iterable

from icarus_engine.assets import REGISTRY
from icarus_engine.feeds.yahoo import Yahoo


PROBE_SYMBOLS = (
    "MNQ", "MES", "MYM", "MGC", "SIL",
    "RTY", "M2K",
    "CL", "MCL",
    "NG", "MNG",
    "HG", "MHG",
    "6E", "M6E",
    "6J", "MJY",
    "6B", "M6B",
    "6A", "M6A",
    "ZN", "ZB",
)


def probe_symbol(symbol: str, feed: Yahoo) -> dict:
    spec = REGISTRY[symbol]
    started = time.monotonic()
    row = {
        "symbol": symbol,
        "ticker": spec.ticker,
        "feed": spec.feed,
        "feed_mode": spec.feed_mode,
        "kind": spec.kind,
        "exchange": spec.exchange,
        "asset_class": spec.asset_class,
        "micro_of": spec.micro_of,
        "status": "unknown",
        "bar_count": 0,
        "last_bar_ts": None,
        "last_close": None,
        "currency": None,
        "exchange_name": None,
        "elapsed_ms": None,
        "error_class": None,
        "error": None,
    }
    try:
        bars = feed.daily_volume(spec.ticker, days=5)
        meta = feed.meta(spec.ticker)
        row["bar_count"] = len(bars)
        if bars:
            row["last_bar_ts"] = int(bars[-1][0])
            row["last_close"] = float(bars[-1][1])
        row["currency"] = meta.get("currency")
        row["exchange_name"] = meta.get("exchangeName") or meta.get("fullExchangeName")
        row["status"] = "connected_public_delayed" if bars else "reachable_no_bars"
    except Exception as exc:  # provider/network evidence is data, not a crash
        row["status"] = "provider_blocked_or_unavailable"
        row["error_class"] = type(exc).__name__
        row["error"] = str(exc)[:240]
    row["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
    return row


def run(symbols: Iterable[str]) -> dict:
    feed = Yahoo(min_interval=0.10)
    rows = [probe_symbol(symbol, feed) for symbol in symbols]
    connected = sum(row["status"] == "connected_public_delayed" for row in rows)
    return {
        "schema_version": "icarus-futures-universe-probe-v1",
        "source": "Yahoo public chart endpoint",
        "authority": "research_delayed_only",
        "live_execution_authorized": False,
        "requested": len(rows),
        "connected": connected,
        "not_connected": len(rows) - connected,
        "provider_requests": feed.requests,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe delayed public futures bars without credentials")
    parser.add_argument("--symbol", action="append", choices=PROBE_SYMBOLS, help="probe only this symbol; repeatable")
    parser.add_argument("--require-all", action="store_true", help="return nonzero if any selected symbol lacks bars")
    args = parser.parse_args()
    symbols = tuple(dict.fromkeys(args.symbol or PROBE_SYMBOLS))
    report = run(symbols)
    print(json.dumps(report, sort_keys=True, indent=2))
    return 1 if args.require_all and report["not_connected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
