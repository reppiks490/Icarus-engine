import random

import pytest

from icarus.backtest import (
    PerformanceReport, backtest, permutation_test, run_engine, shuffle_bars, summarise, walk_forward,
)
from icarus.config import AssetClass
from icarus.data import synthetic_for


BARS = synthetic_for(AssetClass.CRYPTO, 4000, seed=11)


def test_backtest_produces_a_complete_report():
    report = backtest(BARS, AssetClass.CRYPTO)
    assert isinstance(report, PerformanceReport)
    assert report.bars == len(BARS)
    assert report.asset_class == "crypto"
    assert report.trades >= 0
    assert 0.0 <= report.win_rate <= 100.0
    assert 0.0 <= report.exposure_pct <= 100.0
    assert report.max_drawdown >= 0.0
    assert report.render()


def test_report_arithmetic_is_self_consistent():
    engine = run_engine(BARS, AssetClass.CRYPTO)
    report = summarise(engine, BARS)
    assert report.net_pnl == pytest.approx(report.ending_equity - report.starting_equity)
    assert report.sum_r == pytest.approx(sum(trade.r for trade in engine.blotter.trades))
    if report.trades:
        assert report.expectancy_r == pytest.approx(report.sum_r / report.trades)
        assert sum(report.exit_reasons.values()) == report.trades


def test_empty_input_is_rejected():
    with pytest.raises(ValueError):
        backtest([], AssetClass.CRYPTO)


def test_shuffle_preserves_length_and_bar_validity():
    surrogate = shuffle_bars(BARS, random.Random(3))
    assert len(surrogate) == len(BARS)
    assert [bar.ts for bar in surrogate] == [bar.ts for bar in BARS]
    for bar in surrogate:
        assert bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high
    assert [bar.close for bar in surrogate] != [bar.close for bar in BARS]


def test_shuffle_is_reproducible_for_a_seed():
    first = shuffle_bars(BARS, random.Random(3))
    second = shuffle_bars(BARS, random.Random(3))
    assert [bar.close for bar in first] == [bar.close for bar in second]


def test_permutation_p_value_is_a_valid_probability():
    engine = run_engine(BARS, AssetClass.CRYPTO)
    observed = sum(trade.r for trade in engine.blotter.trades)
    p_value = permutation_test(BARS, AssetClass.CRYPTO, observed, runs=5, seed=2)
    assert 0.0 < p_value <= 1.0
    assert p_value >= 1.0 / 6.0            # the observed run counts as one sample


def test_an_unbeatable_bar_is_never_significant():
    # No shuffled tape can beat +infinity, so the p-value must sit at its floor.
    p_value = permutation_test(BARS, AssetClass.CRYPTO, float("inf"), runs=4, seed=2)
    assert p_value == pytest.approx(1.0 / 5.0)


def test_permutation_runs_must_be_positive():
    with pytest.raises(ValueError):
        permutation_test(BARS, AssetClass.CRYPTO, 0.0, runs=0)


def test_verdict_refuses_to_bless_a_small_sample():
    report = backtest(synthetic_for(AssetClass.CRYPTO, 600, seed=4), AssetClass.CRYPTO)
    if report.trades < 30:
        assert "INSUFFICIENT SAMPLE" in report.verdict


def test_verdict_demands_the_permutation_test_before_sizing_up():
    report = backtest(BARS, AssetClass.CRYPTO)
    report.trades = 50
    report.sum_r = 10.0
    report.permutation_p_value = None
    assert "UNVALIDATED" in report.verdict
    report.permutation_p_value = 0.40
    assert "REJECT" in report.verdict
    report.permutation_p_value = 0.01
    report.expectancy_r = 0.20
    assert "ACCEPT" in report.verdict


def test_walk_forward_returns_contiguous_independent_folds():
    reports = walk_forward(BARS, AssetClass.CRYPTO, folds=4)
    assert len(reports) == 4
    assert sum(report.bars for report in reports) == len(BARS)
    assert all(report.starting_equity == 100_000.0 for report in reports)


def test_walk_forward_refuses_degenerate_splits():
    with pytest.raises(ValueError):
        walk_forward(BARS, AssetClass.CRYPTO, folds=1)
    with pytest.raises(ValueError, match="folds too small"):
        walk_forward(BARS[:300], AssetClass.CRYPTO, folds=4)
