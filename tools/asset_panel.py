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

from datetime import datetime, timezone

from pathlib import Path

from icarus.data import Bar, load_csv

# What each market actually is, so a result reads as "holds in metals but not
# in credit" rather than as a list of tickers.
ASSET_CLASS = {
    "SPY": "equity index", "QQQ": "equity index", "IWM": "equity index",
    "DIA": "equity index", "NVDA": "single stock",
    "GLD": "metals", "SLV": "metals", "USO": "energy", "UNG": "energy",
    "XLE": "energy sector", "XLK": "tech sector", "XLF": "financials",
    "TLT": "rates", "IEF": "rates", "HYG": "credit", "LQD": "credit",
    "UUP": "fx", "FXE": "fx", "VXX": "volatility",
    "EEM": "emerging", "EFA": "intl developed", "I:NDX": "index cash",
}

def load_panel(min_bars: int = 2000) -> dict[str, list[Bar]]:
    """Every market in data/panel/, keyed by ticker.

    Reads committed CSVs rather than the vendor spill files. The spills live in
    a container scratch directory and vanish with it, and they carry no ticker
    unless the response happened to paginate -- five markets were silently
    dropped for exactly that reason. The export in data/panel/ is durable, in
    git, and its labels were verified against /v2/aggs/ticker/{T}/prev by
    comparing each file's last close to the previous-day close, rather than
    inferred from the order the calls were made in.

    Bars are already stamped at their CLOSE by the exporter, matching Bar.ts.
    """
    root = Path(__file__).resolve().parent.parent / "data" / "panel"
    panel: dict[str, list[Bar]] = {}
    if not root.is_dir():
        return panel
    for path in sorted(root.glob("*_5m.csv")):
        ticker = path.stem.rsplit("_5m", 1)[0].replace("_", ":")
        bars = load_csv(str(path))
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
