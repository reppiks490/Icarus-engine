"""TradingView Strategy Tester metrics, computed the way TradingView computes them.

Validated against the owner's own TradingView export (tests_engine/test_metrics.py feeds TradingView's
trade list back in and checks TradingView's Performance / Trades analysis / Risk-adjusted sheets):

  Net profit, Gross profit/loss, Commission paid, Expectancy, Percent profitable, Average profit/loss and
  their ratio, Largest profit/loss, Outliers (pieces whose return % is more than 2 standard deviations from
  the mean return %), Average bars in trades/winners/losers, Profit factor, Max contracts held, Net PnL as %
  of largest loss, Largest profit/loss as % of gross, Max drawdown / run-up (close-to-close) and their
  averages/durations (equity at trade closes; an episode counts once the decline exceeds the threshold -
  TradingView's average drawdown 5,495 / max run-up 280,704 are reproduced with a 0.3 % threshold),
  Return of max drawdown, Buy & hold (one contract per initial capital / (first close x point value)),
  Strategy outperformance, CAGR over the backtesting range, margin used (initial capital / leverage:
  TradingView "50x" = 2 % margin), Sharpe / Sortino on monthly returns (risk-free 2 % p.a., population deviation, not annualised;
  TradingView's 1.698 / 8.502 come out as 1.688 / 8.484 from the exported, dollar-rounded trade list).

"Intrabar" run-up/drawdown need bar highs/lows; they are computed when `equity_path` (per-bar equity
including open P&L) is supplied, else reported as None.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass
class Piece:
    """One closed (or open) trade piece, TradingView's List-of-Trades row pair."""
    no: int
    direction: int              # +1 long, -1 short
    qty: int
    entry_ts: int
    entry_px: float
    exit_ts: Optional[int]      # None while open
    exit_px: Optional[float]
    exit_signal: str
    pnl: float                  # net of commission (TradingView "Net PnL")
    commission: float
    runup: Optional[float] = None       # favorable excursion, USD
    drawdown: Optional[float] = None    # adverse excursion, USD (negative or 0)
    bars: int = 0
    entry_id: str = ""

    @property
    def notional(self) -> float:
        return abs(self.entry_px) * self.qty


_GROUPS = ("all", "long", "short")


def _by_group(pieces: Sequence[Piece]) -> Dict[str, List[Piece]]:
    return {"all": list(pieces), "long": [p for p in pieces if p.direction > 0], "short": [p for p in pieces if p.direction < 0]}


def _div(a: float, b: float) -> Optional[float]:
    return (a / b) if b else None


def equity_points(closed: Sequence[Piece], initial_capital: float) -> List[Tuple[int, float]]:
    """Equity at every trade close (pieces closing at the same instant aggregated), starting with the capital."""
    pts = [(min([p.entry_ts for p in closed] or [0]), initial_capital)]
    cum = initial_capital
    for p in sorted(closed, key=lambda p: (p.exit_ts, p.no)):
        cum += p.pnl
        if len(pts) > 1 and pts[-1][0] == p.exit_ts:
            pts[-1] = (p.exit_ts, cum)
        else:
            pts.append((p.exit_ts, cum))
    return pts


def drawdown_episodes(pts: Sequence[Tuple[int, float]], min_pct: float = 0.3) -> List[Tuple[int, float, int, float, int]]:
    """(peak_ts, peak, low_ts, low, end_ts) of every decline from an equity peak that reaches `min_pct` % of the peak."""
    if not pts:
        return []
    eps = []
    peak, peak_t = pts[0][1], pts[0][0]
    low: Optional[Tuple[float, int]] = None
    for t, eq in pts:
        if eq >= peak:
            if low is not None and (peak - low[0]) / peak * 100 >= min_pct:
                eps.append((peak_t, peak, low[1], low[0], t))
            peak, peak_t = eq, t
            low = None
        elif low is None or eq < low[0]:
            low = (eq, t)
    if low is not None and (peak - low[0]) / peak * 100 >= min_pct:
        eps.append((peak_t, peak, low[1], low[0], pts[-1][0]))
    return eps


