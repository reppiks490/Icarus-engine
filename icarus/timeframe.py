"""Timeframe handling: resampling, and honest rescaling of bar-count parameters.

A parameter measured in *bars* is really a parameter measured in *time*. Moving
a 10-minute calibration onto a 2-minute chart without rescaling turns a 4-hour
time stop into a 48-minute one and a 150-minute cooldown into 30 minutes. That
is not a different timeframe, it is a different strategy wearing the same name.

``Profile.at_timeframe`` rescales every bar-count field by the timeframe ratio
and leaves every ATR-relative and fractional field alone, because those are
already scale-free.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Iterable, Sequence

from icarus.config import Profile
from icarus.data import Bar

# Chart timeframes this engine speaks, in minutes.
TIMEFRAMES: dict[str, int] = {
    "1m": 1, "2m": 2, "3m": 3, "5m": 5, "10m": 10,
    "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240,
}

# Fields that count BARS and therefore must scale with the bar size.
_BAR_COUNT_FIELDS = (
    "atr_period", "atr_regime_lookback", "structure_lookback",
    "absorption_lookback", "cvd_fast", "cvd_slow",
    "time_stop_bars", "cooldown_bars_after_exit",
)

# Fields deliberately NOT scaled: sweep_reclaim_bars and swing_strength are
# shape parameters (how many bars define a pivot / a failed raid), not durations.


def parse_timeframe(label: str | int) -> int:
    """Return minutes for a timeframe label, or pass an int through."""
    if isinstance(label, int):
        if label < 1:
            raise ValueError("timeframe minutes must be >= 1")
        return label
    key = str(label).strip().lower()
    if key in TIMEFRAMES:
        return TIMEFRAMES[key]
    if key.endswith("m") and key[:-1].isdigit():
        return int(key[:-1])
    if key.endswith("h") and key[:-1].isdigit():
        return int(key[:-1]) * 60
    raise ValueError(f"unrecognised timeframe {label!r}; known: {sorted(TIMEFRAMES)}")


def scale_bars(count: int, from_minutes: int, to_minutes: int, minimum: int = 1) -> int:
    """Convert a bar count from one timeframe to another, preserving duration."""
    if from_minutes <= 0 or to_minutes <= 0:
        raise ValueError("timeframe minutes must be positive")
    scaled = round(count * from_minutes / to_minutes)
    return max(minimum, int(scaled))


def at_timeframe(profile: Profile, timeframe: str | int) -> Profile:
    """Rescale a profile's bar-count fields onto a different chart timeframe."""
    target = parse_timeframe(timeframe)
    source = profile.base_timeframe_min
    if target == source:
        return profile
    overrides = {
        field: scale_bars(getattr(profile, field), source, target, minimum=2)
        for field in _BAR_COUNT_FIELDS
    }
    overrides["base_timeframe_min"] = target
    return replace(profile, **overrides)


def resample(bars: Sequence[Bar], minutes: int | str) -> list[Bar]:
    """Aggregate bars into a coarser timeframe, anchored to the wall clock.

    Buckets are aligned to midnight UTC so a 10m bar always closes at :00, :10,
    :20 and so on -- the same grid a chart uses. Partial trailing buckets are
    kept: dropping them silently loses the most recent data.
    """
    target = parse_timeframe(minutes)
    if not bars:
        return []
    step = timedelta(minutes=target)

    out: list[Bar] = []
    bucket_end = None
    open_ = high = low = close = 0.0
    volume = bid = ask = 0.0
    has_flow = False

    def flush() -> None:
        if bucket_end is None:
            return
        out.append(Bar(
            ts=bucket_end, open=open_, high=high, low=low, close=close, volume=volume,
            bid_volume=bid if has_flow else None,
            ask_volume=ask if has_flow else None,
        ))

    for bar in bars:
        # Bucket by the bar's CLOSE time, on the wall-clock grid.
        epoch_minutes = int(bar.ts.timestamp() // 60)
        index = (epoch_minutes - 1) // target + 1          # close time -> its bucket
        end = bar.ts.replace(second=0, microsecond=0)
        end = end.fromtimestamp(index * target * 60, tz=bar.ts.tzinfo)

        if bucket_end is None or end != bucket_end:
            flush()
            bucket_end = end
            open_, high, low, close = bar.open, bar.high, bar.low, bar.close
            volume, bid, ask = bar.volume, 0.0, 0.0
            has_flow = bar.bid_volume is not None and bar.ask_volume is not None
            if has_flow:
                bid, ask = bar.bid_volume, bar.ask_volume
        else:
            high = max(high, bar.high)
            low = min(low, bar.low)
            close = bar.close
            volume += bar.volume
            if has_flow and bar.bid_volume is not None and bar.ask_volume is not None:
                bid += bar.bid_volume
                ask += bar.ask_volume
            else:
                has_flow = False
    flush()
    return out


def htf_bars(chart_minutes: int | str, htf_minutes: int | str) -> int:
    """How many chart bars make one higher-timeframe window (e.g. 24 x 10m = 4H)."""
    chart = parse_timeframe(chart_minutes)
    higher = parse_timeframe(htf_minutes)
    if higher < chart:
        raise ValueError(f"higher timeframe {higher}m is below chart timeframe {chart}m")
    return max(2, round(higher / chart))
