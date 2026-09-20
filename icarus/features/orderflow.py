"""Order flow: who is actually paying up, and who is getting absorbed.

Two data paths, one interface:
  * True aggressor volume (futures, most crypto venues) is used when present.
  * Otherwise a close-location delta proxy is used -- volume signed by where the
    bar closed inside its range. It is a proxy, it is labelled as a proxy, and
    the confluence layer discounts it via the per-asset order-flow weight.
"""

from __future__ import annotations

from dataclasses import dataclass

from icarus.data import Bar
from icarus.indicators import EMA, RollingWindow, clamp, squash


@dataclass(frozen=True, slots=True)
class OrderFlowState:
    delta: float               # signed volume on this bar
    cvd: float                 # cumulative volume delta (session-anchored)
    cvd_slope: float           # fast CVD EMA minus slow, normalised by volume
    delta_z: float             # this bar's delta vs its recent distribution
    absorption: float          # effort (volume) without result (price) -> [0, 1]
    divergence: float          # signed: price extreme unconfirmed by CVD
    is_proxy: bool             # True when aggressor data was unavailable

    def pressure(self, direction: int) -> float:
        """Order-flow agreement with ``direction`` (+1 long / -1 short), [0, 1].

        Blends three independent reads: the slope of cumulative delta, the size
        of the current bar's delta, and absorption at the extreme (which favours
        the *reversal* side and is therefore the sweep's natural ally).
        """
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or +1")
        slope = squash(direction * self.cvd_slope, scale=0.35)
        impulse = squash(direction * self.delta_z, scale=1.5)
        absorbed = clamp(self.absorption) if direction * self.divergence >= 0 else 0.0
        score = 0.45 * slope + 0.30 * impulse + 0.25 * absorbed
        return clamp(score)


class OrderFlowEngine:
    """Streaming CVD, delta statistics, absorption and divergence."""

    __slots__ = ("_cvd", "_fast", "_slow", "_delta_window", "_volume_window",
                 "_price_window", "_cvd_window", "_absorb_lookback", "state")

    def __init__(self, fast: int = 12, slow: int = 48, absorption_lookback: int = 20) -> None:
        self._cvd = 0.0
        self._fast = EMA(fast)
        self._slow = EMA(slow)
        self._delta_window = RollingWindow(max(40, slow))
        self._volume_window = RollingWindow(max(40, slow))
        self._price_window = RollingWindow(absorption_lookback)
        self._cvd_window = RollingWindow(absorption_lookback)
        self._absorb_lookback = absorption_lookback
        self.state = OrderFlowState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, True)

    def reset_session(self) -> None:
        """Re-anchor cumulative delta at the session boundary."""
        self._cvd = 0.0
        self._cvd_window = RollingWindow(self._absorb_lookback)

    @staticmethod
    def bar_delta(bar: Bar) -> tuple[float, bool]:
        """Return (signed volume, is_proxy) for a bar."""
        if bar.ask_volume is not None and bar.bid_volume is not None:
            return bar.ask_volume - bar.bid_volume, False
        return bar.clv * bar.volume, True

    def update(self, bar: Bar) -> OrderFlowState:
        delta, is_proxy = self.bar_delta(bar)
        self._cvd += delta
        self._delta_window.push(delta)
        self._volume_window.push(max(bar.volume, 1e-9))
        self._price_window.push(bar.close)
        self._cvd_window.push(self._cvd)

        fast = self._fast.update(self._cvd)
        slow = self._slow.update(self._cvd)
        average_volume = self._volume_window.mean or 1.0
        cvd_slope = (fast - slow) / average_volume

        delta_z = self._delta_window.zscore(delta)

        # Absorption: heavy volume that fails to move price. Effort without result
        # is somebody filling size against the move -- the tell behind a failed raid.
        volume_z = self._volume_window.zscore(max(bar.volume, 1e-9))
        travel = abs(bar.close - bar.open) / bar.range if bar.range > 0 else 0.0
        absorption = clamp(squash(volume_z, scale=1.2) * (1.0 - travel) * 1.6)

        # Divergence: price prints a new extreme that CVD refuses to confirm.
        divergence = 0.0
        # CVD is session-anchored and its window is rebuilt on every roll, so
        # both windows must be full before an extreme is comparable.
        if (len(self._price_window) >= self._absorb_lookback
                and len(self._cvd_window) >= self._absorb_lookback):
            prices = self._price_window.values
            cvds = self._cvd_window.values
            if bar.close >= max(prices[:-1]) and cvds[-1] < max(cvds[:-1]):
                divergence = -1.0          # bearish: new high, weaker flow
            elif bar.close <= min(prices[:-1]) and cvds[-1] > min(cvds[:-1]):
                divergence = 1.0           # bullish: new low, stronger flow

        self.state = OrderFlowState(
            delta=delta, cvd=self._cvd, cvd_slope=cvd_slope, delta_z=delta_z,
            absorption=absorption, divergence=divergence, is_proxy=is_proxy,
        )
        return self.state
