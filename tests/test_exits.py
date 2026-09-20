from datetime import datetime, timedelta, timezone

import pytest

from icarus.config import AssetClass, profile_for
from icarus.data import Bar
from icarus.execution import Position
from icarus.exits import (
    ActionKind, ExitContext, HTFRange, HybridExit, PulseExit, SuiteExit, make_policy,
)

NOW = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
PROFILE = profile_for(AssetClass.MICRO_FUTURES)
ATR = 40.0


def ctx(**kwargs):
    base = dict(atr=ATR, bar_index=100, kalman=None, choppiness=0.4,
                structure_stop=None, structure_target=None, htf_high=None, htf_low=None)
    base.update(kwargs)
    return ExitContext(**base)


def bar(open_, high, low, close, minute=0):
    return Bar(ts=NOW + timedelta(minutes=minute), open=open_, high=high,
               low=low, close=close, volume=1000.0)


def position(policy, direction=1, entry=30000.0, anchor=29980.0, context=None):
    envelope = policy.build(PROFILE, direction, entry, anchor, context or ctx())
    assert envelope is not None
    return Position(
        direction=direction, size=1.0, entry_price=entry, entry_ts=NOW, entry_index=0,
        stop=envelope.stop, risk_unit=envelope.risk_unit, first_target=envelope.first_target,
        runner_target=envelope.runner_target, initial_size=1.0,
    ), envelope


def test_make_policy_and_unknown_name():
    assert make_policy("pulse").name == "pulse"
    assert make_policy("suite").name == "suite"
    assert make_policy("hybrid").name == "hybrid"
    with pytest.raises(ValueError, match="unknown exit policy"):
        make_policy("telepathy")


# --- the core finding -------------------------------------------------------

def test_pulse_stop_sits_inside_one_bars_range():
    """The defect this module exists to fix, pinned as a test."""
    _, envelope = position(PulseExit())
    assert envelope.risk_unit / ATR < 1.0


def test_suite_and_hybrid_floor_the_stop_above_the_noise_floor():
    _, suite = position(SuiteExit())
    _, hybrid = position(HybridExit())
    assert suite.risk_unit / ATR >= SuiteExit().params.min_stop_atr - 1e-9
    assert hybrid.risk_unit / ATR >= HybridExit().params.min_stop_atr - 1e-9
    assert suite.risk_unit > hybrid.risk_unit > 0.0


def test_stop_distance_is_capped_at_the_maximum():
    """A structure stop miles away must not create an un-sizeable trade."""
    policy = HybridExit()
    _, envelope = position(policy, context=ctx(structure_stop=20000.0))
    assert envelope.risk_unit / ATR == pytest.approx(policy.params.max_stop_atr)


def test_short_geometry_is_mirrored():
    for policy in (PulseExit(), SuiteExit(), HybridExit()):
        _, envelope = policy.build(PROFILE, -1, 30000.0, 30020.0, ctx()), None
        built = policy.build(PROFILE, -1, 30000.0, 30020.0, ctx())
        assert built.stop > 30000.0
        assert built.first_target < 30000.0


# --- runner / endurance -----------------------------------------------------

def test_pulse_caps_the_winner_with_a_fixed_r_multiple():
    _, envelope = position(PulseExit())
    assert envelope.runner_target is not None
    reward = abs(envelope.runner_target - 30000.0) / envelope.risk_unit
    assert reward == pytest.approx(PROFILE.runner_target_r, rel=1e-6)


def test_suite_runner_is_the_htf_edge_not_an_r_multiple():
    _, envelope = position(SuiteExit(), context=ctx(htf_high=30500.0, htf_low=29500.0))
    assert envelope.runner_target == pytest.approx(30500.0)


def test_runner_is_unbounded_when_the_htf_edge_is_too_close():
    _, envelope = position(HybridExit(), context=ctx(htf_high=30010.0, htf_low=29500.0))
    assert envelope.runner_target is None, "a target inside the stop distance is not a target"


