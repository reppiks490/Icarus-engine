"""Exit policies -- the layer that decides how long a trade is allowed to live.

The diagnosis this module exists to fix, measured on the engine's own blotter:

    median stop distance ......... 1.0 - 1.2 ATR
    trades dead on the entry bar . 8 - 21%
    exits that were stops ........ 52 - 88%
    median hold .................. 3 - 8 bars

A stop one ATR from entry sits *inside a single bar's expected range* -- that is
what ATR means. The trade is therefore a coin flip on its own entry bar, and the
engine never reaches the part of the distribution where its edge lives.

ICARUS PROTO SUITE 01 solves this with four mechanisms, all transplanted here:

  1. **Stop distance floored in ATR terms** (Suite: Min ATR Mult 1.9, Max 5.0,
     SL ATR Multiple 4.5). Expected time-to-stop under diffusion scales with the
     *square* of the barrier distance, so 4x the room is ~16x the survival.
  2. **The runner replaces the static target** (Suite: Enable Trailing TP2).
     A fixed 2.6R target caps the winner at exactly the size the stop-dominated
     loser side cannot pay for.
  3. **The trail is anchored to a filtered price, not a bar extreme** (Suite:
     Kalman Trail Buffer 0.3xATR). A raw-high trail ratchets on every noise
     spike and is then taken out by the next one.
  4. **An endurance target drawn from higher-timeframe structure** (Suite:
     Endurance Target = opposite side of the 4H range) instead of an R multiple.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque

from icarus.config import Profile
from icarus.data import Bar
from icarus.execution import Position


class ActionKind(str, Enum):
    SCALE_OUT = "scale_out"
    MOVE_STOP = "move_stop"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class ManageAction:
    """One instruction from a policy to the engine, for this bar."""

    kind: ActionKind
    price: float
    reason: str
    fraction: float = 0.0        # SCALE_OUT only: fraction of remaining size


@dataclass(frozen=True, slots=True)
class Envelope:
    """The risk geometry a policy assigns to a new trade."""

    stop: float
    risk_unit: float
    first_target: float
    runner_target: float | None   # None means 'no static target -- trail decides'
    reason: str = ""


@dataclass(slots=True)
class ExitContext:
    """Everything a policy may look at. Strictly current-bar or older."""

    atr: float
    atr_percentile: float = 0.5
    bar_index: int = 0
    kalman: float | None = None            # filtered price estimate
    choppiness: float = 0.5                # FDI mapped to [0, 1]
    structure_stop: float | None = None    # nearest opposing confirmed swing
    structure_target: float | None = None  # structure objective in the trade direction
    htf_high: float | None = None          # higher-timeframe range extremes
    htf_low: float | None = None
    ltf_strength: float = 1.0              # 1.0 = lower timeframe agrees, 0.0 = failing


class HTFRange:
    """Rolling higher-timeframe range, built from the bar stream itself.

    ``bars`` is how many chart bars make one higher-timeframe window -- e.g. 24
    bars of 10m is the Suite's 4H range. No ``request.security`` equivalent is
    needed and no look-ahead is possible.
    """

    __slots__ = ("bars", "_highs", "_lows")

    def __init__(self, bars: int = 24) -> None:
        if bars < 2:
            raise ValueError("HTF range needs >= 2 bars")
        self.bars = bars
        self._highs: Deque[float] = deque(maxlen=bars)
        self._lows: Deque[float] = deque(maxlen=bars)

    def update(self, bar: Bar) -> None:
        self._highs.append(bar.high)
        self._lows.append(bar.low)

    @property
    def ready(self) -> bool:
        return len(self._highs) == self.bars

    @property
    def high(self) -> float | None:
        return max(self._highs) if self.ready else None

    @property
    def low(self) -> float | None:
        return min(self._lows) if self.ready else None


# ---------------------------------------------------------------------------
# Policy interface
# ---------------------------------------------------------------------------

class ExitPolicy(ABC):
    """How a trade is stopped, scaled, trailed and finally killed."""

    name: str = "abstract"

    @abstractmethod
    def build(self, profile: Profile, direction: int, entry_price: float,
              stop_anchor: float, ctx: ExitContext) -> Envelope | None:
        """Assign the risk geometry, or None to refuse the trade."""

    @abstractmethod
    def manage(self, position: Position, bar: Bar, ctx: ExitContext,
               profile: Profile) -> list[ManageAction]:
        """Return this bar's instructions, worst case first."""

    # -- shared helpers -----------------------------------------------------
    @staticmethod
    def _clamped_stop(direction: int, entry: float, raw_stop: float, atr: float,
                      min_atr: float, max_atr: float) -> tuple[float, float]:
        """Force the stop into [min_atr, max_atr] ATRs of the entry.

        This is the whole ballgame. A stop nearer than ``min_atr`` is noise
        exposure priced as signal; one further than ``max_atr`` is an
        un-sizeable idea.
        """
        distance = abs(entry - raw_stop)
        floor = max(min_atr * atr, 0.0)
        ceiling = max_atr * atr if max_atr > 0 else float("inf")
        distance = max(floor, min(distance, ceiling))
        if distance <= 0.0:
            return raw_stop, 0.0
        return entry - direction * distance, distance

    @staticmethod
    def _stop_breached(position: Position, bar: Bar) -> bool:
        return position.stop_hit(bar.high, bar.low)


