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

    # --- the runner has to earn its place -----------------------------------
    # Either the system trades ONE contract to ONE target -- every trade a clean
    # binary, nothing partial can inflate the win rate -- or, if a second leg
    # exists, that leg must win 90% of the time on its own. A runner that
    # scratches at breakeven is unpaid risk sitting behind an already-booked
    # win. Breakeven counts as a failure.
    min_runner_win_rate: float = 90.0
    min_runner_legs: int = 30         # below this the runner rate means nothing

    # --- consistency: an edge that is the same edge every month --------------
    # A result carried by a handful of trades is not a system, it is a lottery
    # ticket that already paid. These catch that before it reaches capital.
    min_consistency: float = 0.30       # 1 - coefficient of variation across 25-trade blocks
    min_positive_block_rate: float = 60.0   # % of blocks that made money
    max_top_decile_share: float = 65.0  # % of net profit from the best 10% of trades
    max_streak_vs_random: float = 2.0   # losing streak vs binomial expectation

    # Winning streaks must dominate losing streaks. A system whose longest win
    # run barely exceeds its longest loss run is a coin flip with commission;
    # the equity curve grinds rather than steps, and every drawdown feels
    # terminal because there is no run of wins to pull it back.
    min_streak_ratio: float = 2.0       # max winning streak / max losing streak
    min_mean_run_ratio: float = 1.3     # and on the MEAN run, not just the max

    def clears(self, hold: dict, tune: dict | None = None) -> bool:
        if "error" in hold:
            return False
        ok = (hold.get("win_rate", 0) >= self.min_win_rate
              and hold.get("trades", 0) >= self.min_trades
              and self.min_trades_per_day <= hold.get("trades_per_day", 0) <= self.max_trades_per_day
              and hold.get("mean_hold", 0) >= self.min_hold_bars
              and hold.get("expectancy", 0) > self.min_expectancy)
        if not ok:
            return False

        # Consistency. Checked on held-out data, where it actually counts.
        if (hold.get("consistency", 0.0) < self.min_consistency
                or hold.get("positive_block_rate", 0.0) < self.min_positive_block_rate):
            return False
        share = hold.get("top_decile_share", 0.0)
        if share and share > self.max_top_decile_share:
            return False
        streak = hold.get("streak_vs_random", 0.0)
        if streak and streak > self.max_streak_vs_random:
            return False
        if hold.get("streak_ratio", 0.0) < self.min_streak_ratio:
            return False
        if hold.get("mean_run_ratio", 0.0) < self.min_mean_run_ratio:
            return False

        # The runner must either not exist, or must win on its own merits.
        legs = hold.get("runner_legs", 0)
        if legs == 0:
            pass                              # single-contract, single-target
        else:
            rate = hold.get("runner_win_rate")
            if rate is None or legs < self.min_runner_legs:
                return False
            if rate < self.min_runner_win_rate:
                return False
            # A surviving runner must still be balanced against TP1.
            if (hold.get("tp_gap_pp", 99.0) > self.max_tp_gap_pp
                    or hold.get("tp1_rate", 0.0) < self.min_tp_leg_rate
                    or hold.get("tp2_rate", 0.0) < self.min_tp_leg_rate):
                return False

        if self.require_tune_too and tune is not None:
            if (tune.get("win_rate", 0) < self.min_win_rate
                    or tune.get("expectancy", 0) <= self.min_expectancy):
                return False
            # The balance must be a property of the system, not of one tape.
            if hold.get("runner_legs", 0):
                if tune.get("tp_gap_pp", 99.0) > self.max_tp_gap_pp:
                    return False
                drift = abs(hold.get("tp_gap_pp", 0.0) - tune.get("tp_gap_pp", 0.0))
                if drift > self.max_tp_gap_drift_pp:
                    return False
                if (tune.get("runner_win_rate") or 0.0) < self.min_runner_win_rate:
                    return False
        return True

    def score(self, hold: dict) -> float:
        """Rank among qualifiers: win rate first, then expectancy, then sample."""
        if "error" in hold or not hold.get("trades"):
            return -1e9
        # TP balance dominates the ranking: it is the primary criterion, so a
        # tighter gap outranks a higher win rate.
        # Ranking order mirrors the priority order: a runner that pays, then
        # consistency, then balance, then win rate, then size of edge.
        runner = (hold.get("runner_win_rate") or 100.0) * 1_000_000.0
        streaks = min(hold.get("streak_ratio", 0.0), 8.0) * 200_000.0
        steady = hold.get("consistency", 0.0) * 500_000.0
        balance = max(0.0, 30.0 - hold.get("tp_gap_pp", 30.0)) * 100_000.0
        return (runner + streaks + steady + balance
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
        if hold.get("mean_hold", 0) < self.min_hold_bars:
            gaps.append(f"hold {hold.get('mean_hold',0):.1f}<{self.min_hold_bars}")
        tpd = hold.get("trades_per_day", 0)
        if not (self.min_trades_per_day <= tpd <= self.max_trades_per_day):
            gaps.append(f"tpd {tpd:.2f}")
        if hold.get("expectancy", 0) <= self.min_expectancy:
            gaps.append(f"exp {hold.get('expectancy',0):+.0f}")
        legs = hold.get("runner_legs", 0)
        if legs:
            rate = hold.get("runner_win_rate")
            if rate is None or rate < self.min_runner_win_rate:
                gaps.append(f"runner win {rate if rate is None else round(rate,1)}"
                            f"<{self.min_runner_win_rate} over {legs} legs "
                            f"(BE {hold.get('runner_breakeven_rate', 0):.0f}%)")
            if legs < self.min_runner_legs:
                gaps.append(f"runner legs {legs}<{self.min_runner_legs}")
        ratio = hold.get("streak_ratio", 0.0)
        if ratio < self.min_streak_ratio:
            gaps.append(f"streak ratio {ratio:.2f}<{self.min_streak_ratio} "
                        f"(win {hold.get('max_winning_streak',0)} vs "
                        f"lose {hold.get('max_losing_streak',0)})")
        mrr = hold.get("mean_run_ratio", 0.0)
        if mrr < self.min_mean_run_ratio:
            gaps.append(f"mean run ratio {mrr:.2f}<{self.min_mean_run_ratio}")
        if hold.get("consistency", 0.0) < self.min_consistency:
            gaps.append(f"consistency {hold.get('consistency',0):.2f}<{self.min_consistency}")
        if hold.get("positive_block_rate", 0.0) < self.min_positive_block_rate:
            gaps.append(f"positive blocks {hold.get('positive_block_rate',0):.0f}%")
        share = hold.get("top_decile_share", 0.0)
        if share and share > self.max_top_decile_share:
            gaps.append(f"top-decile share {share:.0f}%>{self.max_top_decile_share:.0f}%")
        gap = hold.get("tp_gap_pp")
        if legs and gap is not None and gap > self.max_tp_gap_pp:
            gaps.append(f"TPgap {gap:.1f}pp>{self.max_tp_gap_pp} "
                        f"(TP1 {hold.get('tp1_rate',0):.1f}% vs TP2 {hold.get('tp2_rate',0):.1f}%)")
        for leg in ("tp1_rate", "tp2_rate"):
            if hold.get(leg, 0.0) < self.min_tp_leg_rate:
                gaps.append(f"{leg} {hold.get(leg,0):.1f}%<{self.min_tp_leg_rate}")
        return gaps


GOAL = Goal()
TARGET_COUNT = 5        # "more than 5" -- the search does not stop at the first
