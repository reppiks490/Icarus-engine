"""Guards on the cross-engine validation harness.

This harness drives Astra's PulseStrategy through this session's permutation
null. Its whole value is that both engines meet the same tape and the same
surrogates, so the comparison is apples to apples -- these tests pin that.
"""

import random

import pytest

from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from tools.validate_pulse import (
    HTF_NEUTRAL, LTF_NEUTRAL, permutation_null, run_pulse, to_pulse_bars,
)

TAPE = resample(synthetic_for(AssetClass.MICRO_FUTURES, 6000, seed=11, minutes=2), "20m")


def test_bar_conversion_preserves_prices_and_ordering():
    converted = to_pulse_bars(TAPE)
    assert len(converted) == len(TAPE)
    for original, pulse in zip(TAPE[:50], converted[:50]):
        assert pulse.o == original.open and pulse.c == original.close
        assert pulse.h == original.high and pulse.l == original.low
        assert pulse.ts == int(original.ts.timestamp())
    assert all(a.ts < b.ts for a, b in zip(converted, converted[1:]))


def test_neutral_context_is_shaped_as_pulse_expects():
    """5 HTF connections of (dir, regime); 2 LTF of (dir, bars_since_flip, regime)."""
    assert len(HTF_NEUTRAL) == 5 and all(len(x) == 2 for x in HTF_NEUTRAL)
    assert len(LTF_NEUTRAL) == 2 and all(len(x) == 3 for x in LTF_NEUTRAL)


def test_run_pulse_reports_a_coherent_blotter():
    result = run_pulse(TAPE, tf_minutes=20)
    assert result["trades"] >= 0
    if result["trades"]:
        assert 0.0 <= result["win_rate"] <= 100.0
        assert result["expectancy"] == pytest.approx(result["net"] / result["trades"])
        assert result["mean_hold"] >= 0.0


def test_fixed_points_sizing_collapses_hold_time_on_this_tape():
    """The finding, pinned: NQ-sized point stops on a 20m MNQ tape exit same-bar.

    45 points sits inside one bar's range here, so the trade is decided on its
    own entry bar. ATR-scaled sizing is the fix, and the gap must stay visible.
    """
    fixed = run_pulse(TAPE, tf_minutes=20, tpsl_mode="Fixed Points")
    scaled = run_pulse(TAPE, tf_minutes=20, tpsl_mode="ATR-Based")
    if fixed["trades"] >= 5 and scaled["trades"] >= 5:
        assert scaled["mean_hold"] > fixed["mean_hold"], (
            f"ATR sizing should hold longer: {scaled['mean_hold']:.1f} "
            f"vs {fixed['mean_hold']:.1f} bars")


def test_permutation_p_value_is_bounded_by_its_run_count():
    """p can never beat 1/(runs+1) -- a floor value means the test ran out of
    resolution, not that the result is weak. That distinction cost a wrong call
    earlier and is worth a test."""
    out = permutation_null(TAPE, runs=3, tf_minutes=20, seed=5)
    assert out["p_value"] >= 1.0 / 4.0
    assert out["p_value"] <= 1.0
    assert out["runs"] == 3
