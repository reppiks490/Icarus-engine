"""metrics.py must reproduce TradingView's Strategy Tester numbers from TradingView's own trade list.

Fixture: the owner's 14-Sep export (xlsx) - 295 closed pieces + 1 open, and the Performance /
Trades analysis / Risk-adjusted sheets TradingView computed for them (tests_engine/fixtures/tv_tester_0914.json).
"""
from __future__ import annotations

import json
import os

import pytest

from icarus_engine.metrics import Piece, tv_summary

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    fx = json.load(open(os.path.join(HERE, "fixtures", "tv_tester_0914.json"), encoding="utf-8"))
    closed, open_ = [], []
    for p in fx["pieces"]:
        pc = Piece(no=p["no"], direction=p["direction"], qty=int(p["entry"]["qty"]), entry_ts=p["entry"]["ts"], entry_px=p["entry"]["price"],
                   exit_ts=p["exit"]["ts"], exit_px=p["exit"]["price"], exit_signal=p["exit"]["signal"], pnl=p["pnl"], commission=p["commission"],
                   runup=p["runup"], drawdown=p["drawdown"], bars=int(p["bars"]))
        (open_ if p["exit"]["ts"] is None else closed).append(pc)
    return fx, closed, open_


def test_tv_summary_reproduces_tradingview_performance_sheet():
    fx, closed, open_ = load()
    s = tv_summary(closed, open_pieces=open_, initial_capital=fx["initial_capital"], point_value=fx["point_value"],
                   backtest_start=1727785800, backtest_end=1789391400,        # Oct 1 2024 08:30 CT -> Sep 14 2026 09:10 CT (Properties sheet)
                   first_close=22236.0, last_close=29071.0, leverage=50.0)
    P, T, R = fx["performance"], fx["trades_analysis"], fx["risk"]
    a = lambda d, k, col="All USD": d[k][col]
    # TradingView exports per-piece P&L rounded to whole dollars: sums of 295 pieces may differ by a few dollars
    assert s["net_profit"]["all"] == pytest.approx(a(P, "Net profit"), abs=5)
    assert s["net_profit"]["long"] == pytest.approx(a(P, "Net profit", "Long USD"), abs=5)
    assert s["net_profit"]["short"] == pytest.approx(a(P, "Net profit", "Short USD"), abs=5)
    assert s["net_profit_pct"]["all"] == pytest.approx(a(P, "Net profit", "All %"), abs=0.01)
    assert s["gross_profit"]["all"] == pytest.approx(a(P, "Gross profit"), abs=5)
    assert s["gross_loss"]["all"] == pytest.approx(a(P, "Gross loss"), abs=5)
    assert s["gross_profit"]["short"] == pytest.approx(a(P, "Gross profit", "Short USD"), abs=5)
    assert s["commission_paid"]["all"] == pytest.approx(a(P, "Commission paid"))
    assert s["commission_paid"]["long"] == pytest.approx(a(P, "Commission paid", "Long USD"))
    assert s["expectancy"]["all"] == pytest.approx(a(P, "Expectancy"), abs=0.05)
    assert s["max_contracts_held"]["all"] == a(P, "Max contracts held")
    assert s["open_pnl"]["all"] == pytest.approx(sum(p.pnl for p in open_))
    # trades analysis
    assert s["total_trades"]["all"] == a(T, "Total trades") and s["total_trades"]["long"] == a(T, "Total trades", "Long USD")
    assert s["winners"]["all"] == a(T, "Total winners") and s["losers"]["all"] == a(T, "Total losers") and s["even"]["all"] == a(T, "Even trades")
    assert s["percent_profitable"]["all"] == pytest.approx(a(T, "Percent profitable", "All %"), abs=0.01)
    assert s["percent_profitable"]["short"] == pytest.approx(a(T, "Percent profitable", "Short %"), abs=0.01)
    assert s["avg_profit"]["all"] == pytest.approx(a(T, "Average profit"), abs=0.1)
    assert s["avg_loss"]["all"] == pytest.approx(a(T, "Average loss"), abs=0.1)
    assert s["avg_profit_over_avg_loss"]["all"] == pytest.approx(a(T, "Average profit / average loss"), abs=0.001)
    assert s["largest_profit"]["all"] == pytest.approx(a(T, "Largest profit")) and s["largest_loss"]["all"] == pytest.approx(a(T, "Largest loss"))
    assert s["largest_profit"]["short"] == pytest.approx(a(T, "Largest profit", "Short USD"))
    assert s["outliers"]["all"] == a(T, "Outliers") and s["outliers_pnl"]["all"] == pytest.approx(a(T, "Outliers P&L"), abs=5)
    assert s["outliers"]["long"] == a(T, "Outliers", "Long USD") and s["outliers"]["short"] == a(T, "Outliers", "Short USD")
    assert round(s["avg_bars_in_trades"]["all"]) == a(T, "Average bars in trades")
    assert round(s["avg_bars_in_winners"]["all"]) == a(T, "Average bars in winners")
    assert round(s["avg_bars_in_losers"]["all"]) == a(T, "Average bars in losers")
    # risk-adjusted
    assert s["profit_factor"]["all"] == pytest.approx(a(R, "Profit factor"), abs=0.001)
    assert s["profit_factor"]["long"] == pytest.approx(a(R, "Profit factor", "Long USD"), abs=0.001)
    assert s["profit_factor"]["short"] == pytest.approx(a(R, "Profit factor", "Short USD"), abs=0.001)
    # derived ratios TradingView prints
    assert s["net_pnl_pct_of_largest_loss"]["all"] == pytest.approx(a(P, "Net PnL as % of largest loss", "All %"), abs=0.2)
    assert s["largest_profit_pct_of_gross_profit"]["all"] == pytest.approx(a(P, "Largest profit as % of gross profit", "All %"), abs=0.01)
    assert s["largest_loss_pct_of_gross_loss"]["all"] == pytest.approx(a(P, "Largest loss as % of gross loss", "All %"), abs=0.01)
    # equity-curve statistics at trade closes ("close-to-close")
    assert s["max_drawdown"]["all"] == pytest.approx(a(P, "Max drawdown (close-to-close)"), abs=1)
    assert s["max_drawdown_pct"]["all"] == pytest.approx(a(P, "Max drawdown (close-to-close)", "All %"), abs=0.02)
    assert s["max_runup"]["all"] == pytest.approx(a(P, "Max run-up (close-to-close)"), abs=1)
    assert s["max_runup_pct"]["all"] == pytest.approx(a(P, "Max run-up (close-to-close)", "All %"), abs=0.02)
    assert s["return_of_max_drawdown"]["all"] == pytest.approx(a(P, "Return of max drawdown"), abs=0.3)
    # buy & hold, CAGR, margin (TradingView: 50x leverage = 2 % margin)
    assert s["buy_and_hold_pnl"]["all"] == pytest.approx(a(P, "Buy and hold PnL"), abs=30)
    assert s["buy_and_hold_pct_gain"]["all"] == pytest.approx(a(P, "Buy and hold % gain", "All %"), abs=0.02)
    assert s["strategy_outperformance"]["all"] == pytest.approx(a(P, "Strategy outperformance"), abs=35)
    assert s["cagr_pct"]["all"] == pytest.approx(a(P, "Annualized return (CAGR)", "All %"), abs=0.3)
    assert s["return_on_initial_capital_pct"]["all"] == pytest.approx(a(P, "Return on initial capital", "All %"), abs=0.01)
    assert s["max_margin_used"]["all"] == pytest.approx(a(P, "Max margin used"), rel=0.01)
    assert s["sharpe"]["all"] == pytest.approx(a(R, "Sharpe ratio"), abs=0.05)
    assert s["sortino"]["all"] == pytest.approx(a(R, "Sortino ratio"), abs=0.3)


def test_tv_summary_handles_no_trades():
    s = tv_summary([], open_pieces=[], initial_capital=100000, point_value=20)
    assert s["total_trades"]["all"] == 0 and s["net_profit"]["all"] == 0 and s["profit_factor"]["all"] is None and s["max_drawdown"]["all"] == 0
