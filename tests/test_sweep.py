"""Guards on the variant search harness.

The harness exists to avoid fooling ourselves, so its own selection discipline
is worth pinning: a variant must clear the bar on data it was never selected on.
"""

import random
from dataclasses import asdict

import pytest

from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from tools.sweep import (
    LOCATION_MODES, TIMEFRAME_CHOICES, Result, Variant, build_engine, evaluate,
    fmt, passes, sample_variant,
)


def test_sampled_variants_are_inside_their_declared_ranges():
    rng = random.Random(7)
    seen_tf = set()
    for _ in range(200):
        v = sample_variant(rng)
        assert v.timeframe in TIMEFRAME_CHOICES
        assert v.location_mode in LOCATION_MODES
        assert 0.0 <= v.w_location <= 1.30
        assert 0.45 <= v.min_confluence <= 0.82
        assert 0.8 <= v.min_stop_atr <= 3.0
        assert v.max_stop_atr >= 3.0
        assert 0.0 <= v.scale_out <= 0.85
        assert v.sweep_reclaim in (2, 3, 4, 5)
        seen_tf.add(v.timeframe)
    # The search must actually reach the slow end of the band, not cluster
    # on fast bars -- this system is built to hold long intraday trends.
    assert seen_tf == set(TIMEFRAME_CHOICES), f"never sampled: {set(TIMEFRAME_CHOICES)-seen_tf}"


def test_sampling_is_deterministic_for_a_seed():
    a = [sample_variant(random.Random(3)) for _ in range(5)]
    b = [sample_variant(random.Random(3)) for _ in range(5)]
    assert [x.key() for x in a] == [x.key() for x in b]


def test_every_location_mode_is_bounded():
    """A location score outside [0, 1] would silently break score normalisation."""
    from icarus.indicators import SessionVWAP

    vwap = SessionVWAP()
    for price in (100.0, 103.0, 97.0, 101.0, 99.0, 104.0, 96.0):
        vwap.update(price, 1000.0)
    for name, fn in LOCATION_MODES.items():
        for direction in (-1, 1):
            for price in (80.0, 95.0, 100.0, 105.0, 130.0):
                score = fn(direction, price, vwap)
                assert 0.0 <= score <= 1.0, f"{name} out of bounds at {price}: {score}"


def test_a_variant_builds_and_evaluates():
    rng = random.Random(11)
    variant = sample_variant(rng)
    bars = resample(synthetic_for(AssetClass.MICRO_FUTURES, 6000, seed=5, minutes=2),
                    variant.timeframe)
    result = evaluate(variant, bars)
    assert isinstance(result, Result)
    assert result.trades >= 0
    if result.trades:
        assert 0.0 <= result.win_rate <= 100.0
        assert result.trades_per_day > 0.0


def test_build_engine_applies_the_variant():
    rng = random.Random(2)
    variant = sample_variant(rng)
    engine = build_engine(variant)
    assert engine.profile.min_confluence == variant.min_confluence
    assert engine.profile.sweep_reclaim_bars == variant.sweep_reclaim
    assert engine.confluence.min_target_room_atr == variant.min_target_room_atr
    assert engine.exit_policy.params.min_stop_atr == variant.min_stop_atr


def test_an_empty_result_never_passes_a_filter():
    assert not passes(asdict(Result()), min_trades=1, min_exp=-99, max_tpd=99,
                      min_tpd=0, min_win=0)


def test_an_errored_variant_never_passes():
    assert not passes({"error": "boom"}, min_trades=0, min_exp=-99,
                      max_tpd=99, min_tpd=0, min_win=0)


def test_filters_reject_outside_the_trade_rate_window():
    good = asdict(Result(trades=100, expectancy=0.5, win_rate=60.0, trades_per_day=1.0))
    assert passes(good, min_trades=40, min_exp=0.05, max_tpd=2.0, min_tpd=0.05, min_win=45.0)
    too_busy = asdict(Result(trades=100, expectancy=0.5, win_rate=60.0, trades_per_day=9.0))
    assert not passes(too_busy, min_trades=40, min_exp=0.05, max_tpd=2.0, min_tpd=0.05, min_win=45.0)


def test_fmt_renders_without_blowing_up_on_infinite_profit_factor():
    rng = random.Random(4)
    res = asdict(Result(trades=10, expectancy=1.0, win_rate=100.0, trades_per_day=0.5,
                      profit_factor=float("inf")))
    assert "99.00" in fmt(sample_variant(rng), res)
