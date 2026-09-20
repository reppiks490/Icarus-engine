"""Market structure: swing pivots, trend state, break of structure, CHoCH.

Structure is the engine's skeleton. A sweep tells us where liquidity died; the
structure break tells us the market accepted the new direction. Without the
second half, a sweep is just a wick.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Deque

from icarus.data import Bar


class SwingType(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class Swing:
    """A confirmed fractal pivot."""

    ts: datetime
    price: float
    kind: SwingType
    index: int          # bar index of the pivot itself, not of its confirmation


class StructureEvent(str, Enum):
    NONE = "none"
    BOS_UP = "bos_up"        # continuation: prior swing high taken in an uptrend
    BOS_DOWN = "bos_down"
    CHOCH_UP = "choch_up"    # character change: first higher high after a downtrend
    CHOCH_DOWN = "choch_down"


class SwingDetector:
    """Fractal pivot detector with configurable strength.

    A pivot at index i is confirmed only after ``strength`` bars have printed on
    its right. Confirmation therefore always lags by ``strength`` bars -- that
    lag is real and is never removed, because removing it is look-ahead.
    """

    __slots__ = ("strength", "_bars", "_index", "last_high", "last_low")

    def __init__(self, strength: int = 2) -> None:
        if strength < 1:
            raise ValueError("swing strength must be >= 1")
        self.strength = strength
        self._bars: Deque[tuple[int, Bar]] = deque(maxlen=2 * strength + 1)
        self._index = -1
        self.last_high: Swing | None = None
        self.last_low: Swing | None = None

    def update(self, bar: Bar) -> list[Swing]:
        """Feed a bar; return any pivots confirmed by it."""
        self._index += 1
        self._bars.append((self._index, bar))
        if len(self._bars) < self._bars.maxlen:
            return []

        centre_index, centre = self._bars[self.strength]
        left = [item[1] for item in list(self._bars)[: self.strength]]
        right = [item[1] for item in list(self._bars)[self.strength + 1 :]]
        confirmed: list[Swing] = []

        # Strict on the right, non-strict on the left: ties resolve to the
        # earlier pivot so equal highs form a cluster rather than flip-flopping.
        if all(candidate.high <= centre.high for candidate in left) and all(
            candidate.high < centre.high for candidate in right
        ):
            swing = Swing(ts=centre.ts, price=centre.high, kind=SwingType.HIGH, index=centre_index)
            self.last_high = swing
            confirmed.append(swing)

        if all(candidate.low >= centre.low for candidate in left) and all(
            candidate.low > centre.low for candidate in right
        ):
            swing = Swing(ts=centre.ts, price=centre.low, kind=SwingType.LOW, index=centre_index)
            self.last_low = swing
            confirmed.append(swing)

        return confirmed


class MarketStructure:
    """Trend state machine driven by confirmed pivots and closing breaks.

    ``trend`` is +1 (higher highs and higher lows), -1 (lower lows and lower
    highs) or 0 (undecided / balanced).
    """

    __slots__ = (
        "detector", "lookback", "trend", "last_event", "last_event_index",
        "swing_highs", "swing_lows", "_index", "_protected_high", "_protected_low",
        "last_swings",
    )

    def __init__(self, strength: int = 2, lookback: int = 60) -> None:
        self.detector = SwingDetector(strength)
        self.lookback = lookback
        self.trend: int = 0
        self.last_event: StructureEvent = StructureEvent.NONE
        self.last_event_index: int = -10**9
        self.swing_highs: Deque[Swing] = deque(maxlen=lookback)
        self.swing_lows: Deque[Swing] = deque(maxlen=lookback)
        self.last_swings: list[Swing] = []   # pivots confirmed by the most recent bar
        self._index = -1
        # The swing that must break for the current trend to be invalidated.
        self._protected_high: float | None = None
        self._protected_low: float | None = None

    def update(self, bar: Bar) -> StructureEvent:
        self._index += 1
        self.last_swings = self.detector.update(bar)
        for swing in self.last_swings:
            if swing.kind is SwingType.HIGH:
                self.swing_highs.append(swing)
            else:
                self.swing_lows.append(swing)

        event = StructureEvent.NONE
        reference_high = self.swing_highs[-1].price if self.swing_highs else None
        reference_low = self.swing_lows[-1].price if self.swing_lows else None

        # A break is only real on a CLOSE through the level. Wicks through a
        # swing are raids -- that is the liquidity layer's business, not this one.
        if reference_high is not None and bar.close > reference_high:
            event = StructureEvent.BOS_UP if self.trend >= 0 else StructureEvent.CHOCH_UP
            self.trend = 1
            self._protected_low = reference_low
        elif reference_low is not None and bar.close < reference_low:
            event = StructureEvent.BOS_DOWN if self.trend <= 0 else StructureEvent.CHOCH_DOWN
            self.trend = -1
            self._protected_high = reference_high

        if event is not StructureEvent.NONE:
            self.last_event = event
            self.last_event_index = self._index
        return event

    @property
    def index(self) -> int:
        return self._index

    def bars_since_event(self) -> int:
        return self._index - self.last_event_index

    def alignment(self, direction: int) -> float:
        """How well ``direction`` (+1 long / -1 short) agrees with structure, [0, 1].

        A fresh CHoCH in the trade direction scores highest: that is the moment
        the market changes hands. A stale, opposing trend scores near zero.
        """
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or +1")

        score = 0.5 + 0.25 * self.trend * direction   # 0.25 / 0.5 / 0.75

        want_choch = StructureEvent.CHOCH_UP if direction > 0 else StructureEvent.CHOCH_DOWN
        want_bos = StructureEvent.BOS_UP if direction > 0 else StructureEvent.BOS_DOWN
        age = self.bars_since_event()
        if age <= 8:
            freshness = 1.0 - age / 8.0
            if self.last_event is want_choch:
                score += 0.45 * freshness
            elif self.last_event is want_bos:
                score += 0.30 * freshness
            elif self.last_event is not StructureEvent.NONE:
                score -= 0.30 * freshness          # structure just broke against us

        return max(0.0, min(1.0, score))

    @property
    def protected_low(self) -> float | None:
        return self._protected_low

    @property
    def protected_high(self) -> float | None:
        return self._protected_high
