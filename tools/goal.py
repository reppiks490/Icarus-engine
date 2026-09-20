"""The acceptance bar. A variant either clears it on HELD-OUT data or it does not.

Stated as code so no result can be talked into qualifying. Every threshold here
was set by the operator, not inferred from a run that happened to produce it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Goal:
    min_win_rate: float = 82.0      # percent, on held-out data
    min_trades: float = 120.0       # "large quantity" -- enough to mean something
    min_trades_per_day: float = 0.5
    max_trades_per_day: float = 4.0
    min_hold_bars: float = 4.0      # "nice hold time" -- not a same-bar scalp
    min_expectancy: float = 0.0     # must actually make money
    require_tune_too: bool = True   # must clear win rate on BOTH tapes, not just one

    def clears(self, hold: dict, tune: dict | None = None) -> bool:
        if "error" in hold:
            return False
        ok = (hold.get("win_rate", 0) >= self.min_win_rate
              and hold.get("trades", 0) >= self.min_trades
              and self.min_trades_per_day <= hold.get("trades_per_day", 0) <= self.max_trades_per_day
              and hold.get("mean_bars", 0) >= self.min_hold_bars
              and hold.get("expectancy", 0) > self.min_expectancy)
        if ok and self.require_tune_too and tune is not None:
            ok = (tune.get("win_rate", 0) >= self.min_win_rate
                  and tune.get("expectancy", 0) > self.min_expectancy)
        return ok

    def score(self, hold: dict) -> float:
        """Rank among qualifiers: win rate first, then expectancy, then sample."""
        if "error" in hold or not hold.get("trades"):
            return -1e9
        return (hold["win_rate"] * 1000.0
                + min(hold["expectancy"], 5000.0) * 0.1
                + min(hold["trades"], 1000.0) * 0.01)

    def shortfall(self, hold: dict) -> list[str]:
        """Exactly which criteria a near-miss failed. Used to steer the search."""
        gaps = []
        if hold.get("win_rate", 0) < self.min_win_rate:
            gaps.append(f"win {hold.get('win_rate',0):.1f}<{self.min_win_rate}")
        if hold.get("trades", 0) < self.min_trades:
            gaps.append(f"n {hold.get('trades',0)}<{self.min_trades:.0f}")
        if hold.get("mean_bars", 0) < self.min_hold_bars:
            gaps.append(f"hold {hold.get('mean_bars',0):.1f}<{self.min_hold_bars}")
        tpd = hold.get("trades_per_day", 0)
        if not (self.min_trades_per_day <= tpd <= self.max_trades_per_day):
            gaps.append(f"tpd {tpd:.2f}")
        if hold.get("expectancy", 0) <= self.min_expectancy:
            gaps.append(f"exp {hold.get('expectancy',0):+.0f}")
        return gaps


GOAL = Goal()
TARGET_COUNT = 5        # "more than 5" -- the search does not stop at the first
