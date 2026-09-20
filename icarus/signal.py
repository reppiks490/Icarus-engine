"""The confluence core -- where seven independent reads collapse into one number.

Design rules that do not bend:

  1. **The sweep is the only trigger.** Nothing else can originate a trade.
     Every other layer exists to confirm it or veto it.
  2. **Hard gates are boolean, soft layers are continuous.** A gate failure
     kills the trade outright; a weak soft layer only drains conviction.
  3. **Direction is set by price, never by an overlay.** Sentiment and momentum
     scale the score. They cannot flip the side.
  4. **The score is normalised.** Re-weighting a layer per asset class changes
     its influence, not the meaning of the threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from icarus.config import ConfluenceWeights
from icarus.features.liquidity import LiquidityMap, Sweep
from icarus.features.orderflow import OrderFlowState
from icarus.features.sentiment import SentimentOverlay
from icarus.features.structure import MarketStructure
from icarus.ml import MLGate
from icarus.features.volatility import VolatilityState
from icarus.indicators import SessionVWAP, clamp, squash


@dataclass(frozen=True, slots=True)
class Signal:
    """The engine's verdict on one bar."""

    ts: datetime
    direction: int                              # +1 long, -1 short, 0 none
    score: float                                # composite confluence, [0, 1]
    components: dict[str, float] = field(default_factory=dict)
    sweep: Sweep | None = None
    stop_anchor: float = 0.0                    # the raid extreme the stop hides behind
    target_room_atr: float = 0.0                # clean distance to the next opposing pool
    veto: str = ""                              # populated when a hard gate failed

    @property
    def actionable(self) -> bool:
        return self.direction != 0 and not self.veto


class ConfluenceEngine:
    """Turns the feature snapshot into a single, normalised conviction score."""

    __slots__ = ("weights", "_weight_sum", "min_score", "min_target_room_atr")

    def __init__(
        self,
        weights: ConfluenceWeights,
        min_score: float = 0.58,
        min_target_room_atr: float = 1.2,
    ) -> None:
        self.weights = weights
        self._weight_sum = sum(weights.as_dict().values())
        if self._weight_sum <= 0.0:
            raise ValueError("confluence weights must sum to > 0")
        self.min_score = min_score
        self.min_target_room_atr = min_target_room_atr

    # ------------------------------------------------------------------
    # Soft layers
    # ------------------------------------------------------------------
    @staticmethod
    def _location_score(direction: int, price: float, vwap: SessionVWAP) -> float:
        """Premium/discount relative to session value.

        Longs want discount (price below VWAP), shorts want premium. Deep
        dislocation beyond ~3 sigma stops being an edge and starts being a
        trend you are standing in front of, so the curve rolls back off.
        """
        deviation = vwap.deviation(price)
        if deviation == 0.0 and vwap.value is None:
            return 0.5                                  # no value area yet: no opinion
        favourable = -direction * deviation             # positive = trading at a discount for a long
        if favourable <= 0.0:
            return clamp(0.5 + 0.18 * favourable)       # chasing: bleed the score
        return clamp(0.5 + 0.5 * min(favourable, 2.5) / 2.5 - 0.22 * max(0.0, favourable - 3.0))

    @staticmethod
    def _momentum_score(direction: int, structure: MarketStructure, rsi: float) -> float:
        """Higher-timeframe pressure, discounted at exhaustion extremes."""
        trend_component = 0.5 + 0.30 * structure.trend * direction
        # RSI is used only as an exhaustion brake: buying into 80 is buying the top.
        stretch = (rsi - 50.0) / 50.0                   # [-1, +1]
        exhaustion = max(0.0, direction * stretch - 0.55) / 0.45
        return clamp(trend_component - 0.35 * clamp(exhaustion))

    # ------------------------------------------------------------------
    def evaluate(
        self,
        *,
        ts: datetime,
        price: float,
        sweep: Sweep | None,
        volatility: VolatilityState,
        order_flow: OrderFlowState,
        structure: MarketStructure,
        liquidity: LiquidityMap,
        vwap: SessionVWAP,
        sentiment: SentimentOverlay,
        rsi: float,
        session_open: bool,
        ml: MLGate | None = None,
        ml_features: dict[str, float] | None = None,
    ) -> Signal:
        """Score the bar. Hard gates first -- they are cheap and they are absolute."""

        if not session_open:
            return Signal(ts=ts, direction=0, score=0.0, veto="session-closed")
        if not volatility.tradable:
            return Signal(ts=ts, direction=0, score=0.0, veto=f"regime:{volatility.reason}")
        if sweep is None:
            return Signal(ts=ts, direction=0, score=0.0, veto="no-trigger")

        direction = sweep.direction
        atr = volatility.atr

        # Room to the next opposing pool: the target has to physically exist.
        magnet = liquidity.nearest_pool(price, side=direction)
        target_room = abs(magnet.level - price) / atr if (magnet and atr > 0) else 0.0
        if target_room < self.min_target_room_atr:
            return Signal(
                ts=ts, direction=0, score=0.0, sweep=sweep,
                target_room_atr=target_room, veto=f"no-room:{target_room:.2f}atr",
            )

        components = {
            "sweep_quality": clamp(sweep.quality),
            "order_flow": order_flow.pressure(direction),
            "structure": structure.alignment(direction),
            "volatility": volatility.fitness,
            "location": self._location_score(direction, price, vwap),
            "momentum": self._momentum_score(direction, structure, rsi),
            "sentiment": sentiment.alignment(direction, ts),
            # The model votes like every other layer: weighted, bounded, and
            # scored 0.5 ("no opinion") whenever nothing is attached.
            "ml": ml.alignment(direction, ml_features or {}, ts) if ml is not None else 0.5,
        }

        weights = self.weights.as_dict()
        score = sum(weights[name] * value for name, value in components.items()) / self._weight_sum

        # Proxy order flow is weaker evidence than real aggressor data. Say so in
        # the score rather than pretending the two are interchangeable.
        if order_flow.is_proxy:
            score *= 0.96

        if score < self.min_score:
            return Signal(
                ts=ts, direction=0, score=score, components=components, sweep=sweep,
                stop_anchor=sweep.extreme, target_room_atr=target_room,
                veto=f"below-threshold:{score:.3f}<{self.min_score:.2f}",
            )

        return Signal(
            ts=ts,
            direction=direction,
            score=score,
            components=components,
            sweep=sweep,
            stop_anchor=sweep.extreme,
            target_room_atr=target_room,
        )
