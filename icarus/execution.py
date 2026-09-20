"""Execution primitives: intents, positions, fills, and honest friction.

P&L is expressed in generic *units* where one unit earns one currency unit per
one price unit of favourable movement. For equities a unit is a share; for
futures it is one contract times its multiplier; for FX it is one unit of base
currency. The engine never sees the difference -- the profile's ``CostModel``
carries the venue-specific truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from icarus.config import CostModel


class IntentKind(str, Enum):
    ENTER = "enter"
    SCALE_OUT = "scale_out"
    EXIT = "exit"
    MOVE_STOP = "move_stop"


@dataclass(frozen=True, slots=True)
class TradeIntent:
    """What the engine wants done. The broker adapter turns this into orders."""

    kind: IntentKind
    ts: datetime
    direction: int              # +1 long, -1 short
    size: float                 # units; 0.0 for MOVE_STOP
    price: float                # reference price (entry/exit level or new stop)
    reason: str = ""
    score: float = 0.0


@dataclass(slots=True)
class Position:
    """A live position with its full risk envelope attached."""

    direction: int
    size: float
    entry_price: float
    entry_ts: datetime
    entry_index: int
    stop: float
    risk_unit: float                     # price distance of 1R at entry -- never re-based
    first_target: float
    runner_target: float | None
    initial_size: float
    score: float = 0.0
    reason: str = ""
    scaled_out: bool = False
    breakeven_moved: bool = False
    max_favourable: float = 0.0          # in R
    max_adverse: float = 0.0             # in R
    realised: float = 0.0                # currency already banked from scale-outs

    def r_multiple(self, price: float) -> float:
        """Unrealised move in R at ``price``."""
        if self.risk_unit <= 0.0:
            return 0.0
        return self.direction * (price - self.entry_price) / self.risk_unit

    def track_excursion(self, high: float, low: float) -> None:
        """Update MAE/MFE using the bar's true extremes, not its close."""
        favourable = self.r_multiple(high if self.direction > 0 else low)
        adverse = self.r_multiple(low if self.direction > 0 else high)
        self.max_favourable = max(self.max_favourable, favourable)
        self.max_adverse = min(self.max_adverse, adverse)

    def stop_hit(self, high: float, low: float) -> bool:
        return low <= self.stop if self.direction > 0 else high >= self.stop

    def target_hit(self, high: float, low: float, level: float) -> bool:
        return high >= level if self.direction > 0 else low <= level


@dataclass(slots=True)
class Trade:
    """A closed trade, in both currency and R."""

    direction: int
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    r: float
    bars_held: int
    score: float
    reason_in: str
    reason_out: str
    mae_r: float
    mfe_r: float


def apply_entry_cost(price: float, direction: int, costs: CostModel, atr_percentile: float) -> float:
    """Worsen an entry fill by the modelled spread and volatility-scaled slippage."""
    return price + direction * costs.entry_cost(atr_percentile)


def apply_exit_cost(price: float, direction: int, costs: CostModel, atr_percentile: float) -> float:
    """Worsen an exit fill by the same friction, applied against the position."""
    return price - direction * costs.entry_cost(atr_percentile)


def commission(size: float, costs: CostModel) -> float:
    """Per-side commission on ``size`` units."""
    return abs(size) * costs.commission_per_unit


@dataclass(slots=True)
class Blotter:
    """Trade log plus the running equity curve."""

    starting_equity: float
    equity: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    peak_equity: float = 0.0
    max_drawdown: float = 0.0

    def __post_init__(self) -> None:
        self.equity = self.starting_equity
        self.peak_equity = self.starting_equity

    def record(self, trade: Trade) -> None:
        self.trades.append(trade)

    def mark(self, ts: datetime, delta: float) -> None:
        """Apply a realised P&L delta and refresh drawdown statistics."""
        self.equity += delta
        self.peak_equity = max(self.peak_equity, self.equity)
        drawdown = self.peak_equity - self.equity
        self.max_drawdown = max(self.max_drawdown, drawdown)
        self.equity_curve.append((ts, self.equity))