# ---------------------------------------------------------------------------
# 1. Pulse -- the engine's original geometry, preserved verbatim as the control
# ---------------------------------------------------------------------------

class PulseExit(ExitPolicy):
    """The v1.0.0 behaviour. Kept intact so every comparison has a baseline.

    Stop sits just beyond the raid extreme, targets are fixed R multiples, and
    the trail is anchored to the raw bar extreme.
    """

    name = "pulse"

    def build(self, profile, direction, entry_price, stop_anchor, ctx):
        buffer = profile.stop_buffer_atr * ctx.atr
        stop = stop_anchor - direction * buffer
        risk_unit = abs(entry_price - stop)
        if risk_unit <= 0.0:
            risk_unit = max(ctx.atr * profile.stop_buffer_atr, 1e-9)
            stop = entry_price - direction * risk_unit
        if direction * (entry_price - stop) <= 0.0:
            return None
        return Envelope(
            stop=stop,
            risk_unit=risk_unit,
            first_target=entry_price + direction * profile.first_target_r * risk_unit,
            runner_target=entry_price + direction * profile.runner_target_r * risk_unit,
            reason="pulse:raid-extreme",
        )

    def manage(self, position, bar, ctx, profile):
        actions: list[ManageAction] = []
        if self._stop_breached(position, bar):
            return [ManageAction(ActionKind.EXIT, position.stop, "stop")]

        if not position.scaled_out and position.target_hit(bar.high, bar.low, position.first_target):
            actions.append(ManageAction(ActionKind.SCALE_OUT, position.first_target,
                                        "first-target", profile.scale_out_fraction))
            if profile.breakeven_at_r > 0.0:
                actions.append(ManageAction(ActionKind.MOVE_STOP, position.entry_price, "breakeven"))

        if position.runner_target is not None and position.target_hit(bar.high, bar.low, position.runner_target):
            actions.append(ManageAction(ActionKind.EXIT, position.runner_target, "runner-target"))
            return actions

        if position.scaled_out and profile.trail_atr_mult > 0.0:
            distance = profile.trail_atr_mult * ctx.atr
            candidate = (bar.high - distance) if position.direction > 0 else (bar.low + distance)
            if position.direction * (candidate - position.stop) > 0.0:
                actions.append(ManageAction(ActionKind.MOVE_STOP, candidate, "atr-trail"))
        return actions


# ---------------------------------------------------------------------------
# 2. Suite -- ICARUS PROTO SUITE 01's exit model, transplanted
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SuiteParams:
    """Defaults read directly off the Suite's input panel (MNQ1!, 10m)."""

    stop_mode: str = "structure"        # structure | atr | points | percent
    sl_atr_mult: float = 4.5
    tp1_atr_mult: float = 3.0
    tp2_atr_mult: float = 6.0
    sl_points: float = 80.0             # SL (NQ pts)
    tp1_points: float = 140.0
    tp2_points: float = 200.0
    sl_percent: float = 0.42            # SL % of Price
    tp1_percent: float = 0.30
    tp2_percent: float = 0.45
    structure_sl_buffer_atr: float = 0.5
    structure_tp2_extension: float = 1.5
    min_stop_atr: float = 1.9           # Rate Engine: Min ATR Mult
    max_stop_atr: float = 5.0           # Rate Engine: Max ATR Mult
    trailing_tp2: bool = True           # runner replaces static TP2
    trail_distance_atr: float = 1.5
    kalman_trail_buffer_atr: float = 0.3
    tighten_on_ltf_weakness: bool = False
    ltf_weak_threshold: float = 0.35
    tighten_multiplier: float = 0.55
    endurance_target: bool = True       # opposite side of the HTF range
    scale_out_fraction: float = 0.5
    arm_trail_after_tp1: bool = True


