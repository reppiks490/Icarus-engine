"""IcarusEngine -- the master system.

One premise, executed the same way on every venue:

    A known pool of resting liquidity is raided, the raid fails, and the order
    flow that absorbed it confirms the failure while structure breaks back the
    other way -- inside a volatility regime worth paying the spread for.

The engine is strictly causal. A decision made on bar *t* can only be filled on
bar *t+1*'s open; nothing reads a price it has not already been handed. That
rule is enforced here, in ``on_bar``, not left to the backtester's good manners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from icarus.config import AssetClass, Profile, profile_for
from icarus.data import Bar
from icarus.execution import (
    Blotter, IntentKind, Position, Trade, TradeIntent,
    apply_entry_cost, apply_exit_cost, commission,
)
from icarus.features.liquidity import LiquidityMap
from icarus.features.orderflow import OrderFlowEngine
from icarus.features.sentiment import SentimentOverlay
from icarus.features.structure import MarketStructure
from icarus.features.volatility import VolatilityEngine
from icarus.filters import AdaptiveKalman, FractalDimensionIndex
from icarus.exits import (
    ActionKind, ExitContext, ExitPolicy, HTFRange, ManageAction, make_policy,
)
from icarus.timeframe import at_timeframe, htf_bars
from icarus.indicators import RSI, SessionVWAP
from icarus.ml import MLGate
from icarus.risk import RiskManager
from icarus.signal import ConfluenceEngine, Signal

try:                                    # tz database is present on any sane host
    from zoneinfo import ZoneInfo
except ImportError:                     # pragma: no cover - stdlib since 3.9
    ZoneInfo = None                     # type: ignore[assignment]


@dataclass(slots=True)
class _PendingEntry:
    """An entry decided on the previous close, awaiting the next open."""

    direction: int
    stop_anchor: float
    atr: float
    score: float
    reason: str


@dataclass(slots=True)
class EngineState:
    """Everything an operator needs to see at a glance."""

    ts: datetime | None = None
    price: float = 0.0
    in_session: bool = False
    session_key: object | None = None
    signal: Signal | None = None
    position: Position | None = None
    equity: float = 0.0
    bar_index: int = -1
    last_veto: str = ""
    intents: list[TradeIntent] = field(default_factory=list)


class IcarusEngine:
    """The single, cohesive intraday system."""

    def __init__(
        self,
        profile: Profile | AssetClass | str = AssetClass.FUTURES,
        starting_equity: float = 100_000.0,
        sentiment: SentimentOverlay | None = None,
        on_trade: Callable[[Trade], None] | None = None,
        exit_policy: str | ExitPolicy | None = None,
        ml: MLGate | None = None,
        timeframe: str | int | None = None,
        htf: str | int = "4h",
    ) -> None:
        """Build the engine.

        ``exit_policy`` overrides the profile's choice (``pulse`` | ``suite`` |
        ``hybrid``). ``timeframe`` rescales every bar-count parameter onto a
        different chart size. ``htf`` sets the higher-timeframe window whose
        opposite edge becomes the endurance target.
        """
        base = profile if isinstance(profile, Profile) else profile_for(profile)
        self.profile = at_timeframe(base, timeframe) if timeframe is not None else base
        profile_ = self.profile

        self.volatility = VolatilityEngine(
            atr_period=profile_.atr_period,
            regime_lookback=profile_.atr_regime_lookback,
            min_percentile=profile_.min_atr_percentile,
            max_percentile=profile_.max_atr_percentile,
            min_atr_to_cost_ratio=profile_.min_atr_to_cost_ratio,
        )
        self.order_flow = OrderFlowEngine(
            fast=profile_.cvd_fast, slow=profile_.cvd_slow,
            absorption_lookback=profile_.absorption_lookback,
        )
        self.structure = MarketStructure(profile_.swing_strength, profile_.structure_lookback)
        self.liquidity = LiquidityMap(
            tolerance_atr=profile_.equal_level_tolerance_atr,
            min_penetration_atr=profile_.sweep_min_penetration_atr,
            max_penetration_atr=profile_.sweep_max_penetration_atr,
            reclaim_bars=profile_.sweep_reclaim_bars,
        )
        self.vwap = SessionVWAP()
        self.rsi = RSI(14)
        self.sentiment = sentiment or SentimentOverlay()
        # Inert unless a model is attached AND the profile gives `ml` weight.
        self.ml = ml if ml is not None else MLGate()
        self.confluence = ConfluenceEngine(profile_.weights, min_score=profile_.min_confluence)
        self.risk = RiskManager(profile_)
        self.blotter = Blotter(starting_equity=starting_equity)

        # --- exit layer: policy, filters, higher-timeframe context ---------
        if isinstance(exit_policy, ExitPolicy):
            self.exit_policy = exit_policy
        else:
            self.exit_policy = make_policy(exit_policy or profile_.exit_policy)
        self.fdi = FractalDimensionIndex(
            length=max(10, min(60, profile_.atr_period + 5)), ema_smooth=5
        )
        self.kalman = AdaptiveKalman()
        self.htf = HTFRange(htf_bars(profile_.base_timeframe_min, htf))

        self._tz = ZoneInfo(profile_.timezone) if ZoneInfo is not None else None
        self._pending: _PendingEntry | None = None
        self._position: Position | None = None
        self._last_flow = None          # most recent OrderFlowState, for the exit context
        self._session_key: object | None = None
        self._bar_index = -1
        self._on_trade = on_trade
        self.state = EngineState(equity=starting_equity)

    # ------------------------------------------------------------------
    # Session handling
    # ------------------------------------------------------------------
    def _local(self, ts: datetime) -> datetime:
        return ts.astimezone(self._tz) if self._tz is not None else ts

    def _session_id(self, ts: datetime) -> date:
        """The trading date this bar belongs to, in the profile's timezone."""
        return self._local(ts).date()

    def in_session(self, ts: datetime) -> bool:
        """True when the profile permits trading at this moment."""
        if not self.profile.sessions:
            return True                                 # 24/7 venues
        moment = self._local(ts).time()
        return any(window.contains(moment) for window in self.profile.sessions)

    def _must_flatten(self, ts: datetime) -> bool:
        """True inside the forced-flatten buffer before a session window closes."""
        if not self.profile.sessions or self.profile.flat_before_session_end_min <= 0:
            return False
        local = self._local(ts)
        for window in self.profile.sessions:
            if not window.contains(local.time()):
                continue
            end = local.replace(hour=window.end.hour, minute=window.end.minute,
                                second=0, microsecond=0)
            if window.start > window.end and local.time() >= window.start:
                end += timedelta(days=1)                # window wrapped midnight
            if (end - local) <= timedelta(minutes=self.profile.flat_before_session_end_min):
                return True
        return False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def on_bar(self, bar: Bar) -> list[TradeIntent]:
        """Process one completed bar. Returns the intents raised by it."""
        self._bar_index += 1
        intents: list[TradeIntent] = []

        # 1. Session roll -- re-anchor everything that is session-scoped.
        session_key = self._session_id(bar.ts)
        if session_key != self._session_key:
            if self._position is not None:
                intents.append(self._close_position(bar, bar.open, "session-roll"))
            self._session_key = session_key
            self.liquidity.roll_session(bar)
            self.vwap.reset()
            self.order_flow.reset_session()
            self.risk.roll_session(session_key)
            self._pending = None

        # 2. Fill anything decided on the previous close, at THIS bar's open.
        if self._pending is not None:
            intent = self._open_position(bar, self._pending)
            self._pending = None
            if intent is not None:
                intents.append(intent)

        # 3. Feature updates (order matters: volatility feeds liquidity's ATR).
        round_turn_cost = 2.0 * self.profile.costs.entry_cost(self.volatility.state.percentile)
        volatility = self.volatility.update(bar, round_turn_cost)
        flow = self.order_flow.update(bar)
        self.structure.update(bar)
        # Pivots confirmed by this bar become tomorrow's stop clusters.
        self.liquidity.ingest_swings(self.structure.last_swings)
        self.vwap.update(bar.typical, bar.volume)
        rsi = self.rsi.update(bar.close)
        sweep = self.liquidity.update(bar, volatility.atr)

        # Filters that feed the exit layer. The Kalman estimate is what the
        # trail rides; the raw bar extreme is what it must never ride.
        self.fdi.update(bar.high, bar.low)
        self.kalman.update(bar.close, volatility.atr, self.fdi.choppiness)
        self.htf.update(bar)
        self._last_flow = flow

        # 4. Manage the live position against this bar's real extremes.
        if self._position is not None:
            intents.extend(self._manage_position(bar, volatility.percentile))

        # 5. Look for the next shot only when genuinely flat.
        signal: Signal | None = None
        session_open = self.in_session(bar.ts) and not self._must_flatten(bar.ts)
        if self._position is None and self._pending is None:
            signal = self.confluence.evaluate(
                ts=bar.ts, price=bar.close, sweep=sweep, volatility=volatility,
                order_flow=flow, structure=self.structure, liquidity=self.liquidity,
                vwap=self.vwap, sentiment=self.sentiment, rsi=rsi, session_open=session_open,
                ml=self.ml,
            )
            if signal.actionable and not self.risk.halted and not self.risk.in_cooldown(self._bar_index):
                self._pending = _PendingEntry(
                    direction=signal.direction,
                    stop_anchor=signal.stop_anchor,
                    atr=volatility.atr,
                    score=signal.score,
                    reason=self._describe(signal),
                )

        self.state = EngineState(
            ts=bar.ts, price=bar.close, in_session=session_open, session_key=session_key,
            signal=signal, position=self._position, equity=self.blotter.equity,
            bar_index=self._bar_index,
            last_veto=signal.veto if signal is not None else self.state.last_veto,
            intents=intents,
        )
        return intents

    # ------------------------------------------------------------------
    # Exit context
    # ------------------------------------------------------------------
    def _exit_context(self, direction: int, price: float, atr: float) -> ExitContext:
        """Snapshot everything the exit policy is allowed to see.

        ``ltf_strength`` stands in for the Suite's 2m/5m signal-failure read:
        with no second data feed in the core, order-flow pressure in the trade's
        own direction is the honest proxy, and it is labelled as one.
        """
        flow = self._last_flow
        strength = flow.pressure(direction) if flow is not None else 1.0
        return ExitContext(
            atr=atr,
            atr_percentile=self.volatility.state.percentile,
            bar_index=self._bar_index,
            kalman=self.kalman.estimate,
            choppiness=self.fdi.choppiness,
            structure_stop=self.structure.protective_level(direction, price),
            structure_target=self.structure.objective_level(direction, price),
            htf_high=self.htf.high,
            htf_low=self.htf.low,
            ltf_strength=strength,
        )

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------
    def _open_position(self, bar: Bar, pending: _PendingEntry) -> TradeIntent | None:
        """Fill the pending entry at this bar's open, after costs."""
        entry = apply_entry_cost(bar.open, pending.direction, self.profile.costs,
                                 self.volatility.state.percentile)
        ctx = self._exit_context(pending.direction, entry, pending.atr)
        envelope = self.exit_policy.build(self.profile, pending.direction, entry,
                                          pending.stop_anchor, ctx)
        if envelope is None:
            return None
        # The gap through our own stop invalidates the premise before we are in it.
        if pending.direction * (entry - envelope.stop) <= 0.0:
            return None

        sizing = self.risk.size_for(self.blotter.equity, entry, envelope.stop,
                                    self._bar_index, self.profile.point_value)
        if not sizing.allowed:
            return None

        self._position = Position(
            direction=pending.direction, size=sizing.size, entry_price=entry,
            entry_ts=bar.ts, entry_index=self._bar_index, stop=envelope.stop,
            risk_unit=envelope.risk_unit, first_target=envelope.first_target,
            runner_target=envelope.runner_target,
            initial_size=sizing.size, score=pending.score,
            reason=f"{pending.reason} exit={envelope.reason}",
        )
        self.blotter.mark(bar.ts, -commission(sizing.size, self.profile.costs))
        return TradeIntent(IntentKind.ENTER, bar.ts, pending.direction, sizing.size,
                           entry, pending.reason, pending.score)

    def _manage_position(self, bar: Bar, atr_percentile: float) -> list[TradeIntent]:
        """Execute the exit policy's instructions for this bar.

        The engine owns fills, costs and the blotter; the policy owns *when*.
        Policies emit worst case first, so a stop that shares a bar with a
        target is always taken as the stop.
        """
        position = self._position
        assert position is not None
        intents: list[TradeIntent] = []
        position.track_excursion(bar.high, bar.low)

        ctx = self._exit_context(position.direction, bar.close, self.volatility.state.atr)
        for action in self.exit_policy.manage(position, bar, ctx, self.profile):
            if action.kind is ActionKind.EXIT:
                intents.append(self._close_position(bar, action.price, action.reason))
                return intents

            if action.kind is ActionKind.SCALE_OUT:
                if position.scaled_out or action.fraction <= 0.0:
                    continue
                intents.append(self._scale_out(bar, action, atr_percentile))
                if position.size <= 0.0:
                    return intents

            elif action.kind is ActionKind.MOVE_STOP:
                # A stop may only ever move in the trade's favour.
                if position.direction * (action.price - position.stop) > 0.0:
                    position.stop = action.price
                    if action.reason == "breakeven":
                        position.breakeven_moved = True
                    intents.append(TradeIntent(IntentKind.MOVE_STOP, bar.ts, position.direction,
                                               0.0, action.price, action.reason, position.score))

        # Time stop: an idea that has not worked is an idea that was wrong.
        held = self._bar_index - position.entry_index
        if held >= self.profile.time_stop_bars and position.r_multiple(bar.close) < 0.5:
            intents.append(self._close_position(bar, bar.close, "time-stop"))
            return intents

        # Session close: never carry intraday risk past the window.
        if self._must_flatten(bar.ts):
            intents.append(self._close_position(bar, bar.close, "session-flatten"))
        return intents

    def _scale_out(self, bar: Bar, action: "ManageAction", atr_percentile: float) -> TradeIntent:
        """Bank part of the position at the policy's level."""
        position = self._position
        assert position is not None
        scale_size = position.size * action.fraction
        fill = apply_exit_cost(action.price, position.direction, self.profile.costs, atr_percentile)
        realised = position.direction * (fill - position.entry_price) * scale_size * self.profile.point_value
        realised -= commission(scale_size, self.profile.costs)
        position.realised += realised
        position.size -= scale_size
        position.scaled_out = True
        self.blotter.mark(bar.ts, realised)
        return TradeIntent(IntentKind.SCALE_OUT, bar.ts, position.direction, scale_size,
                           fill, action.reason, position.score)

    def _close_position(self, bar: Bar, price: float, reason: str) -> TradeIntent:
        """Flatten the remaining size and book the trade."""
        position = self._position
        assert position is not None
        fill = apply_exit_cost(price, position.direction, self.profile.costs,
                               self.volatility.state.percentile)
        realised = position.direction * (fill - position.entry_price) * position.size * self.profile.point_value
        realised -= commission(position.size, self.profile.costs)
        self.blotter.mark(bar.ts, realised)

        total = position.realised + realised
        risk_at_entry = position.risk_unit * position.initial_size * self.profile.point_value
        r_multiple = total / risk_at_entry if risk_at_entry > 0 else 0.0

        trade = Trade(
            direction=position.direction, entry_ts=position.entry_ts, exit_ts=bar.ts,
            entry_price=position.entry_price, exit_price=fill, size=position.initial_size,
            pnl=total, r=r_multiple, bars_held=self._bar_index - position.entry_index,
            score=position.score, reason_in=position.reason, reason_out=reason,
            mae_r=position.max_adverse, mfe_r=position.max_favourable,
        )
        self.blotter.record(trade)
        self.risk.register_exit(r_multiple, self._bar_index)
        if self._on_trade is not None:
            self._on_trade(trade)

        intent = TradeIntent(IntentKind.EXIT, bar.ts, position.direction, position.size,
                             fill, reason, position.score)
        self._position = None
        return intent

    # ------------------------------------------------------------------
    @staticmethod
    def _describe(signal: Signal) -> str:
        """Compact, human-auditable reason string for the blotter."""
        sweep = signal.sweep
        parts = [
            "long" if signal.direction > 0 else "short",
            f"sweep={sweep.pool.kind.value}" if sweep else "sweep=?",
            f"pen={sweep.penetration_atr:.2f}atr" if sweep else "",
            f"score={signal.score:.3f}",
        ]
        top = sorted(signal.components.items(), key=lambda item: item[1], reverse=True)[:3]
        parts.extend(f"{name}={value:.2f}" for name, value in top)
        return " ".join(part for part in parts if part)

    @property
    def position(self) -> Position | None:
        return self._position

    @property
    def equity(self) -> float:
        return self.blotter.equity
