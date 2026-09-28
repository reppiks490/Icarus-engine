"""Risk: the layer that keeps the engine alive long enough for the edge to pay.

Three independent brakes, each able to stand the system down on its own:
  1. **Per-trade risk** -- fixed fractional on the real stop distance, so size
     collapses automatically when volatility widens the stop.
  2. **Session loss limit** -- a hard stop in R for the day. Not a suggestion.
  3. **Consecutive-loss throttle** -- risk is halved after a losing streak and
     restored on the next win. The tape is telling you the regime changed;
     size down before you find out how far.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from icarus.config import Profile


@dataclass(frozen=True, slots=True)
class SizingResult:
    size: float
    risk_amount: float
    risk_fraction: float
    stop_distance: float
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.size > 0.0


class RiskManager:
    """Position sizing and the session-level circuit breakers."""

    __slots__ = ("profile", "_daily_r", "_consecutive_losses", "_session_key",
                 "_cooldown_until_index", "_halted_reason")

    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self._daily_r = 0.0
        self._consecutive_losses = 0
        self._session_key: object | None = None
        self._cooldown_until_index = -1
        self._halted_reason = ""

    # ------------------------------------------------------------------
    def roll_session(self, session_key: object) -> None:
        """Reset the daily budget. Streak state deliberately survives the roll."""
        self._session_key = session_key
        self._daily_r = 0.0
        self._halted_reason = ""

    def register_exit(self, r_multiple: float, bar_index: int) -> None:
        """Book a closed trade against the daily budget and the streak counter."""
        self._daily_r += r_multiple
        if r_multiple < 0.0:
            self._consecutive_losses += 1
        elif r_multiple > 0.0:
            self._consecutive_losses = 0
        self._cooldown_until_index = bar_index + self.profile.cooldown_bars_after_exit
        if self._daily_r <= -abs(self.profile.daily_loss_limit_r):
            self._halted_reason = f"daily-loss-limit {self._daily_r:.2f}R"

    # ------------------------------------------------------------------
    @property
    def risk_fraction(self) -> float:
        """Current per-trade risk, after the losing-streak throttle."""
        fraction = self.profile.risk_per_trade
        if self._consecutive_losses >= self.profile.consecutive_loss_throttle:
            fraction *= 0.5
        return min(fraction, self.profile.max_risk_per_trade)

    @property
    def halted(self) -> bool:
        return bool(self._halted_reason)

    @property
    def halt_reason(self) -> str:
        return self._halted_reason

    @property
    def daily_r(self) -> float:
        return self._daily_r

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    def in_cooldown(self, bar_index: int) -> bool:
        return bar_index < self._cooldown_until_index

    # ------------------------------------------------------------------
    def size_for(
        self,
        equity: float,
        entry_price: float,
        stop_price: float,
        bar_index: int,
        point_value: float = 1.0,
    ) -> SizingResult:
        """Fixed-fractional size on the actual stop distance.

        ``point_value`` is the currency earned per 1.0 price unit per contract,
        so a micro contract sizes correctly without the engine knowing what a
        micro contract is.
        """
        stop_distance = abs(entry_price - stop_price)
        if self._halted_reason:
            return SizingResult(0.0, 0.0, 0.0, stop_distance, self._halted_reason)
        if self.in_cooldown(bar_index):
            return SizingResult(0.0, 0.0, 0.0, stop_distance, "cooldown")
        if stop_distance <= 0.0:
            return SizingResult(0.0, 0.0, 0.0, 0.0, "degenerate-stop")
        if equity <= 0.0:
            return SizingResult(0.0, 0.0, 0.0, stop_distance, "no-equity")

        if point_value <= 0.0:
            raise ValueError("point_value must be > 0")
        fraction = self.risk_fraction
        risk_amount = equity * fraction
        size = risk_amount / (stop_distance * point_value)
        if size <= 0.0:
            return SizingResult(0.0, 0.0, fraction, stop_distance, "size-rounds-to-zero")
        return SizingResult(size=size, risk_amount=risk_amount,
                            risk_fraction=fraction, stop_distance=stop_distance)


def build_risk_envelope(
    profile: Profile,
    direction: int,
    entry_price: float,
    stop_anchor: float,
    atr: float,
) -> tuple[float, float, float, float]:
    """Return (stop, risk_unit, first_target, runner_target).

    The stop is parked beyond the raid's extreme, not at a round number and not
    at a fixed ATR distance from entry: the raid extreme is the price at which
    the trade's premise is factually wrong.
    """
    buffer = profile.stop_buffer_atr * atr
    stop = stop_anchor - direction * buffer
    risk_unit = abs(entry_price - stop)
    if risk_unit <= 0.0:
        # Degenerate geometry (entry printed through the anchor): fall back to
        # a pure ATR stop so the trade is either sized sanely or rejected.
        risk_unit = max(atr * profile.stop_buffer_atr, 1e-9)
        stop = entry_price - direction * risk_unit
    first_target = entry_price + direction * profile.first_target_r * risk_unit
    runner_target = entry_price + direction * profile.runner_target_r * risk_unit
    return stop, risk_unit, first_target, runner_target
