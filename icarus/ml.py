"""Machine-learning seam: the socket an XGBoost model plugs into.

ICARUS PROTO SUITE 01's HUD carries a row reading ``XGB5:67L/44S`` -- a model
voting 67 long against 44 short. This module is the contract for that vote, and
the exporter that produces the training rows it would be fitted on.

Two deliberate boundaries:

  1. **No model is fabricated here.** With nothing attached, ``MLGate`` returns
     a hard neutral 0.5 and the ``ml`` confluence weight defaults to 0.0, so the
     engine behaves exactly as if this module did not exist. A model that does
     not exist must not be able to move size.
  2. **The model votes, it does not decide.** Like sentiment, the ML score is a
     weighted component of the confluence. It cannot originate a trade -- only a
     liquidity sweep can -- and it cannot flip a direction that price set.

The exporter is the point of this file. ``FeatureExporter`` dumps, for every
bar, the complete engine state plus triple-barrier labels, which is exactly the
matrix an XGBoost classifier needs and exactly the matrix this engine can
reproduce live, feature for feature, with no train/serve skew.
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable, Protocol, Sequence

from icarus.data import Bar
from icarus.indicators import clamp


# ---------------------------------------------------------------------------
# The vote contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ModelVote:
    """A model's opinion at a moment, in the Suite's own long/short vote form."""

    long_score: float          # >= 0
    short_score: float         # >= 0
    ts: datetime
    model_id: str = "unknown"
    confidence: float = 1.0    # [0, 1]; scales how far the vote moves the score

    def __post_init__(self) -> None:
        if self.long_score < 0.0 or self.short_score < 0.0:
            raise ValueError("vote scores must be non-negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")

    @property
    def edge(self) -> float:
        """Net directional lean in [-1, +1]. 67L/44S -> +0.207."""
        total = self.long_score + self.short_score
        if total <= 0.0:
            return 0.0
        return (self.long_score - self.short_score) / total


class ModelSource(Protocol):
    """Anything that can produce a vote for a feature row."""

    def __call__(self, features: dict[str, float], ts: datetime) -> ModelVote | None: ...


class MLGate:
    """Folds a model vote into the confluence, with staleness decay.

    Identical discipline to the sentiment overlay: an absent, stale or abstaining
    model scores 0.5 -- 'no opinion' -- never 0.0, which would read as evidence
    against the trade.
    """

    __slots__ = ("_source", "_half_life", "_latest", "_max_influence", "_min_confidence")

    def __init__(
        self,
        source: ModelSource | Callable[[dict[str, float], datetime], ModelVote | None] | None = None,
        half_life: timedelta = timedelta(minutes=30),
        max_influence: float = 1.0,
        min_confidence: float = 0.0,
    ) -> None:
        self._source = source
        self._half_life = half_life
        self._latest: ModelVote | None = None
        self._max_influence = clamp(max_influence)
        self._min_confidence = clamp(min_confidence)

    def push(self, vote: ModelVote) -> None:
        """Inject a vote directly (live inference, or replay in a backtest)."""
        self._latest = vote

    def update(self, features: dict[str, float], ts: datetime) -> float:
        """Return the age-decayed model edge in [-1, +1] for this moment."""
        if self._source is not None:
            fresh = self._source(features, ts)
            if fresh is not None:
                self._latest = fresh
        vote = self._latest
        if vote is None or vote.confidence < self._min_confidence:
            return 0.0

        age = (ts - vote.ts).total_seconds()
        if age < 0.0:
            return 0.0                                  # a vote from the future is not a vote
        half_life = self._half_life.total_seconds()
        decay = 0.5 ** (age / half_life) if half_life > 0 else 0.0
        return vote.edge * decay * vote.confidence * self._max_influence

    def alignment(self, direction: int, features: dict[str, float], ts: datetime) -> float:
        """Agreement of the model with ``direction``, mapped to [0, 1]."""
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or +1")
        return clamp(0.5 + 0.5 * direction * self.update(features, ts))

    @property
    def latest(self) -> ModelVote | None:
        return self._latest


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BarrierLabel:
    """Triple-barrier outcome for one bar, in ATR units."""

    label: int              # +1 upper hit first, -1 lower hit first, 0 neither
    bars_to_hit: int        # horizon when neither barrier was touched
    forward_atr: float      # close-to-close move over the horizon, in ATRs
    mfe_atr: float
    mae_atr: float


def triple_barrier(
    bars: Sequence[Bar],
    index: int,
    atr: float,
    upper_atr: float = 2.0,
    lower_atr: float = 1.0,
    horizon: int = 24,
) -> BarrierLabel | None:
    """Label bar ``index`` by which barrier price reaches first.

    This is the correct target for a trade-entry classifier: it asks 'did a
    favourable move of ``upper_atr`` happen *before* an adverse move of
    ``lower_atr``', which is the question the strategy actually faces. A plain
    forward return conflates a clean winner with one that first ran the stop.

    Returns None when the horizon runs past the end of the data, so a partially
    observed outcome is never labelled as a real one.
    """
    if atr <= 0.0:
        return None
    end = index + horizon
    if end >= len(bars):
        return None

    entry = bars[index].close
    upper = entry + upper_atr * atr
    lower = entry - lower_atr * atr
    best = worst = 0.0
    label, hit_at = 0, horizon

    for step in range(1, horizon + 1):
        bar = bars[index + step]
        best = max(best, (bar.high - entry) / atr)
        worst = min(worst, (bar.low - entry) / atr)
        # Pessimistic ordering: if a bar spans both barriers, the adverse one won.
        if bar.low <= lower:
            label, hit_at = -1, step
            break
        if bar.high >= upper:
            label, hit_at = 1, step
            break

    return BarrierLabel(
        label=label,
        bars_to_hit=hit_at,
        forward_atr=(bars[end].close - entry) / atr,
        mfe_atr=best,
        mae_atr=worst,
    )


# ---------------------------------------------------------------------------
# Feature export
# ---------------------------------------------------------------------------

# The exact feature contract. Live inference MUST build this same dict from the
# same engine state, or the model is being served data it was not trained on.
FEATURE_COLUMNS: tuple[str, ...] = (
    "atr", "atr_pct", "expansion", "squeeze", "shock", "vol_fitness",
    "fdi", "choppiness", "kalman_dev_atr", "kalman_gain",
    "cvd_slope", "delta_z", "absorption", "divergence", "flow_is_proxy",
    "structure_trend", "bars_since_structure", "align_long", "align_short",
    "sweep_quality", "sweep_penetration_atr", "sweep_reclaim_bars",
    "sweep_direction", "pool_weight", "target_room_atr",
    "vwap_dev", "rsi", "htf_position", "session_open", "minute_of_day",
    "score", "c_sweep_quality", "c_order_flow", "c_structure",
    "c_volatility", "c_location", "c_momentum", "c_sentiment",
)

LABEL_COLUMNS: tuple[str, ...] = ("label", "bars_to_hit", "forward_atr", "mfe_atr", "mae_atr")


def engine_features(engine, bar: Bar, sweep=None, signal=None) -> dict[str, float]:
    """Snapshot the engine as a flat feature row.

    Everything here is available at bar close with no forward information, so a
    model trained on these rows can be served identically in production.
    """
    volatility = engine.volatility.state
    flow = engine.order_flow.state
    structure = engine.structure
    atr = volatility.atr or 1e-9

    kalman = engine.kalman.estimate
    htf_high, htf_low = engine.htf.high, engine.htf.low
    if htf_high is not None and htf_low is not None and htf_high > htf_low:
        htf_position = (bar.close - htf_low) / (htf_high - htf_low)
    else:
        htf_position = 0.5

    row: dict[str, float] = {
        "atr": volatility.atr,
        "atr_pct": volatility.percentile,
        "expansion": volatility.expansion,
        "squeeze": volatility.squeeze,
        "shock": volatility.shock,
        "vol_fitness": volatility.fitness,
        "fdi": engine.fdi.value,
        "choppiness": engine.fdi.choppiness,
        "kalman_dev_atr": (bar.close - kalman) / atr if kalman is not None else 0.0,
        "kalman_gain": engine.kalman.state.gain,
        "cvd_slope": flow.cvd_slope,
        "delta_z": flow.delta_z,
        "absorption": flow.absorption,
        "divergence": flow.divergence,
        "flow_is_proxy": 1.0 if flow.is_proxy else 0.0,
        "structure_trend": float(structure.trend),
        "bars_since_structure": float(min(999, structure.bars_since_event())),
        "align_long": structure.alignment(1),
        "align_short": structure.alignment(-1),
        "sweep_quality": sweep.quality if sweep else 0.0,
        "sweep_penetration_atr": sweep.penetration_atr if sweep else 0.0,
        "sweep_reclaim_bars": float(sweep.reclaim_bars) if sweep else 0.0,
        "sweep_direction": float(sweep.direction) if sweep else 0.0,
        "pool_weight": sweep.pool.weight if sweep else 0.0,
        "target_room_atr": signal.target_room_atr if signal else 0.0,
        "vwap_dev": engine.vwap.deviation(bar.close),
        "rsi": engine.rsi.value,
        "htf_position": htf_position,
        "session_open": 1.0 if engine.in_session(bar.ts) else 0.0,
        "minute_of_day": float(bar.ts.hour * 60 + bar.ts.minute),
        "score": signal.score if signal else 0.0,
    }
    components = signal.components if signal else {}
    for name in ("sweep_quality", "order_flow", "structure", "volatility",
                 "location", "momentum", "sentiment"):
        row[f"c_{name}"] = components.get(name, 0.0)
    return row


def export_training_set(
    bars: Sequence[Bar],
    profile,
    path: str,
    *,
    upper_atr: float = 2.0,
    lower_atr: float = 1.0,
    horizon: int = 24,
    sweeps_only: bool = True,
    exit_policy: str | None = None,
    timeframe: str | int | None = None,
) -> int:
    """Replay the engine and write a labelled feature matrix to CSV.

    ``sweeps_only`` keeps only bars where the engine's own trigger fired, which
    is the population a trade classifier is actually asked about. Set it False
    to label every bar (useful for regime models).

    Returns the number of rows written.
    """
    from icarus.strategy import IcarusEngine

    engine = IcarusEngine(profile, exit_policy=exit_policy, timeframe=timeframe)
    rows: list[dict[str, float]] = []
    bars = list(bars)

    for index, bar in enumerate(bars):
        engine.on_bar(bar)
        sweep = engine.liquidity.last_sweep
        fired = sweep is not None and sweep.index == engine.state.bar_index
        if sweeps_only and not fired:
            continue

        label = triple_barrier(bars, index, engine.volatility.state.atr,
                               upper_atr, lower_atr, horizon)
        if label is None:
            continue                                   # horizon not fully observed
        row = engine_features(engine, bar, sweep if fired else None, engine.state.signal)
        row.update(asdict(label))
        row["ts"] = bar.ts.isoformat()
        rows.append(row)

    columns = ("ts",) + FEATURE_COLUMNS + LABEL_COLUMNS
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
