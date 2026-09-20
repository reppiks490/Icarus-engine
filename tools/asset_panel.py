"""Every market on disk, as Bar lists, for cross-asset replication.

One asset and two spans gives four cells to be fooled by. A dozen markets
across five asset classes gives far more, and noise cannot hold a sign across
all of them. If liquidity sweeps reverse because of how resting stop orders
actually work, that is a claim about microstructure -- it should hold in gold
and crude and credit, not only in the Nasdaq. If it holds ONLY in the
instrument it was designed on, it was fitted to that instrument.

The panel is assembled from the spill files the vendor pulls leave on disk, so
adding a market costs one API call and no context.
"""

from __future__ import annotations

import glob
import json
import re
from datetime import datetime, timezone

from icarus.data import Bar

SPILL_GLOB = "/root/.claude/projects/*/*/tool-results/mcp-Massive-call_api-*.txt"

# What each market actually is, so a result can be read as "holds in metals but
# not in credit" rather than as a list of tickers.
ASSET_CLASS = {
    "SPY": "equity index", "QQQ": "equity index", "IWM": "equity index",
    "DIA": "equity index", "NVDA": "single stock",
    "GLD": "metals", "SLV": "metals", "USO": "energy", "UNG": "energy",
    "TLT": "rates", "IEF": "rates", "HYG": "credit",
    "UUP": "fx", "FXE": "fx", "I:NDX": "index cash",
}

_PATH_TICKER = re.compile(r'ticker/([A-Z:0-9]+)/range')


def _ticker_of(payload: str) -> str | None:
    """Recover the instrument from the pagination footer the response carries."""
    match = _PATH_TICKER.search(payload)
    return match.group(1) if match else None


def _interval_seconds(stamps_ms: list[int]) -> int:
    if len(stamps_ms) < 3:
        return 300
    gaps: dict[int, int] = {}
    for a, b in zip(stamps_ms, stamps_ms[1:]):
        gap = (b - a) // 1000
        if 0 < gap <= 86400:
            gaps[gap] = gaps.get(gap, 0) + 1
    return max(gaps.items(), key=lambda kv: kv[1])[0] if gaps else 300


def load_panel(min_bars: int = 2000) -> dict[str, list[Bar]]:
    """Every equity/ETF/index series on disk, keyed by ticker.

    Bars are stamped at their CLOSE, matching Bar.ts, because the vendor stamps
    the START and a downstream feature that joins on the start silently sees
    one interval into the future.
    """
    merged: dict[str, dict[int, tuple]] = {}

    for path in sorted(glob.glob(SPILL_GLOB)):
        try:
            payload = json.load(open(path, encoding="utf-8"))["result"]
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError, TypeError):
            continue
        lines = payload.strip().split("\n")
        header = lines[0].split(",")
        if header[:3] != ["v", "vw", "o"]:
            continue                                # futures or index shape
        ticker = _ticker_of(payload)
        if ticker is None:
            continue

        idx = {name: i for i, name in enumerate(header)}
        rows = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) < len(header):
                continue
            try:
                rows.append((
                    int(float(parts[idx["t"]])),
                    float(parts[idx["o"]]), float(parts[idx["h"]]),
                    float(parts[idx["l"]]), float(parts[idx["c"]]),
                    float(parts[idx["v"]]),
                ))
            except (ValueError, KeyError):
                continue
        if not rows:
            continue

        step = _interval_seconds([r[0] for r in rows])
        bucket = merged.setdefault(ticker, {})
        for t_ms, o, h, l, c, v in rows:
            bucket[t_ms // 1000 + step] = (o, h, l, c, v)

    panel: dict[str, list[Bar]] = {}
    for ticker, bucket in merged.items():
        if len(bucket) < min_bars:
            continue
        bars = []
        for ts in sorted(bucket):
            o, h, l, c, v = bucket[ts]
            # A vendor bar that violates OHLC ordering is bad data, not a
            # trade signal; drop it rather than let Bar refuse the whole load.
            if not (l <= o <= h and l <= c <= h):
                continue
            bars.append(Bar(ts=datetime.fromtimestamp(ts, timezone.utc),
                            open=o, high=h, low=l, close=c, volume=v))
        if len(bars) >= min_bars:
            panel[ticker] = bars
    return panel


def describe(panel: dict[str, list[Bar]]) -> str:
    lines = []
    for ticker, bars in sorted(panel.items()):
        span = (bars[-1].ts - bars[0].ts).days
        lines.append(f"  {ticker:<8s} {ASSET_CLASS.get(ticker,'?'):<14s} "
                     f"{len(bars):6d} bars  {bars[0].ts.date()} .. {bars[-1].ts.date()} "
                     f"({span}d)")
    return "\n".join(lines)
