import pytest

from icarus.config import AssetClass, profile_for
from icarus.data import synthetic_for
from icarus.lab import HEADER, compare, hold_stats, render, run_policy

SOURCE = synthetic_for(AssetClass.MICRO_FUTURES, 20000, seed=11, minutes=2)


def test_compare_returns_one_result_per_policy_per_timeframe():
    results = compare(SOURCE, AssetClass.MICRO_FUTURES,
                      policies=("pulse", "hybrid"), timeframes=("10m",))
    assert len(results) == 2
    assert {r.policy for r in results} == {"pulse", "hybrid"}
    assert {r.timeframe for r in results} == {"10m"}


def test_compare_refuses_a_tape_too_short_to_mean_anything():
    with pytest.raises(ValueError, match="supply more data"):
        compare(SOURCE[:400], AssetClass.MICRO_FUTURES,
                policies=("pulse",), timeframes=("30m",))


def test_every_policy_sees_the_identical_tape():
    """Any difference in the output must be attributable to the exit layer."""
    results = compare(SOURCE, AssetClass.MICRO_FUTURES,
                      policies=("pulse", "suite", "hybrid"), timeframes=("10m",))
    assert len({r.report.bars for r in results}) == 1


def test_pulse_dies_on_the_entry_bar_more_often_than_the_floored_policies():
    """The headline finding, pinned so a refactor cannot silently undo it."""
    results = {r.policy: r.holds for r in compare(
        SOURCE, AssetClass.MICRO_FUTURES,
        policies=("pulse", "suite", "hybrid"), timeframes=("10m",))}
    assert results["pulse"].same_bar_pct > results["suite"].same_bar_pct
    assert results["pulse"].same_bar_pct > results["hybrid"].same_bar_pct


def test_floored_stops_buy_longer_holds():
    results = {r.policy: r.holds for r in compare(
        SOURCE, AssetClass.MICRO_FUTURES,
        policies=("pulse", "suite", "hybrid"), timeframes=("10m",))}
    assert results["suite"].median_hold > results["pulse"].median_hold
    assert results["hybrid"].median_hold > results["pulse"].median_hold
    assert results["suite"].median_risk_atr > results["pulse"].median_risk_atr


def test_hold_stats_on_an_empty_blotter_are_zeroed_not_undefined():
    engine, risk = run_policy(SOURCE[:600], profile_for(AssetClass.MICRO_FUTURES),
                              "pulse", timeframe=2)
    stats = hold_stats(engine, risk)
    assert stats.trades == len(engine.blotter.trades)
    if stats.trades == 0:
        assert stats.median_hold == 0.0 and stats.exit_mix == {}


def test_render_produces_one_row_per_result():
    results = compare(SOURCE, AssetClass.MICRO_FUTURES,
                      policies=("pulse", "hybrid"), timeframes=("10m",))
    text = render(results, "title")
    assert "title" in text and HEADER in text
    for result in results:
        assert result.policy in text


def test_permutation_runs_under_the_same_policy_as_the_observation():
    results = compare(SOURCE, AssetClass.MICRO_FUTURES, policies=("hybrid",),
                      timeframes=("30m",), permutations=3, seed=2)
    p_value = results[0].report.permutation_p_value
    assert p_value is not None and 0.0 < p_value <= 1.0
    assert results[0].report.permutation_runs == 3