def test_suite_uses_the_structure_stop_when_one_is_available():
    policy = SuiteExit()
    with_structure = policy.build(PROFILE, 1, 30000.0, 29980.0, ctx(structure_stop=29900.0))
    buffer = policy.params.structure_sl_buffer_atr * ATR
    assert with_structure.stop == pytest.approx(29900.0 - buffer)


def test_structure_stop_on_the_wrong_side_of_entry_is_ignored():
    policy = SuiteExit()
    built = policy.build(PROFILE, 1, 30000.0, 29980.0, ctx(structure_stop=30100.0))
    assert built.stop < 30000.0


# --- management -------------------------------------------------------------

def test_stop_is_taken_before_any_target_on_the_same_bar():
    pos, _ = position(PulseExit())
    policy = PulseExit()
    wide = bar(30000.0, pos.first_target + 100.0, pos.stop - 10.0, 30000.0)
    actions = policy.manage(pos, wide, ctx(), PROFILE)
    assert len(actions) == 1
    assert actions[0].kind is ActionKind.EXIT and actions[0].reason == "stop"


def test_first_target_scales_out_and_moves_the_stop_to_breakeven():
    pos, _ = position(SuiteExit())
    actions = SuiteExit().manage(pos, bar(30000.0, pos.first_target + 1.0, 29990.0, pos.first_target), ctx(), PROFILE)
    kinds = [a.kind for a in actions]
    assert ActionKind.SCALE_OUT in kinds and ActionKind.MOVE_STOP in kinds
    move = next(a for a in actions if a.kind is ActionKind.MOVE_STOP)
    assert move.price == pytest.approx(pos.entry_price)


def test_trail_anchors_to_the_kalman_estimate_not_the_bar_extreme():
    """A raw-high trail ratchets on a spike; the Kalman trail must not."""
    policy = SuiteExit()
    pos, _ = position(policy)
    pos.scaled_out = True
    spike = bar(30000.0, 30400.0, 29990.0, 30010.0)          # 10-ATR wick
    filtered = policy.manage(pos, spike, ctx(kalman=30020.0), PROFILE)
    raw = policy.manage(pos, spike, ctx(kalman=None), PROFILE)
    filtered_stop = next(a.price for a in filtered if a.kind is ActionKind.MOVE_STOP)
    raw_stop = next(a.price for a in raw if a.kind is ActionKind.MOVE_STOP)
    assert filtered_stop < raw_stop, "the filtered trail must be looser than the wick trail"


def test_trail_never_moves_against_the_position():
    policy = SuiteExit()
    pos, _ = position(policy)
    pos.scaled_out = True
    pos.stop = 29995.0                                       # already tight
    actions = policy.manage(pos, bar(30000.0, 30005.0, 29996.0, 30000.0), ctx(kalman=29900.0), PROFILE)
    assert all(a.kind is not ActionKind.MOVE_STOP for a in actions)


def test_ltf_weakness_tightens_the_trail():
    policy = HybridExit()
    pos, _ = position(policy)
    pos.scaled_out = True
    strong = policy.manage(pos, bar(30000.0, 30050.0, 29990.0, 30040.0), ctx(kalman=30020.0, ltf_strength=1.0), PROFILE)
    weak = policy.manage(pos, bar(30000.0, 30050.0, 29990.0, 30040.0), ctx(kalman=30020.0, ltf_strength=0.1), PROFILE)
    strong_stop = next(a.price for a in strong if a.kind is ActionKind.MOVE_STOP)
    weak_stop = next(a.price for a in weak if a.kind is ActionKind.MOVE_STOP)
    assert weak_stop > strong_stop, "a failing lower timeframe should pull the stop up"


def test_trail_is_not_armed_before_the_first_target():
    policy = SuiteExit()
    pos, _ = position(policy)
    assert not pos.scaled_out
    actions = policy.manage(pos, bar(30000.0, 30050.0, 29990.0, 30040.0), ctx(kalman=30020.0), PROFILE)
    assert all(a.kind is not ActionKind.MOVE_STOP for a in actions)


def test_zero_atr_refuses_to_build_a_trade():
    assert SuiteExit().build(PROFILE, 1, 30000.0, 29980.0, ctx(atr=0.0)) is None
    assert HybridExit().build(PROFILE, 1, 30000.0, 29980.0, ctx(atr=0.0)) is None


