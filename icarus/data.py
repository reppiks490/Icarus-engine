"""Market data primitives for the Icarus Engine.

The core engine is deliberately dependency-free: bars stream in one at a time
and every feature updates in O(1). That keeps the same code path valid in a
research backtest and inside a live broker callback.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator, Sequence


@dataclass(frozen=True, slots=True)
class Bar:
    """A single completed OHLCV bar.

    ``bid_volume``/``ask_volume`` are optional. When a venue supplies true
    aggressor-side volume (futures, most crypto exchanges) the order-flow layer
    uses it directly; otherwise it falls back to a close-location delta proxy.
    """

    ts: datetime          # bar CLOSE time, timezone-aware, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    bid_volume: float | None = None   # volume traded at the bid (sell aggressor)
    ask_volume: float | None = None   # volume traded at the ask (buy aggressor)

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("Bar.ts must be timezone-aware (UTC)")
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(f"inconsistent OHLC at {self.ts}: {self.open=} {self.high=} {self.low=} {self.close=}")

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def typical(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    @property
    def clv(self) -> float:
        """Close Location Value in [-1, +1]: where the close sits inside the range.

        +1 = closed on the high (buyers won the bar), -1 = closed on the low.
        This is the backbone of the delta proxy when no aggressor data exists.
        """
        rng = self.range
        if rng <= 0.0:
            return 0.0
        return ((self.close - self.low) - (self.high - self.close)) / rng

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def parse_timestamp(raw: str) -> datetime:
    """Parse a timestamp into a UTC-aware datetime.

    Accepts epoch seconds/milliseconds or the common ISO-ish text forms.
    Naive timestamps are assumed to already be UTC.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("empty timestamp")
    # Epoch seconds or milliseconds.
    if raw.lstrip("-").replace(".", "", 1).isdigit():
        value = float(raw)
        if value > 1e11:  # milliseconds
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
        for fmt in _TS_FORMATS:
            try:
                parsed = datetime.strptime(normalized, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError(f"unrecognised timestamp: {raw!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_ALIASES = {
    "ts": "ts", "time": "ts", "timestamp": "ts", "date": "ts", "datetime": "ts", "open_time": "ts",
    "o": "open", "open": "open",
    "h": "high", "high": "high",
    "l": "low", "low": "low",
    "c": "close", "close": "close", "last": "close",
    "v": "volume", "volume": "volume", "vol": "volume",
    "bid_volume": "bid_volume", "bidvol": "bid_volume", "sell_volume": "bid_volume",
    "ask_volume": "ask_volume", "askvol": "ask_volume", "buy_volume": "ask_volume",
}


def load_csv(path: str) -> list[Bar]:
    """Load bars from a CSV with a header row. Column names are matched loosely."""
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no header row")
        mapping = {}
        for name in reader.fieldnames:
            key = _ALIASES.get(name.strip().lower())
            if key and key not in mapping:
                mapping[key] = name
        missing = {"ts", "open", "high", "low", "close"} - mapping.keys()
        if missing:
            raise ValueError(f"{path} missing column(s): {sorted(missing)}")
        for row in reader:
            def optional(field: str) -> float | None:
                column = mapping.get(field)
                if column is None:
                    return None
                raw = (row.get(column) or "").strip()
                return float(raw) if raw else None

            bars.append(
                Bar(
                    ts=parse_timestamp(row[mapping["ts"]]),
                    open=float(row[mapping["open"]]),
                    high=float(row[mapping["high"]]),
                    low=float(row[mapping["low"]]),
                    close=float(row[mapping["close"]]),
                    volume=optional("volume") or 0.0,
                    bid_volume=optional("bid_volume"),
                    ask_volume=optional("ask_volume"),
                )
            )
    bars.sort(key=lambda bar: bar.ts)
    return bars


# --------------------------------------------------------------------------
# Deterministic synthetic tape (so the repo self-verifies with no vendor feed)
# --------------------------------------------------------------------------

def synthetic_series(
    bars: int = 3000,
    start_price: float = 100.0,
    minutes: int = 5,
    seed: int = 7,
    start: datetime | None = None,
    trend_strength: float = 0.35,
    base_vol: float = 0.0012,
) -> list[Bar]:
    """Generate a deterministic regime-switching tape.

    Not a market model -- a test fixture. It produces trending legs, ranges,
    volatility expansion/contraction and stop-run wicks, which is exactly the
    structure the engine claims to exploit. Seeded, so results are reproducible.
    """
    rng = random.Random(seed)
    clock = start or datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    step = timedelta(minutes=minutes)

    out: list[Bar] = []
    price = start_price
    drift = 0.0
    vol = base_vol
    regime_left = 0

    for _ in range(bars):
        if regime_left <= 0:
            regime_left = rng.randint(40, 180)
            roll = rng.random()
            if roll < 0.35:                      # trending leg
                drift = trend_strength * base_vol * rng.choice((-1.0, 1.0))
                vol = base_vol * rng.uniform(0.9, 1.6)
            elif roll < 0.75:                    # balance / range
                drift = 0.0
                vol = base_vol * rng.uniform(0.4, 0.8)
            else:                                # expansion / shock
                drift = trend_strength * base_vol * rng.choice((-1.5, 1.5))
                vol = base_vol * rng.uniform(1.8, 3.0)
        regime_left -= 1

        shock = rng.gauss(drift, vol)
        open_ = price
        close = max(0.01, open_ * math.exp(shock))
        span = abs(close - open_)
        # Wick asymmetry: occasional deep stop-run tails.
        sweep = rng.random() < 0.07
        up_tail = span * rng.uniform(0.2, 1.1) + (open_ * vol * rng.uniform(1.5, 3.5) if sweep and rng.random() < 0.5 else 0.0)
        dn_tail = span * rng.uniform(0.2, 1.1) + (open_ * vol * rng.uniform(1.5, 3.5) if sweep and rng.random() >= 0.5 else 0.0)
        high = max(open_, close) + up_tail
        low = max(0.005, min(open_, close) - dn_tail)

        volume = max(1.0, rng.gauss(1000.0, 250.0) * (1.0 + 4.0 * abs(shock) / max(vol, 1e-9) * 0.1))
        buy_share = 0.5 + 0.35 * (((close - low) - (high - close)) / (high - low) if high > low else 0.0)
        buy_share = min(0.95, max(0.05, buy_share + rng.gauss(0.0, 0.05)))

        clock += step
        out.append(
            Bar(
                ts=clock,
                open=round(open_, 6),
                high=round(high, 6),
                low=round(low, 6),
                close=round(close, 6),
                volume=round(volume, 2),
                bid_volume=round(volume * (1.0 - buy_share), 2),
                ask_volume=round(volume * buy_share, 2),
            )
        )
        price = close
    return out


def stream(bars: Iterable[Bar]) -> Iterator[Bar]:
    """Yield bars in ascending time order, rejecting out-of-order data."""
    previous: datetime | None = None
    for bar in bars:
        if previous is not None and bar.ts < previous:
            raise ValueError(f"out-of-order bar at {bar.ts} (previous {previous})")
        previous = bar.ts
        yield bar


def to_csv(bars: Sequence[Bar], path: str) -> None:
    """Write bars back out in the canonical column order."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts", "open", "high", "low", "close", "volume", "bid_volume", "ask_volume"])
        for bar in bars:
            writer.writerow([
                bar.ts.isoformat(),
                bar.open, bar.high, bar.low, bar.close, bar.volume,
                "" if bar.bid_volume is None else bar.bid_volume,
                "" if bar.ask_volume is None else bar.ask_volume,
            ])


# Realistic price scale and volatility per venue. Without this a synthetic tape
# printing $100 with a $0.25 tick makes every asset look cost-bound, which is an
# artefact of the fixture, not of the engine.
_SYNTHETIC_CALIBRATION = {
    "equity":  {"start_price": 185.00, "base_vol": 0.0011, "minutes": 5},
    "futures": {"start_price": 5200.00, "base_vol": 0.0008, "minutes": 5},
    "forex":   {"start_price": 1.08500, "base_vol": 0.00045, "minutes": 5},
    "crypto":  {"start_price": 64000.0, "base_vol": 0.0025, "minutes": 5},
}


def synthetic_for(asset_class, bars: int = 4000, seed: int = 7, **overrides) -> list[Bar]:
    """Synthetic tape calibrated to an asset class's real price scale and vol."""
    key = getattr(asset_class, "value", str(asset_class))
    params = dict(_SYNTHETIC_CALIBRATION[key])
    params.update(overrides)
    return synthetic_series(bars=bars, seed=seed, **params)
