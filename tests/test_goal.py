"""The acceptance bar is code, so it gets tests like any other logic.

A goal that can be quietly reinterpreted after seeing results is not a goal.
"""

import pytest

from tools.goal import GOAL, Goal


def result(**kw):
    base = dict(win_rate=85.0, trades=200, trades_per_day=1.5, mean_hold=8.0,
                expectancy=300.0, tp1_rate=20.0, tp2_rate=18.0, tp_gap_pp=2.0,
                runner_legs=0, runner_win_rate=None, consistency=0.6,
                positive_block_rate=75.0, top_decile_share=40.0,
                streak_vs_random=1.2, streak_ratio=3.0, mean_run_ratio=1.8,
                max_winning_streak=9, max_losing_streak=3,
                # Hold time is scored as hard as everything else, so a "clean"
                # result has to describe it: a bounded tail, winners held
                # longer than losers, a stable hold across the run, profit per
                # bar of exposure, and a book that is actually flat overnight.
                hold_p90=18.0, hold_max=24, same_bar_rate=1.0,
                hold_winners=10.0, hold_losers=6.0, hold_asymmetry=1.67,
                hold_drift=0.05, r_per_bar=37.5,
                overnight_rate=0.0, overnight_net_share=0.0,
                intraday_net=60000.0, overnight_net=0.0)
    base.update(kw)
    return base


def test_a_clean_result_clears():
    assert GOAL.clears(result(), result())


# --- TP consistency: the primary criterion ----------------------------------

def test_a_wide_tp_gap_is_rejected_however_good_everything_else_is():
    """TP1 42% / TP2 23% is a TP1-only system carrying TP2's risk for nothing.

    Only meaningful when a runner exists -- with one contract and one target
    there is no second leg to be out of balance with.
    """
    lopsided = result(tp1_rate=41.8, tp2_rate=22.7, tp_gap_pp=19.1, win_rate=95.0,
                      runner_legs=90, runner_win_rate=95.0)
    assert not GOAL.clears(lopsided, lopsided)


def test_a_vestigial_tp_leg_is_rejected():
    vestigial = result(tp2_rate=2.0, tp_gap_pp=18.0, runner_legs=90, runner_win_rate=95.0)
    assert not GOAL.clears(vestigial, vestigial)


def test_balance_must_hold_on_BOTH_tapes():
    """A gap that is tight on one tape and wide on the other is not a property
    of the system, it is a property of that tape."""
    hold = result(tp_gap_pp=2.0, runner_legs=90, runner_win_rate=95.0)
    tune = result(tp_gap_pp=14.0, runner_legs=90, runner_win_rate=95.0)
    assert not GOAL.clears(hold, tune)


def test_gap_drift_between_tapes_is_bounded():
    hold = result(tp_gap_pp=1.0, runner_legs=90, runner_win_rate=95.0)
    tune = result(tp_gap_pp=6.6, runner_legs=90, runner_win_rate=95.0)
    assert not GOAL.clears(hold, tune)


def test_tp_balance_outranks_win_rate_in_the_score():
    """Primary means primary: a tighter gap beats a higher win rate."""
    balanced = result(tp_gap_pp=1.0, win_rate=83.0, runner_legs=90, runner_win_rate=95.0)
    lopsided = result(tp_gap_pp=15.0, win_rate=99.0, runner_legs=90, runner_win_rate=95.0)
    assert GOAL.score(balanced) > GOAL.score(lopsided)


# --- the rest of the bar ----------------------------------------------------

@pytest.mark.parametrize("bad", [
    dict(win_rate=81.9),
    dict(trades=119),
    dict(trades_per_day=0.4),
    dict(trades_per_day=4.1),
    dict(mean_hold=3.9),
    dict(expectancy=0.0),
])
def test_each_threshold_is_actually_enforced(bad):
    assert not GOAL.clears(result(**bad), result(**bad))


def test_win_rate_must_hold_on_the_tuning_tape_too():
    assert not GOAL.clears(result(), result(win_rate=70.0))


def test_an_errored_result_never_clears():
    assert not GOAL.clears({"error": "boom"}, result())


def test_shortfall_names_the_failing_criteria():
    gaps = GOAL.shortfall(result(win_rate=60.0, tp1_rate=40.0, tp2_rate=10.0,
                                 tp_gap_pp=30.0, runner_legs=90, runner_win_rate=52.0))
    joined = " ".join(gaps)
    assert "win" in joined and "TPgap" in joined and "runner win" in joined


def test_thresholds_are_configurable_without_editing_the_logic():
    loose = Goal(max_tp_gap_pp=25.0, min_win_rate=50.0)
    lopsided = result(tp_gap_pp=19.1, win_rate=60.0, runner_legs=90, runner_win_rate=95.0)
    assert loose.clears(lopsided, lopsided)
    assert not GOAL.clears(lopsided, lopsided)


# --- the runner must earn its place -----------------------------------------

def test_single_contract_single_target_needs_no_runner_proof():
    """0 runner legs is the clean case: every trade is binary, nothing partial
    can inflate the win rate, so there is nothing to prove about a runner."""
    clean = result(runner_legs=0, tp2_rate=0.0, tp_gap_pp=0.0, runner_win_rate=None)
    assert GOAL.clears(clean, clean)


def test_a_runner_that_only_wins_half_the_time_is_rejected():
    """A runner at 52% is unpaid risk behind an already-booked TP1 win."""
    weak = result(runner_legs=98, runner_win_rate=52.1)
    assert not GOAL.clears(weak, weak)


def test_a_runner_winning_90_percent_is_allowed_back():
    strong = result(runner_legs=98, runner_win_rate=92.0, tp1_rate=22.0,
                    tp2_rate=20.0, tp_gap_pp=2.0)
    assert GOAL.clears(strong, strong)


