"""Stitch the raw MNQ contract pulls into one continuous tape.

Feeding the engine a session-only tape put a 14-hour hole between every bar 30
and the next bar 1. Measured on the first build, the median overnight jump was
88 points against a median bar range of 45.5 -- roughly two full bars of
"movement" that never traded on the chart, 515 times over. The engine read
those as price action: sweeps that never happened, stops taken out by a gap.

So the tape is built whole. Every bar the contract printed goes in, and the
decision about when to trade is left where it belongs -- the strategy's own
session gate.

Bars are anchored to 18:00 ET, the CME session open, which is the grid
TradingView draws intraday futures bars on. Contracts are spliced at the
standard roll (the second Thursday of the expiry month), so exactly one
contract is live at any instant and the front month is always the liquid one.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TICK = 0.25
ANCHOR_MIN = 18 * 60          # 18:00 ET, the CME session open
ROOT = Path(__file__).resolve().parent.parent

# Front-month windows: [start, end) in ET calendar dates.
ROLLS = [
    ("MNQZ4", "2024-09-20", "2024-12-12"),
    ("MNQH5", "2024-12-12", "2025-03-13"),
    ("MNQM5", "2025-03-13", "2025-06-12"),
    ("MNQU5", "2025-06-12", "2025-09-11"),
    ("MNQZ5", "2025-09-11", "2025-12-11"),
    ("MNQH6", "2025-12-11", "2026-03-12"),
    ("MNQM6", "2026-03-12", "2026-06-11"),
    ("MNQU6", "2026-06-11", "2026-09-10"),
    ("MNQZ6", "2026-09-10", "2026-09-19"),
]

_DST_SPANS = (
    (date(2024, 3, 10), date(2024, 11, 2)),
    (date(2025, 3, 9), date(2025, 11, 1)),
    (date(2026, 3, 8), date(2026, 10, 31)),
)


def et_offset_seconds(utc_epoch: int) -> int:
    day = datetime.fromtimestamp(utc_epoch, timezone.utc).date()
    return -14400 if any(lo <= day <= hi for lo, hi in _DST_SPANS) else -18000


def load_spills(pattern: str) -> dict[str, list[tuple]]:
    """Read every spilled API response and bucket its rows by ticker."""
    by_ticker: dict[str, list[tuple]] = {}
    for path in sorted(glob.glob(pattern)):
        try:
            payload = json.load(open(path, encoding="utf-8"))["result"]
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            continue
        lines = payload.strip().split("\n")
        if not lines or not lines[0].startswith("ticker,window_start"):
            continue
        for row in lines[1:]:
            parts = row.split(",")
            if len(parts) < 9 or not parts[1].isdigit():
                continue
            by_ticker.setdefault(parts[0], []).append(
                (
                    int(parts[1]) // 1_000_000_000,
                    float(parts[3]), float(parts[4]),
                    float(parts[5]), float(parts[6]),
                    float(parts[8]),
                )
            )
    return by_ticker


def build(tf_minutes: int, out_path: Path) -> None:
    by_ticker = load_spills(
        "/root/.claude/projects/*/*/tool-results/mcp-Massive-call_api-*.txt"
    )
    if not by_ticker:
        raise SystemExit("no spill files found")

    # One contract live at a time: take each ticker only inside its roll window.
    rows: dict[int, list[float]] = {}
    step = tf_minutes * 60
    for ticker, start, end in ROLLS:
        lo = datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp()
        hi = datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp()
        for utc, o, h, l, c, v in by_ticker.get(ticker, []):
            et = utc + et_offset_seconds(utc)
            if not (lo <= et < hi):
                continue
            # Anchor the grid to 18:00 ET rather than to midnight, so bucket
            # boundaries land where the exchange session actually starts.
            bucket = ((et - ANCHOR_MIN * 60) // step) * step + ANCHOR_MIN * 60
            cell = rows.get(bucket)
            if cell is None:
                rows[bucket] = [o, h, l, c, v]
            else:
                cell[1] = max(cell[1], h)
                cell[2] = min(cell[2], l)
                cell[3] = c
                cell[4] += v

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts", "open", "high", "low", "close", "volume"])
        for bucket in sorted(rows):
            o, h, l, c, v = rows[bucket]
            # `bucket` is ET-as-epoch; undo the shift to get true UTC, then add
            # one bar so the stamp is the bar's CLOSE, which is what Bar.ts means.
            utc_open = bucket - et_offset_seconds(bucket)
            ts = datetime.fromtimestamp(utc_open + step, timezone.utc)
            writer.writerow([ts.isoformat(), o, h, l, c, int(v)])

    print(f"{len(rows)} bars @ {tf_minutes}m -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", type=int, default=20)
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args()
    out = Path(args.out) if args.out else ROOT / "data" / f"mnq_{args.tf}m_full.csv"
    build(args.tf, out)
