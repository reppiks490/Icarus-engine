"""Streaming indicator primitives.

Every object here updates in O(1) (or O(window) worst case for rank queries)
and holds only the state it needs. No vectorised look-ahead is possible by
construction: an indicator can never see a bar it has not been fed.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Iterable


class RollingWindow:
    """Fixed-length FIFO of floats with cached sum for O(1) mean."""

    __slots__ = ("size", "_values", "_sum")

    def __init__(self, size: int) -> None:
        if size < 1:
            raise ValueError("window size must be >= 1")
        self.size = size
        self._values: Deque[float] = deque(maxlen=size)
        self._sum = 0.0

    def push(self, value: float) -> None:
        if len(self._values) == self.size:
            self._sum -= self._values[0]
        self._values.append(value)
        self._sum += value

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self):
        return iter(self._values)

    def __getitem__(self, index: int) -> float:
        return self._values[index]

    @property
    def ready(self) -> bool:
        return len(self._values) == self.size

    @property
    def values(self) -> list[float]:
        return list(self._values)

    @property
    def mean(self) -> float:
        return self._sum / len(self._values) if self._values else 0.0

    @property
    def last(self) -> float | None:
        return self._values[-1] if self._values else None

    def max(self) -> float:
        return max(self._values) if self._values else 0.0

    def min(self) -> float:
        return min(self._values) if self._values else 0.0

    def std(self) -> float:
        count = len(self._values)
        if count < 2:
            return 0.0
        mean = self.mean
        variance = sum((value - mean) ** 2 for value in self._values) / (count - 1)
        return math.sqrt(variance)

    def percentile_of(self, value: float) -> float:
        """Fraction of stored observations at or below ``value`` -> [0, 1]."""
        if not self._values:
            return 0.5
        below = sum(1 for stored in self._values if stored <= value)
        return below / len(self._values)

    def zscore(self, value: float) -> float:
        deviation = self.std()
        if deviation <= 0.0:
            return 0.0
        return (value - self.mean) / deviation


class EMA:
    """Exponential moving average, seeded on the first sample."""

    __slots__ = ("period", "alpha", "value", "_count")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("EMA period must be >= 1")
        self.period = period
        self.alpha = 2.0 / (period + 1.0)
        self.value: float | None = None
        self._count = 0

    def update(self, sample: float) -> float:
        self._count += 1
        if self.value is None:
            self.value = sample
        else:
            self.value += self.alpha * (sample - self.value)
        return self.value

    @property
    def ready(self) -> bool:
        return self._count >= self.period


class WilderRMA:
    """Wilder's smoothing (the average behind ATR/RSI). Seeded with an SMA."""

    __slots__ = ("period", "value", "_seed", "_count")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("RMA period must be >= 1")
        self.period = period
        self.value: float | None = None
        self._seed = 0.0
        self._count = 0

    def update(self, sample: float) -> float:
        self._count += 1
        if self._count < self.period:
            self._seed += sample
            self.value = self._seed / self._count
        elif self._count == self.period:
            self._seed += sample
            self.value = self._seed / self.period
        else:
            assert self.value is not None
            self.value += (sample - self.value) / self.period
        return self.value

    @property
    def ready(self) -> bool:
        return self._count >= self.period


class ATR:
    """Average True Range over Wilder smoothing, plus a regime percentile."""

    __slots__ = ("_rma", "_prev_close", "_regime", "value")

    def __init__(self, period: int = 14, regime_lookback: int = 240) -> None:
        self._rma = WilderRMA(period)
        self._prev_close: float | None = None
        self._regime = RollingWindow(regime_lookback)
        self.value: float = 0.0

    def update(self, high: float, low: float, close: float) -> float:
        if self._prev_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        self.value = self._rma.update(true_range)
        self._regime.push(self.value)
        return self.value

    @property
    def ready(self) -> bool:
        return self._rma.ready

    @property
    def percentile(self) -> float:
        """Where the current ATR sits in its own recent distribution, [0, 1]."""
        if len(self._regime) < 20:
            return 0.5
        return self._regime.percentile_of(self.value)

    @property
    def regime_ready(self) -> bool:
        return len(self._regime) >= 20


class RSI:
    """Wilder RSI. Used only as a momentum-exhaustion modifier, never alone."""

    __slots__ = ("_gain", "_loss", "_prev_close", "value")

    def __init__(self, period: int = 14) -> None:
        self._gain = WilderRMA(period)
        self._loss = WilderRMA(period)
        self._prev_close: float | None = None
        self.value: float = 50.0

    def update(self, close: float) -> float:
        if self._prev_close is None:
            self._prev_close = close
            return self.value
        change = close - self._prev_close
        self._prev_close = close
        average_gain = self._gain.update(max(change, 0.0))
        average_loss = self._loss.update(max(-change, 0.0))
        if average_loss <= 0.0:
            self.value = 100.0 if average_gain > 0.0 else 50.0
        else:
            self.value = 100.0 - 100.0 / (1.0 + average_gain / average_loss)
        return self.value

    @property
    def ready(self) -> bool:
        return self._gain.ready


class SessionVWAP:
    """Volume-weighted average price anchored to a session, with sigma bands.

    Bands are computed from the volume-weighted variance of typical price about
    the VWAP -- the standard anchored-VWAP band, not a Bollinger substitute.
    """

    __slots__ = ("_pv", "_volume", "_pv2", "value", "sigma", "_bars")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._pv = 0.0
        self._pv2 = 0.0
        self._volume = 0.0
        self._bars = 0
        self.value: float | None = None
        self.sigma: float = 0.0

    def update(self, typical: float, volume: float) -> float | None:
        # Fall back to equal weighting when a venue reports no volume (spot FX).
        weight = volume if volume > 0.0 else 1.0
        self._pv += typical * weight
        self._pv2 += typical * typical * weight
        self._volume += weight
        self._bars += 1
        if self._volume <= 0.0:
            return None
        self.value = self._pv / self._volume
        variance = max(0.0, self._pv2 / self._volume - self.value * self.value)
        self.sigma = math.sqrt(variance)
        return self.value

    def band(self, multiple: float) -> tuple[float, float] | None:
        """Return (lower, upper) at ``multiple`` sigma, or None before warmup."""
        if self.value is None or self._bars < 5 or self.sigma <= 0.0:
            return None
        return (self.value - multiple * self.sigma, self.value + multiple * self.sigma)

    def deviation(self, price: float) -> float:
        """Signed sigma-distance of ``price`` from VWAP (0.0 before warmup)."""
        if self.value is None or self.sigma <= 0.0:
            return 0.0
        return (price - self.value) / self.sigma


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp ``value`` into [low, high]."""
    return low if value < low else high if value > high else value


def squash(value: float, scale: float = 1.0) -> float:
    """Map an unbounded score to [0, 1] with a smooth, monotone curve."""
    if scale <= 0.0:
        raise ValueError("scale must be > 0")
    return 0.5 * (1.0 + math.tanh(value / scale))


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0
