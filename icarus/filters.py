"""Adaptive price filters lifted from ICARUS PROTO SUITE 01.

Two pieces, and they exist for one reason: **a trailing stop anchored to a raw
bar extreme ratchets on noise and then gets taken out by the next noise spike.**
Anchoring the trail to a filtered estimate of price is the single largest
mechanical difference between an exit that survives ten bars and one that dies
on the bar it opened.

  * ``FractalDimensionIndex`` (Ehlers' FDI) measures how space-filling the tape
    is. ~1.0 is a clean trend, ~1.5 is a random walk, ~2.0 is pure chop.
  * ``AdaptiveKalman`` is a scalar random-walk Kalman filter whose measurement
    noise is *raised* when FDI says the tape is choppy. In chop the filter
    trusts its own estimate and ignores the ticks; in a trend it tracks price
    closely. That is exactly the behaviour a trail wants.

Suite defaults preserved: measurement noise base 0.15xATR, FDI gain 0.35,
process noise base 0.05.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from icarus.indicators import RollingWindow, clamp


class FractalDimensionIndex:
    """Ehlers' Fractal Dimension Index over a rolling window of highs/lows.

    Returns a value in roughly [1.0, 2.0]. Lower means more directional.
    """

    __slots__ = ("length", "_highs", "_lows", "_smooth", "value", "_alpha", "_seeded")

    def __init__(self, length: int = 30, ema_smooth: int = 5) -> None:
        if length < 3:
            raise ValueError("FDI length must be >= 3")
        self.length = length
        self._highs = RollingWindow(length)
        self._lows = RollingWindow(length)
        self._alpha = 2.0 / (ema_smooth + 1.0)
        self._smooth: float | None = None
        self._seeded = False
        self.value = 1.5                      # random-walk prior until warm

    def update(self, high: float, low: float) -> float:
        self._highs.push(high)
        self._lows.push(low)
        if not self._highs.ready:
            return self.value

        highs = self._highs.values
        lows = self._lows.values
        span_high = max(highs)
        span_low = min(lows)
        span = span_high - span_low
        if span <= 0.0:
            return self.value

        # Normalised path length over the window, per Ehlers.
        length_sum = 0.0
        previous = (highs[0] + lows[0]) / 2.0
        for index in range(1, self.length):
            current = (highs[index] + lows[index]) / 2.0
            step = (current - previous) / span
            length_sum += math.sqrt(step * step + (1.0 / (self.length - 1)) ** 2)
            previous = current
        if length_sum <= 0.0:
            return self.value

        raw = 1.0 + (math.log(length_sum) + math.log(2.0)) / math.log(2.0 * (self.length - 1))
        raw = clamp(raw, 1.0, 2.0)
        self._smooth = raw if self._smooth is None else self._smooth + self._alpha * (raw - self._smooth)
        self._seeded = True
        self.value = self._smooth
        return self.value

    @property
    def ready(self) -> bool:
        return self._seeded

    @property
    def choppiness(self) -> float:
        """FDI mapped to [0, 1]: 0 = clean trend, 1 = pure chop."""
        return clamp((self.value - 1.0) / 1.0)


@dataclass(slots=True)
class KalmanState:
    estimate: float
    variance: float
    innovation: float          # last (measurement - prior estimate)
    innovation_z: float        # innovation in units of its own predicted sigma
    gain: float


class AdaptiveKalman:
    """Scalar random-walk Kalman filter with FDI-modulated measurement noise.

    Measurement noise R = (base + fdi_gain * choppiness) * ATR, squared.
    Process noise  Q = (process_base * ATR)^2.

    A shock (|innovation| beyond ``shock_z``) temporarily inflates R so the
    filter does not chase a spike, then decays that inflation over
    ``shock_decay`` bars. This mirrors the Suite's Shock Z-Score Trigger 2.5 /
    Shock Threshold Decay 8 / Shock Threshold Boost 1.35.
    """

    __slots__ = ("meas_base", "fdi_gain", "process_base", "shock_z", "shock_decay",
                 "shock_boost", "_estimate", "_variance", "_shock_left", "state")

    def __init__(
        self,
        measurement_noise_base: float = 0.15,
        fdi_gain: float = 0.35,
        process_noise_base: float = 0.05,
        shock_z: float = 2.5,
        shock_decay: int = 8,
        shock_boost: float = 1.35,
    ) -> None:
        self.meas_base = measurement_noise_base
        self.fdi_gain = fdi_gain
        self.process_base = process_noise_base
        self.shock_z = shock_z
        self.shock_decay = max(1, shock_decay)
        self.shock_boost = shock_boost
        self._estimate: float | None = None
        self._variance = 0.0
        self._shock_left = 0
        self.state = KalmanState(0.0, 0.0, 0.0, 0.0, 0.0)

    def update(self, measurement: float, atr: float, choppiness: float) -> KalmanState:
        if atr <= 0.0:
            atr = max(abs(measurement) * 1e-4, 1e-9)

        if self._estimate is None:
            self._estimate = measurement
            self._variance = (atr * 0.5) ** 2
            self.state = KalmanState(measurement, self._variance, 0.0, 0.0, 0.0)
            return self.state

        # Predict (random walk: estimate unchanged, variance grows by Q).
        process_var = (self.process_base * atr) ** 2
        prior_variance = self._variance + process_var
        innovation = measurement - self._estimate

        # Measurement noise, raised in chop and further during a shock.
        noise_scale = self.meas_base + self.fdi_gain * clamp(choppiness)
        if self._shock_left > 0:
            decay = self._shock_left / self.shock_decay
            noise_scale *= 1.0 + (self.shock_boost - 1.0) * decay
            self._shock_left -= 1
        measurement_var = max((noise_scale * atr) ** 2, 1e-18)

        innovation_sigma = math.sqrt(prior_variance + measurement_var)
        innovation_z = innovation / innovation_sigma if innovation_sigma > 0 else 0.0
        if abs(innovation_z) >= self.shock_z:
            self._shock_left = self.shock_decay
            measurement_var *= self.shock_boost

        gain = prior_variance / (prior_variance + measurement_var)
        self._estimate += gain * innovation
        self._variance = (1.0 - gain) * prior_variance

        self.state = KalmanState(self._estimate, self._variance, innovation, innovation_z, gain)
        return self.state

    @property
    def estimate(self) -> float | None:
        return self._estimate

    @property
    def ready(self) -> bool:
        return self._estimate is not None
