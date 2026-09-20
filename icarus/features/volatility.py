"""Volatility regime: the engine's permission slip.

Icarus does not trade every tape. Dead volatility means the target is inside
the spread; shock volatility means stops are noise and fills are fiction. The
edge lives in the middle band, and it is sharpest when compression is resolving
into expansion.
"""

from __future__ import annotations

from dataclasses import dataclass

from icarus.data import Bar
from icarus.indicators import ATR, EMA, RollingWindow, clamp


@dataclass(frozen=True, slots=True)
class VolatilityState:
    atr: float
    percentile: float          # ATR rank within its own recent history, [0, 1]
    expansion: float           # fast ATR / slow ATR; > 1 means expanding
    squeeze: float             # realised range vs its own baseline; < 1 means compressed
    shock: float               # bar range in ATRs -- a spike guard
    tradable: bool             # regime gate result
    reason: str = ""

    @property
    def fitness(self) -> float:
        """Regime desirability in [0, 1] -- compression resolving into expansion."""
        if not self.tradable:
            return 0.0
        # Prefer mid-band volatility: peak at the 55th percentile.
        band = 1.0 - abs(self.percentile - 0.55) / 0.55
        # Reward expansion out of a squeeze, penalise a stalling tape.
        breakout = clamp((self.expansion - 0.95) / 0.35)
        coiled = clamp((1.05 - self.squeeze) / 0.35)
        return clamp(0.45 * clamp(band) + 0.35 * breakout + 0.20 * coiled)


class VolatilityEngine:
    """Tracks ATR, its regime percentile, expansion and compression."""

    __slots__ = ("atr", "_fast", "_slow", "_range_window", "_min_pct", "_max_pct",
                 "_min_atr_to_cost", "state")

    def __init__(
        self,
        atr_period: int = 14,
        regime_lookback: int = 240,
        min_percentile: float = 0.20,
        max_percentile: float = 0.97,
        min_atr_to_cost_ratio: float = 6.0,
    ) -> None:
        self.atr = ATR(atr_period, regime_lookback)
        self._fast = EMA(max(2, atr_period // 2))
        self._slow = EMA(atr_period * 3)
        self._range_window = RollingWindow(max(20, atr_period * 4))
        self._min_pct = min_percentile
        self._max_pct = max_percentile
        self._min_atr_to_cost = min_atr_to_cost_ratio
        self.state = VolatilityState(0.0, 0.5, 1.0, 1.0, 0.0, False, "warmup")

    def update(self, bar: Bar, round_turn_cost: float) -> VolatilityState:
        atr = self.atr.update(bar.high, bar.low, bar.close)
        fast = self._fast.update(atr)
        slow = self._slow.update(atr)
        self._range_window.push(bar.range)

        expansion = fast / slow if slow > 0 else 1.0
        baseline = self._range_window.mean
        squeeze = (bar.range / baseline) if baseline > 0 else 1.0
        shock = (bar.range / atr) if atr > 0 else 0.0
        percentile = self.atr.percentile

        reason = ""
        tradable = True
        if not self.atr.ready or not self.atr.regime_ready:
            tradable, reason = False, "warmup"
        elif atr <= 0.0:
            tradable, reason = False, "zero-atr"
        elif percentile < self._min_pct:
            tradable, reason = False, f"dead-tape p={percentile:.2f}"
        elif percentile > self._max_pct:
            tradable, reason = False, f"shock-tape p={percentile:.2f}"
        elif round_turn_cost > 0.0 and atr / round_turn_cost < self._min_atr_to_cost:
            tradable, reason = False, f"cost-bound atr/cost={atr / round_turn_cost:.1f}"
        elif shock > 4.0:
            tradable, reason = False, f"range-spike {shock:.1f}atr"

        self.state = VolatilityState(
            atr=atr, percentile=percentile, expansion=expansion,
            squeeze=squeeze, shock=shock, tradable=tradable, reason=reason,
        )
        return self.state