def runup_episodes(pts: Sequence[Tuple[int, float]], eps) -> List[Tuple[int, float, int, float]]:
    """(low_ts, low, peak_ts, peak): the rises between consecutive drawdown episodes (and before/after them)."""
    if not pts:
        return []
    lows = [(pts[0][0], pts[0][1])] + [(e[2], e[3]) for e in eps]
    out = []
    for k, (lt, lo) in enumerate(lows):
        if k < len(eps):
            pt, pk = eps[k][0], eps[k][1]
        else:
            # Equal timestamps still have an order (capital, then close).
            # A pre-loss capital point is not a recovery after that loss.
            start = next((i for i, point in enumerate(pts) if point == (lt, lo)), len(pts))
            after = pts[start:]
            pt, pk = max(after, key=lambda x: x[1]) if after else (lt, lo)
        out.append((lt, lo, pt, pk))
    return out


def _monthly_returns(pts: Sequence[Tuple[int, float]]) -> List[float]:
    """Return per calendar month from the trade-close equity (equity at the last close of each month)."""
    if len(pts) < 2:
        return []
    by_month: Dict[Tuple[int, int], float] = {}
    for t, eq in pts:
        d = datetime.fromtimestamp(t, tz=timezone.utc)
        by_month[(d.year, d.month)] = eq
    keys = sorted(by_month)
    rets = []
    prev = pts[0][1]
    year, month = keys[0]
    while (year, month) <= keys[-1]:
        eq = by_month.get((year, month), prev)
        if prev > 0:
            rets.append(eq / prev - 1.0)
        prev = eq
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return rets


