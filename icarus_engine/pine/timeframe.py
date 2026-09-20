"""Bars, timeframe aggregation, and Pine's time/session built-ins.

Timestamps are UTC epoch seconds of the bar OPEN (like Pine's `time`).
Intraday buckets are aligned to the UTC epoch, which is how TradingView aligns
bars for 24/7 crypto symbols whose exchange timezone is UTC (Coinbase, Binance).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Optional, Tuple

try:  # zoneinfo needs the IANA database (present on this machine; tzdata pip package elsewhere)
    from zoneinfo import ZoneInfo
    _NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - manual US-Eastern DST fallback
    _NY = None


@dataclass(frozen=True)
class Bar:
    ts: int          # open time, UTC epoch seconds
    o: float
    h: float
    l: float
    c: float
    v: float


def tf_minutes(tf: str) -> int:
    """Pine timeframe strings: "1", "2", "5", "15", "60", "240", "D", "W" (also "1D", "1W", "4H")."""
    t = str(tf).strip().upper()
    if t in ("D", "1D"):
        return 1440
    if t in ("W", "1W"):
        return 10080
    if t.endswith("D"):
        return int(t[:-1]) * 1440
    if t.endswith("W"):
        return int(t[:-1]) * 10080
    if t.endswith("H"):
        return int(t[:-1]) * 60
    if t.endswith("M"):
        return int(t[:-1])
    return int(t)


def bucket_start(ts: int, minutes: int) -> int:
    span = minutes * 60
    return (int(ts) // span) * span


class Aggregator:
    """Builds `minutes`-bars from smaller bars (normally 1m). `push` returns the list
    of bars completed by this sub-bar (0, 1 or - after a data gap - 2); `forming`
    is the live, not-yet-closed bar."""

    def __init__(self, minutes: int, bucket_fn=None, end_fn=None):
        self.minutes = int(minutes)
        self.span = self.minutes * 60
        self.bucket_fn = bucket_fn or bucket_start        # (ts, minutes) -> bucket open; calendars supply session-aligned ones
        self.end_fn = end_fn                              # (bucket, minutes) -> bucket end; calendars truncate the last bar of a session
        self.forming: Optional[List[float]] = None   # [ts, o, h, l, c, v]
        self.bucket: Optional[int] = None
        self.last_closed: Optional[int] = None       # a late sub-bar for an already-closed bucket is dropped

    def _end(self) -> int:
        b = self.bucket or 0
        if self.end_fn is not None:
            return int(self.end_fn(b, self.minutes))
        return b + (7 * 86400 if self.minutes >= 10080 else 86400 if self.minutes >= 1440 else self.span)

    def push(self, b: Bar, sub_minutes: int = 1) -> List[Bar]:
        out: List[Bar] = []
        bk = self.bucket_fn(b.ts, self.minutes)
        if self.last_closed is not None and bk <= self.last_closed:
            return out
        if self.bucket is not None and bk != self.bucket:
            done = self._close()
            if done is not None:
                out.append(done)
        if self.forming is None:
            self.bucket = bk
            self.forming = [bk, b.o, b.h, b.l, b.c, b.v]
        else:
            f = self.forming
            f[2] = max(f[2], b.h); f[3] = min(f[3], b.l); f[4] = b.c; f[5] += b.v
        # the sub-bar that ends exactly on the bucket boundary closes the bucket now
        if b.ts + sub_minutes * 60 >= self._end():
            done = self._close()
            if done is not None:
                out.append(done)
        return out

    def _close(self) -> Optional[Bar]:
        if self.forming is None:
            return None
        f = self.forming
        self.forming, self.bucket = None, None
        self.last_closed = int(f[0])
        return Bar(int(f[0]), f[1], f[2], f[3], f[4], f[5])

    def flush_if_stale(self, now_ts: float, grace: float = 3.0) -> Optional[Bar]:
        """Close the forming bar if wall-clock time has passed its end (missing sub-bars)."""
        if self.forming is not None and self.bucket is not None and now_ts >= self._end() + grace:
            return self._close()
        return None

    def forming_bar(self) -> Optional[Bar]:
        f = self.forming
        return None if f is None else Bar(int(f[0]), f[1], f[2], f[3], f[4], f[5])


# ── New-York time helpers (Pine: hour(time, "America/New_York") etc.) ──
def _ny(ts: int) -> datetime:
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    if _NY is not None:
        return dt.astimezone(_NY)
    return dt + timedelta(hours=-5 + (1 if _is_us_dst(dt) else 0))


def _is_us_dst(dt_utc: datetime) -> bool:
    y = dt_utc.year
    # second Sunday of March 07:00 UTC (02:00 EST) → first Sunday of November 06:00 UTC (02:00 EDT)
    mar = datetime(y, 3, 1, 7, tzinfo=timezone.utc)
    start = mar + timedelta(days=(6 - mar.weekday()) % 7 + 7)
    nov = datetime(y, 11, 1, 6, tzinfo=timezone.utc)
    end = nov + timedelta(days=(6 - nov.weekday()) % 7)
    return start <= dt_utc < end


def ny_hour_minute(ts: int) -> Tuple[int, int]:
    d = _ny(ts)
    return d.hour, d.minute


def ny_hour(ts: int) -> int:
    return _ny(ts).hour


def ny_minute(ts: int) -> int:
    return _ny(ts).minute


def ny_dayofmonth(ts: int) -> int:
    return _ny(ts).day


def ny_date_str(ts: int) -> str:
    return _ny(ts).strftime("%Y-%m-%d")


def utc_date_str(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def in_session(ts: int, session: str) -> bool:
    """Pine `not na(time(timeframe.period, "HHMM-HHMM", "America/New_York"))` for the bar
    whose OPEN time is `ts`: true when the open falls inside [start, end). Overnight
    windows (1800-0930) wrap midnight. Days-of-week spec is not used by the strategy."""
    s = session.split(":")[0]
    a, b = s.split("-")
    start = int(a[:2]) * 60 + int(a[2:])
    end = int(b[:2]) * 60 + int(b[2:])
    h, m = ny_hour_minute(ts)
    now = h * 60 + m
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def iter_minutes(start_ts: int, end_ts: int, step_min: int) -> Iterator[int]:
    t = start_ts
    while t < end_ts:
        yield t
        t += step_min * 60
