"""Sentiment overlay -- a scalar bias, never a signal.

Hard rule: sentiment can scale conviction and it can veto an over-extended
trade. It can never originate a trade and it can never flip a direction that
price, flow and structure disagree with. Sentiment data is slow, revised, and
frequently wrong at turning points; it is given exactly as much authority as
that track record deserves.

The overlay is a pluggable callable so live feeds (crypto funding and open
interest, equity put/call and breadth, FX positioning and rate differentials)
can be injected without touching the core. No feed is fabricated here: with no
provider attached the reading is a hard neutral.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol


@dataclass(frozen=True, slots=True)
class SentimentReading:
    """A sentiment observation in [-1, +1], with the time it was produced."""

    value: float
    ts: datetime
    source: str = "none"

    def __post_init__(self) -> None:
        if not -1.0 <= self.value <= 1.0:
            raise ValueError("sentiment value must be in [-1, +1]")


class SentimentSource(Protocol):
    """Anything that can answer 'what is the bias right now?'."""

    def __call__(self, ts: datetime) -> SentimentReading | None: ...


class SentimentOverlay:
    """Decays a sentiment reading toward neutral as it ages.

    ``half_life`` is how long a reading keeps half its weight. A stale feed
    quietly becomes a neutral feed instead of poisoning live decisions.
    """

    __slots__ = ("_source", "_half_life", "_latest", "_max_influence")

    def __init__(
        self,
        source: SentimentSource | Callable[[datetime], SentimentReading | None] | None = None,
        half_life: timedelta = timedelta(hours=6),
        max_influence: float = 1.0,
    ) -> None:
        self._source = source
        self._half_life = half_life
        self._latest: SentimentReading | None = None
        self._max_influence = max(0.0, min(1.0, max_influence))

    def push(self, reading: SentimentReading) -> None:
        """Inject a reading directly (live feeds, or replay in a backtest)."""
        self._latest = reading

    def update(self, ts: datetime) -> float:
        """Return the age-decayed bias in [-1, +1] for this moment."""
        if self._source is not None:
            fresh = self._source(ts)
            if fresh is not None:
                self._latest = fresh
        if self._latest is None:
            return 0.0

        age = (ts - self._latest.ts).total_seconds()
        if age < 0.0:
            return 0.0                              # reading from the future: ignore
        half_life = self._half_life.total_seconds()
        decay = 0.5 ** (age / half_life) if half_life > 0 else 0.0
        return self._latest.value * decay * self._max_influence

    def alignment(self, direction: int, ts: datetime) -> float:
        """Agreement of sentiment with ``direction``, mapped to [0, 1].

        0.5 is the neutral pivot, so an absent feed is scored as 'no opinion'
        rather than as evidence either way.
        """
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or +1")
        return 0.5 + 0.5 * direction * self.update(ts)

    @property
    def latest(self) -> SentimentReading | None:
        return self._latest


def constant_source(value: float, source: str = "constant") -> SentimentSource:
    """A fixed bias -- for stress-testing the overlay's influence, not for live use."""

    def _source(ts: datetime) -> SentimentReading:
        return SentimentReading(value=value, ts=ts, source=source)

    return _source