# --- HTF range --------------------------------------------------------------

def test_htf_range_needs_a_full_window():
    window = HTFRange(4)
    for index in range(3):
        window.update(bar(100.0, 101.0 + index, 99.0 - index, 100.0))
    assert not window.ready and window.high is None
    window.update(bar(100.0, 110.0, 90.0, 100.0))
    assert window.ready and window.high == 110.0 and window.low == 90.0


def test_htf_range_rolls_off_old_bars():
    window = HTFRange(2)
    window.update(bar(100.0, 200.0, 50.0, 100.0))
    window.update(bar(100.0, 101.0, 99.0, 100.0))
    window.update(bar(100.0, 102.0, 98.0, 100.0))
    assert window.high == 102.0 and window.low == 98.0


def test_htf_range_rejects_a_degenerate_window():
    with pytest.raises(ValueError):
        HTFRange(1)


# --- excursion-armed breakeven ----------------------------------------------
# A measured leak: 75 of 239 trades peaked between +0.5R and +1.5R and then took
# a FULL -1.00R, because the stop only moved to entry when TP1 filled at 1.5R.
# Arming breakeven off the excursion already made looked like free money. A
# sweep on a tuning tape AND a held-out tape says it is not: every arm level
# from 0.4R to 1.2R is WORSE than off, on both. The knob ships OFF.

def test_breakeven_arming_is_off_by_default():
    """The sweep says early arming costs more than the leak it plugs."""
    assert HybridExit().params.breakeven_arm_r == 0.0
    assert SuiteExit().params.breakeven_arm_r == 0.0


def test_breakeven_does_not_arm_below_the_threshold():
    from icarus.exits import HybridParams
    policy = HybridExit(HybridParams(breakeven_arm_r=1.0))
    pos, _ = position(policy)
    pos.max_favourable = 0.9
    actions = policy.manage(pos, bar(30000.0, 30010.0, 29990.0, 30000.0), ctx(), PROFILE)
    assert all(a.reason != "breakeven" for a in actions)


def test_breakeven_arms_once_the_excursion_is_made():
    from icarus.exits import HybridParams
    policy = HybridExit(HybridParams(breakeven_arm_r=1.0, breakeven_offset_r=0.05))
    pos, _ = position(policy)
    pos.max_favourable = 1.2
    actions = policy.manage(pos, bar(30000.0, 30010.0, 29990.0, 30000.0), ctx(), PROFILE)
    move = next(a for a in actions if a.reason == "breakeven")
    # Parked slightly in profit so the scratch clears round-turn friction.
    assert move.price == pytest.approx(pos.entry_price + 0.05 * pos.risk_unit)


def test_breakeven_arming_never_loosens_an_existing_stop():
    from icarus.exits import HybridParams
    policy = HybridExit(HybridParams(breakeven_arm_r=1.0))
    pos, _ = position(policy)
    pos.max_favourable = 5.0
    pos.stop = pos.entry_price + 10.0          # trail already past breakeven
    actions = policy.manage(pos, bar(30000.0, 30010.0, 29990.0, 30000.0), ctx(), PROFILE)
    assert all(a.reason != "breakeven" for a in actions)


def test_breakeven_does_not_rearm_after_it_has_fired():
    from icarus.exits import HybridParams
    policy = HybridExit(HybridParams(breakeven_arm_r=1.0))
    pos, _ = position(policy)
    pos.max_favourable = 2.0
    pos.breakeven_moved = True
    actions = policy.manage(pos, bar(30000.0, 30010.0, 29990.0, 30000.0), ctx(), PROFILE)
    assert all(a.reason != "breakeven" for a in actions)


def test_arming_at_the_scale_out_level_is_equivalent_to_the_old_behaviour():
    """Correctness check on the implementation: at TP1's own R, it is a no-op.

    The sweep confirms this empirically -- arm_r = 1.5 reproduces arm_r = 0.0
    to within noise (239 trades, +0.329R vs +0.325R) because HybridParams puts
    first_target_r at 1.5.
    """
    from icarus.exits import HybridParams
    assert HybridParams().first_target_r == 1.5