def tv_summary(closed: Sequence[Piece], open_pieces: Sequence[Piece] = (), *, initial_capital: float, point_value: float,
               backtest_start: Optional[int] = None, backtest_end: Optional[int] = None,
               first_close: Optional[float] = None, last_close: Optional[float] = None, leverage: Optional[float] = None,
               risk_free_pct: float = 2.0, episode_min_pct: float = 0.3,
               equity_path: Optional[Sequence[Tuple[int, float]]] = None) -> Dict[str, Dict[str, Optional[float]]]:
    groups = _by_group(closed)
    og = _by_group(open_pieces)
    out: Dict[str, Dict[str, Optional[float]]] = {}

    def put(key: str, fn):
        out[key] = {g: fn(g) for g in _GROUPS}

    # ── outliers: return % more than 2 standard deviations from the mean (computed over ALL closed pieces) ──
    rets = [(p.pnl / (p.notional * point_value) * 100.0) if p.notional * point_value else 0.0 for p in closed]
    if len(rets) >= 2:
        m, sd = statistics.mean(rets), statistics.stdev(rets)
        outlier_ids = {p.no for p, r in zip(closed, rets) if sd > 0 and abs(r - m) > 2.0 * sd}
    else:
        outlier_ids = set()

    put("total_trades", lambda g: len(groups[g]))
    put("open_trades", lambda g: len(og[g]))
    put("winners", lambda g: sum(1 for p in groups[g] if p.pnl > 0))
    put("losers", lambda g: sum(1 for p in groups[g] if p.pnl < 0))
    put("even", lambda g: sum(1 for p in groups[g] if p.pnl == 0))
    put("net_profit", lambda g: sum(p.pnl for p in groups[g]))
    put("gross_profit", lambda g: sum(p.pnl for p in groups[g] if p.pnl > 0))
    put("gross_loss", lambda g: -sum(p.pnl for p in groups[g] if p.pnl < 0))
    put("commission_paid", lambda g: sum(p.commission for p in groups[g]) + sum(p.commission for p in og[g]))   # TradingView counts the open trade's entry commission
    put("open_pnl", lambda g: sum(p.pnl for p in og[g]))
    put("net_profit_pct", lambda g: out["net_profit"][g] / initial_capital * 100.0)
    put("gross_profit_pct", lambda g: out["gross_profit"][g] / initial_capital * 100.0)
    put("gross_loss_pct", lambda g: out["gross_loss"][g] / initial_capital * 100.0)
    put("return_on_initial_capital_pct", lambda g: out["net_profit_pct"][g])
    put("expectancy", lambda g: _div(out["net_profit"][g], out["total_trades"][g]))
    put("percent_profitable", lambda g: _div(out["winners"][g] * 100.0, out["total_trades"][g]))
    put("avg_profit", lambda g: _div(out["gross_profit"][g], out["winners"][g]))
    put("avg_loss", lambda g: _div(out["gross_loss"][g], out["losers"][g]))
    put("avg_profit_over_avg_loss", lambda g: _div(out["avg_profit"][g] or 0.0, out["avg_loss"][g] or 0.0))
    put("largest_profit", lambda g: max([p.pnl for p in groups[g] if p.pnl > 0] or [0.0]))
    put("largest_loss", lambda g: -min([p.pnl for p in groups[g] if p.pnl < 0] or [0.0]))
    put("largest_profit_pct_of_gross_profit", lambda g: _div(out["largest_profit"][g] * 100.0, out["gross_profit"][g]))
    put("largest_loss_pct_of_gross_loss", lambda g: _div(out["largest_loss"][g] * 100.0, out["gross_loss"][g]))
    put("net_pnl_pct_of_largest_loss", lambda g: _div(out["net_profit"][g] * 100.0, out["largest_loss"][g]))
    put("outliers", lambda g: sum(1 for p in groups[g] if p.no in outlier_ids))
    put("outliers_pnl", lambda g: sum(p.pnl for p in groups[g] if p.no in outlier_ids))
    # TradingView counts the bars a trade is open INCLUSIVE of the entry and exit bars = "Duration (bars)" + 1
    put("avg_bars_in_trades", lambda g: _div(sum(p.bars + 1 for p in groups[g]), len(groups[g])))
    put("avg_bars_in_winners", lambda g: _div(sum(p.bars + 1 for p in groups[g] if p.pnl > 0), out["winners"][g]))
    put("avg_bars_in_losers", lambda g: _div(sum(p.bars + 1 for p in groups[g] if p.pnl < 0), out["losers"][g]))
    put("profit_factor", lambda g: _div(out["gross_profit"][g], out["gross_loss"][g]))

    # ── position over time: max contracts held, margin used ──
    def exposure(g):
        ev = []
        # A reversal closes the old direction before opening the new one.
        # Other ties retain entries-before-exits: partial exits and same-bar
        # trades still occupied their combined quantity during that bar.
        entry_directions = {}
        for p in groups["all"] + og["all"]:
            entry_directions.setdefault(p.entry_ts, set()).add(p.direction)
        for p in groups[g] + og[g]:
            ev.append((p.entry_ts, 1, p.qty, p.entry_px))
            if p.exit_ts is not None:
                reversal = p.entry_ts < p.exit_ts and -p.direction in entry_directions.get(p.exit_ts, ())
                ev.append((p.exit_ts, 0 if reversal else 2, -p.qty, p.entry_px))
        ev.sort(key=lambda e: (e[0], e[1]))
        pos = 0; notional = 0.0; max_pos = 0; max_notional = 0.0; samples = []
        for t, _, dq, px in ev:
            pos += dq; notional += dq * px * point_value
            max_pos = max(max_pos, pos); max_notional = max(max_notional, notional)
            samples.append(max(notional, 0.0))
        return max_pos, max_notional, (statistics.mean(samples) if samples else 0.0)
    exp = {g: exposure(g) for g in _GROUPS}
    put("max_contracts_held", lambda g: exp[g][0])
    margin_frac = (1.0 / leverage) if leverage else None
    put("max_margin_used", lambda g: (exp[g][1] * margin_frac) if margin_frac else None)
    put("avg_margin_used", lambda g: (exp[g][2] * margin_frac) if margin_frac else None)

    # ── equity at trade closes: drawdown / run-up episodes ──
    def curve_stats(g):
        pts = equity_points(groups[g], initial_capital)
        eps = drawdown_episodes(pts, episode_min_pct)
        rus = runup_episodes(pts, eps)
        peak = initial_capital; mdd = 0.0; mdd_pct = 0.0
        for t, eq in pts:                                                   # max drawdown: plain peak-to-trough, no threshold
            peak = max(peak, eq)
            dd = peak - eq
            if dd > mdd:
                mdd, mdd_pct = dd, dd / peak * 100.0
        best = max(rus, key=lambda r: r[3] - r[1]) if rus else None
        return {
            "max_drawdown": mdd, "max_drawdown_pct": mdd_pct,
            "avg_drawdown": statistics.mean([e[1] - e[3] for e in eps]) if eps else 0.0,
            "avg_drawdown_pct": statistics.mean([(e[1] - e[3]) / e[1] * 100.0 for e in eps]) if eps else 0.0,
            "avg_drawdown_days": statistics.mean([(e[4] - e[0]) / 86400.0 for e in eps]) if eps else 0.0,
            "max_runup": (best[3] - best[1]) if best else 0.0,
            "max_runup_pct": ((best[3] - best[1]) / best[1] * 100.0) if best and best[1] else 0.0,
            "avg_runup": statistics.mean([r[3] - r[1] for r in rus]) if rus else 0.0,
            "avg_runup_pct": statistics.mean([(r[3] - r[1]) / r[1] * 100.0 for r in rus if r[1]]) if rus else 0.0,
            "avg_runup_days": statistics.mean([(r[2] - r[0]) / 86400.0 for r in rus]) if rus else 0.0,
            "pts": pts,
        }
    cs = {g: curve_stats(g) for g in _GROUPS}
    for k in ("max_drawdown", "max_drawdown_pct", "avg_drawdown", "avg_drawdown_pct", "avg_drawdown_days",
              "max_runup", "max_runup_pct", "avg_runup", "avg_runup_pct", "avg_runup_days"):
        put(k, lambda g, k=k: cs[g][k])
    put("return_of_max_drawdown", lambda g: _div(out["net_profit"][g], out["max_drawdown"][g]))

    # ── intrabar run-up / drawdown from a per-bar equity path (optional) ──
    if equity_path:
        peak = initial_capital; mdd = 0.0; mdd_pct = 0.0; trough = initial_capital; mru = 0.0; mru_pct = 0.0
        for t, eq in equity_path:
            peak = max(peak, eq); trough = min(trough, eq)
            if peak - eq > mdd:
                mdd, mdd_pct = peak - eq, (peak - eq) / peak * 100.0
            if eq - trough > mru:
                mru, mru_pct = eq - trough, (eq - trough) / trough * 100.0 if trough else 0.0
        out["max_drawdown_intrabar"] = {"all": mdd, "long": None, "short": None}
        out["max_drawdown_intrabar_pct"] = {"all": mdd_pct, "long": None, "short": None}
        out["max_runup_intrabar"] = {"all": mru, "long": None, "short": None}
        out["max_runup_intrabar_pct"] = {"all": mru_pct, "long": None, "short": None}
    else:
        for k in ("max_drawdown_intrabar", "max_drawdown_intrabar_pct", "max_runup_intrabar", "max_runup_intrabar_pct"):
            out[k] = {"all": None, "long": None, "short": None}

    # ── buy & hold, CAGR ──
    if first_close and last_close:
        qty = math.floor(initial_capital / (first_close * point_value)) if first_close * point_value > 0 else 0
        bh = (last_close - first_close) * point_value * qty
        out["buy_and_hold_pnl"] = {"all": bh, "long": None, "short": None}
        out["buy_and_hold_pnl_pct"] = {"all": bh / initial_capital * 100.0, "long": None, "short": None}
        out["buy_and_hold_pct_gain"] = {"all": (last_close / first_close - 1.0) * 100.0, "long": None, "short": None}
        out["strategy_outperformance"] = {"all": out["net_profit"]["all"] - bh, "long": None, "short": None}
    else:
        for k in ("buy_and_hold_pnl", "buy_and_hold_pnl_pct", "buy_and_hold_pct_gain", "strategy_outperformance"):
            out[k] = {"all": None, "long": None, "short": None}
    if backtest_start and backtest_end and backtest_end > backtest_start:
        years = (backtest_end - backtest_start) / (365.25 * 86400.0)
        def cagr(g):
            fin = initial_capital + out["net_profit"][g]
            return ((fin / initial_capital) ** (1.0 / years) - 1.0) * 100.0 if fin > 0 else None
        put("cagr_pct", cagr)
    else:
        out["cagr_pct"] = {"all": None, "long": None, "short": None}

    # ── account size required (TradingView: max intrabar drawdown + max margin used) ──
    dd_for_acct = out["max_drawdown_intrabar"]["all"] if out["max_drawdown_intrabar"]["all"] is not None else out["max_drawdown"]["all"]
    out["account_size_required"] = {"all": (dd_for_acct + (out["max_margin_used"]["all"] or 0.0)), "long": None, "short": None}
    out["return_on_account_size_required_pct"] = {"all": _div(out["net_profit"]["all"] * 100.0, out["account_size_required"]["all"]), "long": None, "short": None}

    # ── Sharpe / Sortino on monthly returns ──
    def ratios(g):
        rets = _monthly_returns(cs[g]["pts"])
        if len(rets) < 2:
            return None, None
        # TradingView: monthly returns, risk-free 2 % p.a. / 12, population deviation, NOT annualised
        # (the owner's export: Sharpe 1.698 / Sortino 8.502 -> 1.688 / 8.484 from the exported trade list)
        rf = risk_free_pct / 100.0 / 12.0
        ex = [r - rf for r in rets]
        m = statistics.mean(ex)
        sd = statistics.pstdev(rets)
        sharpe = (m / sd) if sd > 0 else None
        downside = [min(e, 0.0) ** 2 for e in ex]
        ddv = math.sqrt(sum(downside) / len(downside)) if downside else 0.0
        sortino = (m / ddv) if ddv > 0 else None
        return sharpe, sortino
    rr = {g: ratios(g) for g in _GROUPS}
    put("sharpe", lambda g: rr[g][0])
    put("sortino", lambda g: rr[g][1])
    out["margin_calls"] = {"all": 0, "long": 0, "short": 0}
    for k in ("total_trades", "open_trades", "winners", "losers", "even", "outliers", "max_contracts_held"):
        out[k] = {g: (int(v) if v is not None else None) for g, v in out[k].items()}
    return out


