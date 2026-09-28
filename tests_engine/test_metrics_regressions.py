"""Regressions for timestamp ties and gaps in trade-close metrics."""
from datetime import datetime, timezone
import math
import statistics

import pytest

from icarus_engine.metrics import Piece, _monthly_returns, equity_points, tv_summary


def piece(no, direction=1, qty=1, entry_ts=0, exit_ts=60, pnl=0):
    return Piece(no=no, direction=direction, qty=qty, entry_ts=entry_ts,
                 entry_px=100, exit_ts=exit_ts,
                 exit_px=100 if exit_ts is not None else None,
                 exit_signal="", pnl=pnl, commission=0)


@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("exit_ts", [100, 200, None])
def test_reversal_does_not_double_exposure(direction, exit_ts):
    old = piece(1, direction=direction, exit_ts=100)
    new = piece(2, direction=-direction, entry_ts=100, exit_ts=exit_ts)
    closed = [old] + ([new] if exit_ts is not None else [])
    opened = [new] if exit_ts is None else []
    s = tv_summary(closed, opened, initial_capital=1000, point_value=1, leverage=10)
    assert s["max_contracts_held"] == {"all": 1, "long": 1, "short": 1}
    assert s["max_margin_used"] == {"all": 10, "long": 10, "short": 10}
    assert s["avg_margin_used"]["all"] == pytest.approx(20 / (3 if exit_ts is None else 4))


def test_same_bar_pieces_retain_combined_exposure():
    pieces = [piece(1, qty=2, entry_ts=60), piece(2, qty=3, entry_ts=60)]
    s = tv_summary(pieces, initial_capital=1000, point_value=2, leverage=10)
    assert s["max_contracts_held"]["all"] == 5
    assert s["max_margin_used"]["all"] == 100


def test_same_direction_timestamp_tie_retains_overlap():
    pieces = [piece(1), piece(2, entry_ts=60, exit_ts=120)]
    s = tv_summary(pieces, initial_capital=1000, point_value=1, leverage=10)
    assert s["max_contracts_held"]["all"] == 2
    assert s["max_margin_used"]["all"] == 20


@pytest.mark.parametrize("pnl", [-10, 10])
def test_first_same_timestamp_close_preserves_baseline(pnl):
    pieces = [piece(1, entry_ts=60, pnl=pnl)]
    assert equity_points(pieces, 1000) == [(60, 1000), (60, 1000 + pnl)]
    s = tv_summary(pieces, initial_capital=1000, point_value=1)
    assert s["avg_drawdown"]["all"] == max(-pnl, 0)
    assert s["max_drawdown"]["all"] == max(-pnl, 0)
    assert s["max_runup"]["all"] == max(pnl, 0)


def test_same_timestamp_closes_still_aggregate_after_baseline():
    pieces = [piece(2, entry_ts=60, pnl=5), piece(1, entry_ts=60, pnl=-10)]
    assert equity_points(pieces, 1000) == [(60, 1000), (60, 995)]


@pytest.mark.parametrize("start,end", [("2025-01-01", "2025-03-31"),
                                      ("2024-12-01", "2025-02-28")])
def test_inactive_calendar_months_carry_equity_and_risk_free_return(start, end):
    start_ts = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp())
    expected = [0, 0, 0.1]
    assert _monthly_returns([(start_ts, 1000), (end_ts, 1100)]) == pytest.approx(expected)
    s = tv_summary([piece(1, entry_ts=start_ts, exit_ts=end_ts, pnl=100)],
                   initial_capital=1000, point_value=1, risk_free_pct=12)
    excess = [-0.01, -0.01, 0.09]
    assert s["sharpe"]["all"] == pytest.approx(statistics.mean(excess) / statistics.pstdev(expected))
    assert s["sortino"]["all"] == pytest.approx(statistics.mean(excess) / math.sqrt(0.0002 / 3))
