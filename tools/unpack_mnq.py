"""Decode the packed MNQ tape into a CSV the engine's ``load_csv`` can read.

The vendor feed is pulled through a remote SQL workspace, so every byte that
reaches this process costs context. The packed form exists to make that cheap:
one line per session, prices as integer ticks delta-coded against the previous
close, time implied by position on a fixed 20-minute grid.

Line format
-----------
``YYYY-MM-DD,<base_ticks>,<n_bars>,<bar> <bar> ...``  with each bar ``a,b,c,d,v``

    a = (open  - prev_close) / TICK      prev_close is the previous bar's close,
                                         or ``base_ticks`` for the first bar
    b = (high  - open)       / TICK      >= 0 by construction
    c = (open  - low)        / TICK      >= 0 by construction
    d = (close - open)       / TICK
    v = contracts traded in the bar

MNQ trades on a 0.25 grid, so every delta is an exact integer and the round
trip is lossless -- no float drift, no reconstruction error.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timedelta, timezone

TICK = 0.25
SESSION_START_MIN = 5 * 60 + 30      # 05:30 ET, the profile's first bar open
BAR_MINUTES = 20

# US Eastern DST spans covering the tape. Stated explicitly rather than pulled
# from a tz database so the decode is reproducible on a machine with no tzdata.
_DST_SPANS = (
    (date(2024, 3, 10), date(2024, 11, 2)),
    (date(2025, 3, 9), date(2025, 11, 1)),
    (date(2026, 3, 8), date(2026, 10, 31)),
)


def _et_offset_hours(day: date) -> int:
    """Return the UTC offset for `day` in Eastern time, as a negative int."""
    return -4 if any(lo <= day <= hi for lo, hi in _DST_SPANS) else -5


def decode_session(line: str) -> list[tuple[datetime, float, float, float, float, int]]:
    """Expand one packed session line into absolute OHLCV bars."""
    day_str, base_str, _n_str, pack = line.split(",", 3)
    day = date.fromisoformat(day_str)
    offset = timedelta(hours=_et_offset_hours(day))
    prev_close_ticks = int(base_str)

    rows = []
    for index, chunk in enumerate(pack.strip().strip('"').split(" ")):
        if not chunk:
            continue
        a, b, c, d, volume = (int(x) for x in chunk.split(","))
        open_ticks = prev_close_ticks + a
        high_ticks = open_ticks + b
        low_ticks = open_ticks - c
        close_ticks = open_ticks + d
        prev_close_ticks = close_ticks

        # Bar CLOSE time, which is what Bar.ts means, hence the +1.
        close_min = SESSION_START_MIN + BAR_MINUTES * (index + 1)
        et_naive = datetime(day.year, day.month, day.day) + timedelta(minutes=close_min)
        rows.append(
            (
                (et_naive - offset).replace(tzinfo=timezone.utc),
                open_ticks * TICK,
                high_ticks * TICK,
                low_ticks * TICK,
                close_ticks * TICK,
                volume,
            )
        )
    return rows


def main(src: str, dst: str) -> None:
    bars = []
    with open(src, encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if raw and not raw.startswith("#"):
                bars.extend(decode_session(raw))
    bars.sort(key=lambda row: row[0])

    with open(dst, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts", "open", "high", "low", "close", "volume"])
        for ts, o, h, l, c, v in bars:
            writer.writerow([ts.isoformat(), o, h, l, c, v])

    sessions = len({row[0].date() for row in bars})
    print(f"{len(bars)} bars over ~{sessions} days -> {dst}")
    print(f"first {bars[0][0].isoformat()}  last {bars[-1][0].isoformat()}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
