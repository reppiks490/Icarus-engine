"""Can a lower timeframe capture a higher timeframe's move?

Every test in this project so far asked the same question -- can the next move's
DIRECTION be predicted -- and the answer kept coming back no. A permutation
null on the finished strategy put the entry signal at p=0.377 held-out.

This asks something different, and separable. Given that a large HTF bar
happens, how much of it is reachable by an LTF entry with a tight stop? That
is not prediction. Nothing here forecasts direction: the trigger fires only
AFTER price has already committed a set distance from the HTF bar's open, and
the direction is read off that commitment rather than guessed.

The distinction matters because the two failures are unrelated. A signal can
have no directional edge and the market can still hand over large, capturable
moves -- in which case the problem was never the entry, it was that the entry
was being asked to do the impossible while the execution layer left the move
on the table.

What the measurement has to establish, in order:

  1. Are big HTF bars DIRECTIONAL, or do they end where they started after a
     wide round trip? Range tells you nothing on its own; a 200-point bar that
     closes flat is not a trend, it is a fight.
  2. Does the move DEVELOP, or does it arrive in one print? A move that
     happens inside a single LTF bar is not tradeable at any speed, because
     the entry and the move occupy the same instant.
  3. Once a causal trigger has fired, how much is LEFT, and what heat does it
     take first? That ratio is the whole system: remaining favourable
     excursion over adverse excursion after entry.

Everything is computed from the LTF bars inside each HTF bar, so the HTF bar's
own close is never consulted before the LTF path that produced it.
"""

from __future__ import annotations

import statistics as st
from dataclasses import dataclass


@dataclass(slots=True)
class CaptureResult:
    triggered: bool
    direction: int
    entry_price: float
    entry_sub_bar: int          # which LTF bar inside the HTF bar fired it
    mfe: float                  # best favourable excursion after entry, points
    mae: float                  # worst adverse excursion after entry, points
    realised: float             # move from entry to the end of the window
    htf_range: float
    htf_body: float


def group_by_htf(ltf_bars, htf_minutes: int, ltf_minutes: int):
    """Slice LTF bars into the HTF buckets they belong to, in order."""
    per = max(1, htf_minutes // ltf_minutes)
    step = htf_minutes * 60
    buckets: dict[int, list] = {}
    for bar in ltf_bars:
        key = int(bar.ts.timestamp()) // step
        buckets.setdefault(key, []).append(bar)
    return [buckets[k] for k in sorted(buckets) if len(buckets[k]) >= per - 1]


def commitment_entry(sub_bars, trigger_points: float,
                     horizon_bars: int | None = None) -> CaptureResult | None:
    """Enter once price has committed `trigger_points` from the window's open.

    Strictly causal. The trigger reads price that has already printed, and the
    direction is whichever side committed first -- never the side the window
    eventually closed on. If both sides are touched inside one LTF bar the bar
    is ambiguous at this resolution, and the conservative reading is taken:
    the ADVERSE side is assumed to have come first, so an entry can never be
    credited to the favourable leg of a bar that also went against it.
    """
    if not sub_bars:
        return None
    open_px = sub_bars[0].open
    window = sub_bars if horizon_bars is None else sub_bars[:horizon_bars]
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    body = window[-1].close - open_px

    for index, bar in enumerate(window):
        up = bar.high >= open_px + trigger_points
        down = bar.low <= open_px - trigger_points
        if not (up or down):
            continue
        if up and down:
            # Ambiguous inside one bar: take the side that is worse for us.
            direction = -1 if body > 0 else +1
        else:
            direction = +1 if up else -1
        entry = open_px + direction * trigger_points

        rest = window[index:]
        best = max(b.high for b in rest) if direction > 0 else min(b.low for b in rest)
        worst = min(b.low for b in rest) if direction > 0 else max(b.high for b in rest)
        return CaptureResult(
            triggered=True, direction=direction, entry_price=entry,
            entry_sub_bar=index,
            mfe=direction * (best - entry),
            mae=direction * (worst - entry),
            realised=direction * (window[-1].close - entry),
            htf_range=hi - lo, htf_body=abs(body),
        )
    return None


def directionality(sub_bars) -> float:
    """|close - open| / (high - low): how much of the range the move kept.

    Near 1.0 is a trend bar that went one way and stayed. Near 0.0 is a wide
    round trip that ended where it began -- the same range, and untradeable.
    """
    if not sub_bars:
        return 0.0
    hi = max(b.high for b in sub_bars)
    lo = min(b.low for b in sub_bars)
    span = hi - lo
    return abs(sub_bars[-1].close - sub_bars[0].open) / span if span > 0 else 0.0


def concentration(sub_bars) -> float:
    """Share of the window's total travel contributed by its single busiest bar.

    Near 1.0 means the move arrived in one print and no faster chart could have
    got in front of it. Low values mean the move developed across the window,
    which is the only case where execution on a lower timeframe can help.
    """
    if not sub_bars:
        return 0.0
    travels = [b.high - b.low for b in sub_bars]
    total = sum(travels)
    return max(travels) / total if total > 0 else 0.0


def atr_of(bars, window: int = 14) -> list[float]:
    out = [0.0] * len(bars)
    running = 0.0
    trs = [0.0] * len(bars)
    for i in range(1, len(bars)):
        b, p = bars[i], bars[i - 1]
        trs[i] = max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close))
    for i in range(1, len(bars)):
        running += trs[i]
        if i > window:
            running -= trs[i - window]
        out[i] = running / min(i, window)
    return out


def summarise(values: list[float]) -> str:
    if not values:
        return "no data"
    s = sorted(values)
    return (f"median {st.median(s):7.2f}  mean {st.fmean(s):7.2f}  "
            f"p25 {s[len(s)//4]:7.2f}  p75 {s[3*len(s)//4]:7.2f}")
