"""The acceptance bar is code, so it gets tests like any other logic.

A goal that can be quietly reinterpreted after seeing results is not a goal.
"""

import pytest

from tools.goal import GOAL, Goal


def result(**kw):
    base = dict(win_rate=85.0, trades=200, trades_per_day=1.5, mean_bars=8.0,
                expectancy=300.0, tp1_rate=20.0, tp2_rate=18.0, tp_gap_pp=2.0)
    base.update(kw)
    return base


def test_a_clean_result_clears():
    assert GOAL.clears(result(), result())


# --- TP consistency: the primary criterion ----------------------------------

def test_a_wide_tp_gap_is_rejected_however_good_everything_else_is():
    """TP1 42% / TP2 23% is a TP1-only system carrying TP2's risk for nothing."""
    lopsided = result(tp1_rate=41.8, tp2_rate=22.7, tp_gap_pp=19.1, win_rate=95.0)
    assert not GOAL.clears(lopsided, lopsided)


def test_a_vestigial_tp_leg_is_rejected():
    assert not GOAL.clears(result(tp2_rate=2.0, tp_gap_pp=18.0),
                           result(tp2_rate=2.0, tp_gap_pp=18.0))


def test_balance_must_hold_on_BOTH_tapes():
    """A gap that is tight on one tape and wide on the other is not a property
    of the system, it is a property of that tape."""
    hold = result(tp_gap_pp=2.0)
    tune = result(tp_gap_pp=14.0)
    assert not GOAL.clears(hold, tune)


def test_gap_drift_between_tapes_is_bounded():
    assert not GOAL.clears(result(tp_gap_pp=1.0), result(tp_gap_pp=5.5 + 1.0 + 0.1))


def test_tp_balance_outranks_win_rate_in_the_score():
    """Primary means primary: a tighter gap beats a higher win rate."""
    balanced = result(tp_gap_pp=1.0, win_rate=83.0)
    lopsided = result(tp_gap_pp=15.0, win_rate=99.0)
    assert GOAL.score(balanced) > GOAL.score(lopsided)


# --- the rest of the bar ----------------------------------------------------

@pytest.mark.parametrize("bad", [
    dict(win_rate=81.9),
    dict(trades=119),
    dict(trades_per_day=0.4),
    dict(trades_per_day=4.1),
    dict(mean_bars=3.9),
    dict(expectancy=0.0),
])
def test_each_threshold_is_actually_enforced(bad):
    assert not GOAL.clears(result(**bad), result(**bad))


def test_win_rate_must_hold_on_the_tuning_tape_too():
    assert not GOAL.clears(result(), result(win_rate=70.0))


def test_an_errored_result_never_clears():
    assert not GOAL.clears({"error": "boom"}, result())


def test_shortfall_names_the_failing_criteria():
    gaps = GOAL.shortfall(result(win_rate=60.0, tp1_rate=40.0, tp2_rate=10.0, tp_gap_pp=30.0))
    joined = " ".join(gaps)
    assert "win" in joined and "TPgap" in joined


def test_thresholds_are_configurable_without_editing_the_logic():
    loose = Goal(max_tp_gap_pp=25.0, min_win_rate=50.0)
    lopsided = result(tp_gap_pp=19.1, win_rate=60.0)
    assert loose.clears(lopsided, lopsided)
    assert not GOAL.clears(lopsided, lopsided)
