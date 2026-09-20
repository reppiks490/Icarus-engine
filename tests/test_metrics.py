"""Tests for the characterisation suite.

The grouping rule is the one that matters: `entry_id` is a Pine strategy label
("Long", "Short") reused across every trade. Grouping legs by it silently merges
unrelated positions, which is how a single-contract run once reported 50 runner
legs it did not have.
"""

import pytest

from tools.metrics import Report, analyse, assemble


class Leg:
    """Minimal stand-in for icarus_engine.emulator.ClosedTrade."""

    def __init__(self, entry_bar, exit_bar, profit, exit_comment="X",
                 direction=1, runup=0.0, drawdown=0.0, entry_id="Long"):
        self.entry_bar = entry_bar
        self.exit_bar = exit_bar
        self.exit_ts = exit_bar * 600
        self.entry_ts = entry_bar * 600
        self.profit = profit
        self.exit_comment = exit_comment
        self.direction = direction
        self.runup = runup
        self.drawdown = drawdown
        self.entry_id = entry_id
        self.qty = 1


def test_legs_group_by_entry_bar_not_by_pine_label():
    """The bug this suite was built to stop: every leg shares entry_id."""
    legs = [Leg(10, 12, 100.0), Leg(50, 55, -80.0), Leg(90, 95, 60.0)]
    assert all(l.entry_id == "Long" for l in legs)
    positions = assemble(legs)
    assert len(positions) == 3
    assert all(len(p.legs) == 1 for p in positions)
    assert all(not p.runner_legs for p in positions)


def test_a_scaled_out_position_is_one_position_with_a_runner():
    legs = [Leg(10, 12, 100.0, "L_TP1"), Leg(10, 30, 40.0, "L_TP2")]
    positions = assemble(legs)
    assert len(positions) == 1
    assert len(positions[0].runner_legs) == 1
    assert positions[0].profit == pytest.approx(140.0)
    assert positions[0].bars_held == 20


def test_runner_breakeven_counts_as_a_failure_not_a_neutral():
    legs = [Leg(i, i + 2, 100.0, "L_TP1") for i in range(0, 100, 10)]
    legs += [Leg(i, i + 5, 0.0, "L_BE") for i in range(0, 100, 10)]
    report = analyse(legs)
    assert report.runner_legs == 10
    assert report.runner_win_rate == pytest.approx(0.0)
    assert report.runner_breakeven_rate == pytest.approx(100.0)


def test_single_leg_run_reports_no_runner():
    report = analyse([Leg(i, i + 2, 50.0, "L_TP1") for i in range(0, 100, 10)])
    assert report.runner_legs == 0
    assert report.runner_win_rate is None


def test_empty_input_returns_a_zeroed_report():
    report = analyse([])
    assert isinstance(report, Report) and report.trades == 0


# --- consistency ------------------------------------------------------------

def test_a_steady_series_scores_high_consistency():
    steady = analyse([Leg(i, i + 2, 100.0) for i in range(0, 600, 5)], block_size=25)
    assert steady.consistency > 0.9
    assert steady.positive_block_rate == pytest.approx(100.0)


def test_one_trade_carrying_the_whole_result_is_flagged():
    legs = [Leg(i, i + 2, -10.0) for i in range(0, 300, 5)]
    legs.append(Leg(400, 402, 5000.0))
    report = analyse(legs, block_size=25)
    assert report.top_decile_share > 65.0
    assert report.gini > 0.3


def test_losing_streaks_are_counted():
    legs = [Leg(i, i + 1, -10.0 if i < 50 else 10.0) for i in range(0, 100)]
    report = analyse(legs)
    assert report.max_losing_streak == 50
    assert report.max_winning_streak == 50


# --- risk and execution -----------------------------------------------------

def test_drawdown_is_measured_peak_to_trough_on_the_curve():
    legs = [Leg(0, 1, 100.0), Leg(2, 3, -30.0), Leg(4, 5, -40.0), Leg(6, 7, 200.0)]
    report = analyse(legs)
    assert report.max_drawdown == pytest.approx(70.0)
    assert report.recovery_factor == pytest.approx(230.0 / 70.0)


def test_same_bar_exits_are_reported():
    legs = [Leg(i, i, 10.0) for i in range(5)] + [Leg(i, i + 9, 10.0) for i in range(10, 15)]
    assert analyse(legs).same_bar_rate == pytest.approx(50.0)


def test_mfe_capture_shows_profit_given_back():
    """Realised 40 of an available 100 is 0.4 capture."""
    legs = [Leg(i, i + 3, 40.0, runup=100.0, drawdown=-20.0) for i in range(0, 50, 5)]
    report = analyse(legs)
    assert report.mfe_capture == pytest.approx(0.4)
    assert report.edge_ratio == pytest.approx(5.0)


def test_trades_per_day_uses_the_supplied_span():
    legs = [Leg(i, i + 1, 10.0) for i in range(0, 100, 10)]
    assert analyse(legs, span_days=10.0).trades_per_day == pytest.approx(1.0)
