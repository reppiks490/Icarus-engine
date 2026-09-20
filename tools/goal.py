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

    # --- TP consistency: the primary criterion -------------------------------
    # The two take-profit legs must fill at comparable rates. A configuration
    # where TP1 fills 42% and TP2 22% is a TP1-only system carrying TP2's risk
    # for nothing -- the runner almost never pays. "Can vary slightly" is read
    # as a few percentage points, not a factor of two.
    max_tp_gap_pp: float = 6.0      # |TP1% - TP2%| on held-out data
    min_tp_leg_rate: float = 8.0    # neither leg may be vestigial
    max_tp_gap_drift_pp: float = 5.0  # and the gap must hold across BOTH tapes

    def clears(self, hold: dict, tune: dict | None = None) -> bool:
        if "error" in hold:
            return False
        ok = (hold.get("win_rate", 0) >= self.min_win_rate
              and hold.get("trades", 0) >= self.min_trades
              and self.min_trades_per_day <= hold.get("trades_per_day", 0) <= self.max_trades_per_day
              and hold.get("mean_bars", 0) >= self.min_hold_bars
              and hold.get("expectancy", 0) > self.min_expectancy)
        if not ok:
            return False

        # TP consistency, evaluated on held-out data.
        if (hold.get("tp_gap_pp", 99.0) > self.max_tp_gap_pp
                or hold.get("tp1_rate", 0.0) < self.min_tp_leg_rate
                or hold.get("tp2_rate", 0.0) < self.min_tp_leg_rate):
            return False

        if self.require_tune_too and tune is not None:
            if (tune.get("win_rate", 0) < self.min_win_rate
                    or tune.get("expectancy", 0) <= self.min_expectancy):
                return False
            # The balance must be a property of the system, not of one tape.
            if tune.get("tp_gap_pp", 99.0) > self.max_tp_gap_pp:
                return False
            drift = abs(hold.get("tp_gap_pp", 0.0) - tune.get("tp_gap_pp", 0.0))
            if drift > self.max_tp_gap_drift_pp:
                return False
        return True

    def score(self, hold: dict) -> float:
        """Rank among qualifiers: win rate first, then expectancy, then sample."""
        if "error" in hold or not hold.get("trades"):
            return -1e9
        # TP balance dominates the ranking: it is the primary criterion, so a
        # tighter gap outranks a higher win rate.
        balance = max(0.0, 30.0 - hold.get("tp_gap_pp", 30.0)) * 100_000.0
        return (balance
                + hold["win_rate"] * 1000.0
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
        gap = hold.get("tp_gap_pp")
        if gap is not None and gap > self.max_tp_gap_pp:
            gaps.append(f"TPgap {gap:.1f}pp>{self.max_tp_gap_pp} "
                        f"(TP1 {hold.get('tp1_rate',0):.1f}% vs TP2 {hold.get('tp2_rate',0):.1f}%)")
        for leg in ("tp1_rate", "tp2_rate"):
            if hold.get(leg, 0.0) < self.min_tp_leg_rate:
                gaps.append(f"{leg} {hold.get(leg,0):.1f}%<{self.min_tp_leg_rate}")
        return gaps


GOAL = Goal()
TARGET_COUNT = 5        # "more than 5" -- the search does not stop at the first