class SuiteExit(ExitPolicy):
    """Structure-anchored stop, ATR-floored, Kalman-trailed runner.

    The three changes that buy hold time, in order of measured impact:
      1. the stop is floored at ``min_stop_atr`` ATRs (1.9 by default) and
         defaults to the opposing swing rather than the raid extreme;
      2. TP2 is a trail, not a price, so a winner is never capped;
      3. the trail anchors to the Kalman estimate plus a buffer, so it advances
         on filtered progress and ignores single-bar spikes.
    """

    name = "suite"

    def __init__(self, params: SuiteParams | None = None) -> None:
        self.params = params or SuiteParams()

    # -- geometry -----------------------------------------------------------
    def _raw_stop(self, direction: int, entry: float, stop_anchor: float, ctx: ExitContext) -> float:
        mode = self.params.stop_mode
        if mode == "structure" and ctx.structure_stop is not None:
            buffer = self.params.structure_sl_buffer_atr * ctx.atr
            candidate = ctx.structure_stop - direction * buffer
            # A structure stop on the wrong side of entry is unusable.
            if direction * (entry - candidate) > 0.0:
                return candidate
        if mode == "points":
            return entry - direction * self.params.sl_points
        if mode == "percent":
            return entry * (1.0 - direction * self.params.sl_percent / 100.0)
        # ATR mode, and the fallback for every other mode.
        return entry - direction * self.params.sl_atr_mult * ctx.atr

    def build(self, profile, direction, entry_price, stop_anchor, ctx):
        if ctx.atr <= 0.0:
            return None
        raw = self._raw_stop(direction, entry_price, stop_anchor, ctx)
        stop, risk_unit = self._clamped_stop(direction, entry_price, raw, ctx.atr,
                                             self.params.min_stop_atr, self.params.max_stop_atr)
        if risk_unit <= 0.0:
            return None

        first_target = entry_price + direction * self.params.tp1_atr_mult * ctx.atr

        runner: float | None = None
        if not self.params.trailing_tp2:
            runner = entry_price + direction * self.params.tp2_atr_mult * ctx.atr
            if ctx.structure_target is not None:
                extension = self.params.structure_tp2_extension * abs(ctx.structure_target - entry_price)
                runner = entry_price + direction * extension
        elif self.params.endurance_target:
            # The runner is still unbounded, but the HTF range gives it somewhere
            # to aim: the opposite side of the range is where liquidity sits.
            edge = ctx.htf_high if direction > 0 else ctx.htf_low
            if edge is not None and direction * (edge - entry_price) > risk_unit:
                runner = edge

        return Envelope(stop=stop, risk_unit=risk_unit, first_target=first_target,
                        runner_target=runner, reason=f"suite:{self.params.stop_mode}")

    # -- management ---------------------------------------------------------
    def manage(self, position, bar, ctx, profile):
        params = self.params
        actions: list[ManageAction] = []

        if self._stop_breached(position, bar):
            return [ManageAction(ActionKind.EXIT, position.stop, "stop")]

        if not position.scaled_out and position.target_hit(bar.high, bar.low, position.first_target):
            actions.append(ManageAction(ActionKind.SCALE_OUT, position.first_target,
                                        "tp1", params.scale_out_fraction))
            actions.append(ManageAction(ActionKind.MOVE_STOP, position.entry_price, "breakeven"))

        if position.runner_target is not None and position.target_hit(bar.high, bar.low, position.runner_target):
            actions.append(ManageAction(ActionKind.EXIT, position.runner_target, "endurance-target"))
            return actions

        armed = position.scaled_out or not params.arm_trail_after_tp1
        if armed and params.trail_distance_atr > 0.0:
            candidate = self._trail_level(position, bar, ctx)
            if candidate is not None and position.direction * (candidate - position.stop) > 0.0:
                actions.append(ManageAction(ActionKind.MOVE_STOP, candidate, "kalman-trail"))
        return actions

    def _trail_level(self, position: Position, bar: Bar, ctx: ExitContext) -> float | None:
        """Trail anchored to the filtered price, never to the raw bar extreme."""
        params = self.params
        distance = params.trail_distance_atr * ctx.atr
        if params.tighten_on_ltf_weakness and ctx.ltf_strength < params.ltf_weak_threshold:
            distance *= params.tighten_multiplier

        anchor = ctx.kalman
        if anchor is None:
            # No filter yet: fall back to the bar extreme, i.e. Pulse behaviour.
            anchor = bar.high if position.direction > 0 else bar.low
            buffer = 0.0
        else:
            buffer = params.kalman_trail_buffer_atr * ctx.atr

        return anchor - position.direction * (distance + buffer)


