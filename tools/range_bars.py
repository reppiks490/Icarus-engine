"""Range bars: sample the tape by price movement instead of by the clock.

Every statistic in this project has been computed on time bars, and time bars
have a defect that has been quietly contaminating all of it. A 20-minute bar at
09:35 and one at 13:05 are the same object to the code and completely different
objects to the market -- the first may contain forty times the activity of the
second. So any average over time bars is an average across regimes, and any
"edge" can be nothing more than the fact that the sample is dominated by a
particular hour of the day.

A range bar closes when price has travelled a fixed distance, whatever that
takes. The consequences are the point:

  * Bars are equal in PRICE, so a mean or a t-statistic over them is comparing
    like with like. Volatility clustering is absorbed into the bar CLOCK
    rather than leaking into the returns.
  * Quiet periods produce few bars and busy periods produce many, so the
    sample is automatically weighted toward the times something was happening.
  * Range-bar returns are far closer to identically distributed than time-bar
    returns, which is what every test used here -- t-stats, permutation nulls,
    tercile spreads -- actually assumes.

Built from whatever time bars are available rather than from ticks, so the
construction has to be honest about what it cannot see: within a source bar
the path from open to close is unknown. `_walk` states the assumption it makes
and why that assumption is the conservative one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from icarus.data import Bar


@dataclass(slots=True)
class RangeBarSpec:
    range_points: float            # how far price must travel to close a bar
    source_minutes: float          # the timeframe the bars were built from


def _walk(bar: Bar) -> list[tuple[float, float]]:
    """A plausible intrabar path as (price, volume_share) steps.

    The true path inside a source bar is unknown. The convention here is the
    standard conservative one: price is assumed to visit the extreme FURTHEST
    from the close first, then travel to the other extreme, then settle at the
    close. For a bar that closed up, that means down-first.

    This matters because the opposite assumption would let a range bar complete
    in the favourable direction before an adverse excursion that really
    happened first -- which is how intrabar path assumptions manufacture
    profits that cannot be traded. Assuming the adverse leg came first can only
    understate a result, never flatter it.
    """
    up = bar.close >= bar.open
    first, second = (bar.low, bar.high) if up else (bar.high, bar.low)
    legs = [bar.open, first, second, bar.close]
    total = sum(abs(b - a) for a, b in zip(legs, legs[1:])) or 1.0
    out = []
    for a, b in zip(legs, legs[1:]):
        out.append((b, abs(b - a) / total))
    return out


def build(bars: list[Bar], range_points: float) -> list[Bar]:
    """Collapse time bars into range bars of `range_points` travel."""
    if range_points <= 0:
        raise ValueError("range_points must be positive")

    out: list[Bar] = []
    open_px: float | None = None
    high = low = 0.0
    volume = 0.0
    stamp: datetime | None = None

    for bar in bars:
        for price, share in _walk(bar):
            if open_px is None:
                open_px = high = low = price
                volume = 0.0
            high = max(high, price)
            low = min(low, price)
            volume += bar.volume * share
            stamp = bar.ts

            if high - low >= range_points:
                # The bar closes AT the level that completed it, not at the
                # source bar's close: a range bar is defined by its travel.
                close = high if price >= open_px else low
                out.append(Bar(ts=stamp, open=open_px,
                               high=max(high, open_px, close),
                               low=min(low, open_px, close),
                               close=close, volume=round(volume, 2)))
                open_px = close
                high = low = close
                volume = 0.0
    return out


def suggest_range(bars: list[Bar], bars_per_day: float = 60.0) -> float:
    """A range size that yields roughly `bars_per_day` range bars.

    Picked from the tape's own daily travel rather than guessed, so the same
    call gives a comparable bar count on a quiet instrument and a wild one.
    """
    by_day: dict[object, list[Bar]] = {}
    for bar in bars:
        by_day.setdefault(bar.ts.date(), []).append(bar)
    travels = []
    for day in by_day.values():
        travel = sum(b.high - b.low for b in day)
        if travel > 0:
            travels.append(travel)
    if not travels:
        return 1.0
    travels.sort()
    median_travel = travels[len(travels) // 2]
    return round(median_travel / bars_per_day, 2)


def renko(bars: list[Bar], brick: float) -> list[Bar]:
    """Renko bricks: a new brick only after a full `brick` of travel.

    Distinct from a range bar, and the distinction is the reason to test both.
    A range bar closes on any `range_points` of travel in either direction, so
    it still prints during chop. A Renko brick continues the current direction
    on one brick of movement but requires TWO to reverse, which discards small
    counter-moves entirely.

    That makes Renko a deliberately lossy view: wicks and noise vanish, and
    what remains is committed directional movement. If the sweep premise is
    real it should survive that filtering, because a sweep is by definition a
    committed move through a level. If the premise only appears on time bars
    and dies on Renko, the "sweep" being detected was wick noise around a
    level rather than a genuine excursion through it.
    """
    if brick <= 0:
        raise ValueError("brick must be positive")

    out: list[Bar] = []
    anchor: float | None = None
    direction = 0

    for bar in bars:
        for price, share in _walk(bar):
            if anchor is None:
                anchor = round(price / brick) * brick
                continue
            while True:
                # Continuing costs one brick; reversing costs two, which is
                # what makes Renko a noise filter rather than a range bar.
                up_needed = brick if direction >= 0 else 2 * brick
                down_needed = brick if direction <= 0 else 2 * brick

                if price >= anchor + up_needed:
                    step = anchor + (brick if direction >= 0 else 2 * brick)
                    out.append(Bar(ts=bar.ts, open=anchor, high=step,
                                   low=anchor, close=step,
                                   volume=bar.volume * share))
                    anchor, direction = step, +1
                elif price <= anchor - down_needed:
                    step = anchor - (brick if direction <= 0 else 2 * brick)
                    out.append(Bar(ts=bar.ts, open=anchor, high=anchor,
                                   low=step, close=step,
                                   volume=bar.volume * share))
                    anchor, direction = step, -1
                else:
                    break
    return out


def volume_profile(bars: list[Bar], tick: float, *, bins: int = 60) -> dict:
    """Volume at price: where trading actually happened.

    Not a footprint -- there is no aggressor split here, because that needs
    tick data with real buy/sell labels and inventing it would make a guess
    look like a measurement. What this does give is the thing Icarus's sweep
    logic actually needs: resting liquidity is currently GUESSED from prior
    highs and lows, and a volume profile locates it from where volume traded.

    Returns the point of control, the value area (70% of volume) and the low
    volume nodes -- thin shelves that price tends to cross quickly, which is
    exactly where a sweep should travel if the premise is right.
    """
    if not bars:
        return {}
    lo = min(b.low for b in bars)
    hi = max(b.high for b in bars)
    if hi <= lo:
        return {}
    width = (hi - lo) / bins
    buckets = [0.0] * bins

    for bar in bars:
        span = bar.high - bar.low
        first = min(int((bar.low - lo) / width), bins - 1)
        last = min(int((bar.high - lo) / width), bins - 1)
        if span <= 0 or first == last:
            buckets[first] += bar.volume
            continue
        # Spread the bar's volume evenly over the prices it actually visited.
        # Uniform is the honest choice without intrabar data: any other shape
        # would be an assumption dressed as a measurement.
        share = bar.volume / (last - first + 1)
        for k in range(first, last + 1):
            buckets[k] += share

    total = sum(buckets) or 1.0
    poc = max(range(bins), key=lambda k: buckets[k])

    # Value area: grow outward from the POC until 70% of volume is enclosed.
    lo_i = hi_i = poc
    covered = buckets[poc]
    while covered < 0.70 * total and (lo_i > 0 or hi_i < bins - 1):
        below = buckets[lo_i - 1] if lo_i > 0 else -1.0
        above = buckets[hi_i + 1] if hi_i < bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += buckets[hi_i]
        else:
            lo_i -= 1
            covered += buckets[lo_i]

    median = sorted(buckets)[bins // 2]
    return {
        "poc": lo + (poc + 0.5) * width,
        "value_low": lo + lo_i * width,
        "value_high": lo + (hi_i + 1) * width,
        "low_volume_nodes": [lo + (k + 0.5) * width
                             for k in range(bins) if buckets[k] < 0.35 * median],
        "bin_width": width,
    }
