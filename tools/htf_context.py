"""Real higher/lower-timeframe context for PulseStrategy, built causally.

`pulse.py` takes five HTF connections as (direction, regime) and two LTF reads
as (direction, bars_since_flip, regime). Feeding it neutral zeros -- as an
earlier version of tools/validate_pulse.py did -- switches off the MTF vote and
one of the twelve confluence votes outright, which understates the strategy and
makes any result from it worthless.

This builds those series from the chart tape itself. The only rule that matters
is causality: the value attached to a chart bar closing at time T may only come
from higher-timeframe bars that had already CLOSED at or before T. A bar that
is still forming is not information.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from icarus.data import Bar
from icarus.indicators import ATR, EMA
from icarus.timeframe import parse_timeframe, resample

# The Suite's own five connections, transcribed from its input panel.
HTF_CHAIN = ("1h", "4h", "1d", "1w", "1M")
LTF_CHAIN = ("2m", "5m")

# Calendar timeframes the resampler does not speak, expressed in minutes.
_CALENDAR = {"1d": 1440, "1w": 1440 * 5, "1M": 1440 * 21}


def _minutes(label: str) -> int:
    return _CALENDAR.get(label) or parse_timeframe(label)


@dataclass(slots=True)
class _Track:
    """Direction, regime and flip-age for one timeframe, indexed by close time."""

    closes: list[float]          # epoch seconds of each HTF bar's close
    direction: list[float]       # +1 / -1 / 0
    regime: list[float]          # ATR percentile in [0, 1]
    flip_age: list[float]        # bars since direction last changed

    def at(self, ts: float) -> tuple[float, float, float]:
        """The most recent value that had CLOSED at or before ``ts``."""
        index = bisect.bisect_right(self.closes, ts) - 1
        if index < 0:
            return 0.0, 0.5, 0.0
        return self.direction[index], self.regime[index], self.flip_age[index]


def build_track(bars: list[Bar], label: str, ema_period: int = 20) -> _Track:
    """Derive direction and regime on one timeframe.

    Direction is the sign of close minus an EMA of close -- the cheapest honest
    trend read. Regime is the ATR percentile, matching how the engine's own
    volatility layer scores a tape.
    """
    series = resample(bars, _minutes(label))
    ema, atr = EMA(ema_period), ATR(14, 200)
    closes: list[float] = []
    direction: list[float] = []
    regime: list[float] = []
    flip_age: list[float] = []

    previous_dir, age = 0.0, 0.0
    for bar in series:
        mean = ema.update(bar.close)
        atr.update(bar.high, bar.low, bar.close)
        current = 0.0 if not ema.ready else (1.0 if bar.close > mean else -1.0)
        age = 0.0 if current != previous_dir else age + 1.0
        previous_dir = current

        closes.append(bar.ts.timestamp())
        direction.append(current)
        regime.append(atr.percentile if atr.regime_ready else 0.5)
        flip_age.append(age)

    return _Track(closes, direction, regime, flip_age)


class ContextProvider:
    """Serves causal (htf, ltf) context for each chart bar."""

    def __init__(self, bars: list[Bar], chart_tf: str,
                 htf_chain: tuple[str, ...] = HTF_CHAIN,
                 ltf_chain: tuple[str, ...] = LTF_CHAIN) -> None:
        chart_minutes = parse_timeframe(chart_tf)
        # A "higher" timeframe below the chart is not higher; drop it rather
        # than silently feed the strategy a faster series in an HTF slot.
        self.htf_labels = [x for x in htf_chain if _minutes(x) >= chart_minutes]
        self.ltf_labels = [x for x in ltf_chain if parse_timeframe(x) <= chart_minutes]
        self.htf = [build_track(bars, label) for label in self.htf_labels]
        self.ltf = [build_track(bars, label) for label in self.ltf_labels]
        self._n_htf = len(htf_chain)
        self._n_ltf = len(ltf_chain)

    def at(self, ts: float) -> tuple[list[tuple[float, float]], list[tuple[float, float, float]]]:
        htf = [(t.at(ts)[0], t.at(ts)[1]) for t in self.htf]
        # Pad to the five slots pulse.py expects; a dropped slot reads neutral.
        htf += [(0.0, 0.5)] * (self._n_htf - len(htf))

        ltf = []
        for track in self.ltf:
            d, r, age = track.at(ts)
            ltf.append((d, age, r))
        ltf += [(0.0, 10.0, 0.5)] * (self._n_ltf - len(ltf))
        return htf[: self._n_htf], ltf[: self._n_ltf]