# ---------------------------------------------------------------------------
# 3. Hybrid -- Pulse's entry premise, Suite's endurance
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class HybridParams:
    """The synthesis. Every value here is a deliberate compromise, not a split.

    The raid extreme still defines *where the idea is wrong* -- that is Pulse's
    genuine edge and it is not diluted. What changes is that the stop is no
    longer allowed to be tighter than the tape's own noise floor, and the winner
    is no longer capped by a fixed R multiple.
    """

    stop_buffer_atr: float = 0.35       # beyond the raid extreme, as Pulse
    min_stop_atr: float = 1.6           # noise floor -- the fix for same-bar deaths
    max_stop_atr: float = 4.0           # beyond this the idea is un-sizeable
    first_target_r: float = 1.5         # further than Pulse's 1.0R: pay for the wider stop
    scale_out_fraction: float = 0.40    # bank less, run more
    trail_distance_atr: float = 1.5
    kalman_trail_buffer_atr: float = 0.3
    arm_trail_after_tp1: bool = True
    breakeven_after_tp1: bool = True
    endurance_target: bool = True
    endurance_min_r: float = 2.0        # HTF edge must be worth at least this
    tighten_on_ltf_weakness: bool = True
    ltf_weak_threshold: float = 0.35
    tighten_multiplier: float = 0.55
    structure_stop_preferred: bool = True


class HybridExit(ExitPolicy):
    """Pulse entry geometry, floored stop, Kalman trail, structural endurance."""

    name = "hybrid"

    def __init__(self, params: HybridParams | None = None) -> None:
        self.params = params or HybridParams()

    def build(self, profile, direction, entry_price, stop_anchor, ctx):
        if ctx.atr <= 0.0:
            return None
        params = self.params

        # Start from the raid extreme -- the price that falsifies the premise.
        raw = stop_anchor - direction * params.stop_buffer_atr * ctx.atr

        # If a confirmed swing sits further out on the protective side, respect
        # it: the market has already defended that level once.
        if params.structure_stop_preferred and ctx.structure_stop is not None:
            structural = ctx.structure_stop - direction * params.stop_buffer_atr * ctx.atr
            if direction * (raw - structural) > 0.0 and direction * (entry_price - structural) > 0.0:
                raw = structural

        stop, risk_unit = self._clamped_stop(direction, entry_price, raw, ctx.atr,
                                             params.min_stop_atr, params.max_stop_atr)
        if risk_unit <= 0.0 or direction * (entry_price - stop) <= 0.0:
            return None

        first_target = entry_price + direction * params.first_target_r * risk_unit

        runner: float | None = None
        if params.endurance_target:
            edge = ctx.htf_high if direction > 0 else ctx.htf_low
            if edge is not None and direction * (edge - entry_price) >= params.endurance_min_r * risk_unit:
                runner = edge

        return Envelope(stop=stop, risk_unit=risk_unit, first_target=first_target,
                        runner_target=runner, reason="hybrid:floored-raid-extreme")

    def manage(self, position, bar, ctx, profile):
        params = self.params
        actions: list[ManageAction] = []

        if self._stop_breached(position, bar):
            return [ManageAction(ActionKind.EXIT, position.stop, "stop")]

        if not position.scaled_out and position.target_hit(bar.high, bar.low, position.first_target):
            actions.append(ManageAction(ActionKind.SCALE_OUT, position.first_target,
                                        "tp1", params.scale_out_fraction))
            if params.breakeven_after_tp1:
                actions.append(ManageAction(ActionKind.MOVE_STOP, position.entry_price, "breakeven"))

        if position.runner_target is not None and position.target_hit(bar.high, bar.low, position.runner_target):
            actions.append(ManageAction(ActionKind.EXIT, position.runner_target, "endurance-target"))
            return actions

        armed = position.scaled_out or not params.arm_trail_after_tp1
        if armed and params.trail_distance_atr > 0.0:
            distance = params.trail_distance_atr * ctx.atr
            if params.tighten_on_ltf_weakness and ctx.ltf_strength < params.ltf_weak_threshold:
                distance *= params.tighten_multiplier
            anchor = ctx.kalman
            buffer = params.kalman_trail_buffer_atr * ctx.atr if anchor is not None else 0.0
            if anchor is None:
                anchor = bar.high if position.direction > 0 else bar.low
            candidate = anchor - position.direction * (distance + buffer)
            if position.direction * (candidate - position.stop) > 0.0:
                actions.append(ManageAction(ActionKind.MOVE_STOP, candidate, "kalman-trail"))
        return actions


POLICIES: dict[str, type[ExitPolicy]] = {
    "pulse": PulseExit,
    "suite": SuiteExit,
    "hybrid": HybridExit,
}


def make_policy(name: str) -> ExitPolicy:
    """Instantiate a policy by name (``pulse`` | ``suite`` | ``hybrid``)."""
    try:
        return POLICIES[name]()
    except KeyError:
        raise ValueError(f"unknown exit policy {name!r}; choose from {sorted(POLICIES)}") from None