def test_a_runner_with_too_few_legs_cannot_be_judged():
    assert not GOAL.clears(result(runner_legs=5, runner_win_rate=100.0),
                           result(runner_legs=5, runner_win_rate=100.0))


# --- consistency and concentration ------------------------------------------

def test_an_inconsistent_edge_is_rejected():
    assert not GOAL.clears(result(consistency=0.05), result(consistency=0.05))


def test_an_edge_carried_by_a_handful_of_trades_is_rejected():
    """Top decile making 72% of net is a lottery ticket that already paid."""
    concentrated = result(top_decile_share=72.0)
    assert not GOAL.clears(concentrated, concentrated)


def test_mostly_losing_blocks_are_rejected():
    assert not GOAL.clears(result(positive_block_rate=40.0),
                           result(positive_block_rate=40.0))


def test_an_abnormal_losing_streak_is_rejected():
    assert not GOAL.clears(result(streak_vs_random=3.5), result(streak_vs_random=3.5))


def test_runner_quality_outranks_everything_in_the_score():
    paying = result(runner_legs=90, runner_win_rate=95.0, win_rate=83.0)
    unpaid = result(runner_legs=90, runner_win_rate=50.0, win_rate=99.0)
    assert GOAL.score(paying) > GOAL.score(unpaid)


# --- streak dominance -------------------------------------------------------

def test_streaks_must_favour_wins():
    """A system whose longest win run barely beats its longest loss run is a
    coin flip with commission."""
    flat = result(streak_ratio=1.1, mean_run_ratio=1.0)
    assert not GOAL.clears(flat, flat)


def test_a_flattering_max_streak_is_caught_by_the_mean():
    """Max ratio passes, mean ratio does not -- one lucky run, not dominance."""
    lucky = result(streak_ratio=4.0, mean_run_ratio=1.05)
    assert not GOAL.clears(lucky, lucky)


def test_genuine_streak_dominance_clears():
    strong = result(streak_ratio=3.0, mean_run_ratio=2.2)
    assert GOAL.clears(strong, strong)


def test_streak_dominance_is_scored():
    dominant = result(streak_ratio=5.0)
    even = result(streak_ratio=1.0)
    assert GOAL.score(dominant) > GOAL.score(even)


# --- hold time ---------------------------------------------------------------
# Each of these is a way a result can look good on every other number and still
# be a system nobody should trade. They exist because real MNQ produced the
# overnight case for real: a configuration reporting a 25.4-bar intraday hold
# was carrying a third of its positions through the halt, and those positions
# were the only reason it made money.

def test_a_swing_hold_wearing_an_intraday_label_is_rejected():
    swing = result(mean_hold=42.0, hold_p90=90.0, hold_max=160)
    assert not GOAL.clears(swing, swing)


def test_a_bounded_mean_with_an_unbounded_tail_is_rejected():
    """The mean can sit inside the cap while the p90 is a different system."""
    fat_tail = result(mean_hold=12.0, hold_p90=96.0, hold_max=210)
    assert not GOAL.clears(fat_tail, fat_tail)


def test_holding_losers_longer_than_winners_is_rejected():
    """The asymmetry that separates riding a trend from hoping one comes back."""
    backwards = result(hold_winners=6.0, hold_losers=11.0, hold_asymmetry=0.55)
    assert not GOAL.clears(backwards, backwards)


def test_same_bar_exits_are_rejected():
    scalp = result(same_bar_rate=31.0)
    assert not GOAL.clears(scalp, scalp)


def test_a_hold_that_drifts_across_the_run_is_rejected():
    drifting = result(hold_drift=0.80)
    assert not GOAL.clears(drifting, drifting)


def test_no_profit_per_bar_of_exposure_is_rejected():
    stalled = result(r_per_bar=0.0)
    assert not GOAL.clears(stalled, stalled)


def test_positions_carried_through_the_halt_are_rejected():
    carried = result(overnight_rate=33.9)
    assert not GOAL.clears(carried, carried)


def test_an_edge_that_is_only_the_overnight_carry_is_rejected():
    """The real failure, in the shape real MNQ produced it.

    A third of positions crossing the halt supplied +$51,567 while the intraday
    book lost $37,080 -- so the carry was 356% of net and the system had no
    intraday edge at all. Overnight rate alone would catch this one, so the
    share is checked with the rate inside its limit to prove it stands alone.
    """
    carry = result(overnight_rate=4.0, overnight_net_share=356.0,
                   intraday_net=-37079.9, overnight_net=51567.4)
    assert not GOAL.clears(carry, carry)


def test_an_overnight_book_that_LOST_is_not_this_failure():
    """A negative share means the intraday book carried the system.

    That is the opposite situation and must not be rejected by a check aimed at
    an edge made of gap risk.
    """
    intraday_carried = result(overnight_rate=3.0, overnight_net_share=-12.0,
                              intraday_net=67000.0, overnight_net=-7000.0)
    assert GOAL.clears(intraday_carried, intraday_carried)


def test_shortfall_names_the_hold_criteria_it_failed():
    bad = result(mean_hold=44.0, hold_p90=99.0, overnight_rate=33.9,
                 overnight_net_share=356.0, hold_asymmetry=0.5,
                 same_bar_rate=20.0, r_per_bar=-1.0, hold_drift=0.9)
    gaps = " | ".join(GOAL.shortfall(bad))
    for token in ("hold 44.0", "hold p90", "same-bar", "asymmetry",
                  "drift", "per-bar", "overnight"):
        assert token in gaps, f"shortfall never mentioned {token!r}: {gaps}"