# Display order and labels, exactly as TradingView's tabs
PERFORMANCE_ROWS = [
    ("open_pnl", "Open PnL", "$"), ("net_profit", "Net profit", "$%"), ("gross_profit", "Gross profit", "$%"), ("gross_loss", "Gross loss", "$%"),
    ("expectancy", "Expectancy", "$"), ("commission_paid", "Commission paid", "$"), ("buy_and_hold_pnl", "Buy and hold PnL", "$"),
    ("buy_and_hold_pct_gain", "Buy and hold % gain", "%"), ("strategy_outperformance", "Strategy outperformance", "$"),
    ("max_contracts_held", "Max contracts held", "n"), ("cagr_pct", "Annualized return (CAGR)", "%"), ("return_on_initial_capital_pct", "Return on initial capital", "%"),
    ("account_size_required", "Account size required", "$"), ("return_on_account_size_required_pct", "Return on account size required", "%"),
    ("avg_margin_used", "Average margin used", "$"), ("max_margin_used", "Max margin used", "$"),
    ("avg_runup_days", "Average run-up duration (close-to-close)", "d"), ("avg_runup", "Average run-up (close-to-close)", "$%"),
    ("max_runup", "Max run-up (close-to-close)", "$%"), ("max_runup_intrabar", "Max run-up (intrabar)", "$%"),
    ("avg_drawdown_days", "Average drawdown duration (close-to-close)", "d"), ("avg_drawdown", "Average drawdown (close-to-close)", "$%"),
    ("return_of_max_drawdown", "Return of max drawdown", "x"), ("max_drawdown", "Max drawdown (close-to-close)", "$%"), ("max_drawdown_intrabar", "Max drawdown (intrabar)", "$%"),
    ("net_pnl_pct_of_largest_loss", "Net PnL as % of largest loss", "%"), ("largest_profit_pct_of_gross_profit", "Largest profit as % of gross profit", "%"),
    ("largest_loss_pct_of_gross_loss", "Largest loss as % of gross loss", "%"),
]
TRADES_ROWS = [
    ("open_trades", "Total open trades", "n"), ("total_trades", "Total trades", "n"), ("winners", "Total winners", "n"), ("losers", "Total losers", "n"),
    ("even", "Even trades", "n"), ("percent_profitable", "Percent profitable", "%"), ("expectancy", "Expectancy", "$"), ("avg_profit", "Average profit", "$"),
    ("avg_loss", "Average loss", "$"), ("avg_profit_over_avg_loss", "Average profit / average loss", "x"), ("largest_profit", "Largest profit", "$"),
    ("largest_loss", "Largest loss", "$"), ("outliers", "Outliers", "n"), ("outliers_pnl", "Outliers P&L", "$"), ("avg_bars_in_trades", "Average bars in trades", "n"),
    ("avg_bars_in_winners", "Average bars in winners", "n"), ("avg_bars_in_losers", "Average bars in losers", "n"),
]
RISK_ROWS = [("sharpe", "Sharpe ratio", "x"), ("sortino", "Sortino ratio", "x"), ("profit_factor", "Profit factor", "x"), ("margin_calls", "Margin calls", "n")]
