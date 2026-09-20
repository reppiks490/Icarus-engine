"""Full characterisation of a trading result.

Headline expectancy and win rate describe almost nothing. A system can post a
90% win rate and be a slow bankruptcy; it can post 45% and be excellent. What
separates them lives in the shape of the distribution, the stability of that
shape over time, and whether it survives on data it was never fitted to.

Five families, each answering a question the others cannot:

  EDGE        is there an edge, and how large
  CONSISTENCY is it the same edge in month six as in month one
  RISK        what does it cost to hold, and how bad does it get
  EXECUTION   is it physically tradeable, or an artefact of the fill model
  VALIDITY    would this result survive if the sequence were destroyed

Legs are grouped by ``entry_bar``. ``entry_id`` is a Pine strategy label --
"Long", "Short" -- reused across every trade, so grouping by it silently merges
unrelated positions.
"""

from __future__ import annotations

import math
import statistics as st
from dataclasses import asdict, dataclass, field
from collections import Counter, defaultdict


# ---------------------------------------------------------------------------
# Position assembly
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Position:
    """One entry and every leg that closed out of it."""

    entry_bar: int
    direction: int
    entry_ts: int
    legs: list = field(default_factory=list)

    @property
    def profit(self) -> float:
        return sum(leg.profit for leg in self.legs)

    @property
    def first_leg(self):
        return self.legs[0]

    @property
    def runner_legs(self) -> list:
        return self.legs[1:]

    @property
    def bars_held(self) -> int:
        return max(leg.exit_bar for leg in self.legs) - self.entry_bar

    @property
    def runup(self) -> float:
        return max((leg.runup for leg in self.legs), default=0.0)

    @property
    def drawdown(self) -> float:
        return min((leg.drawdown for leg in self.legs), default=0.0)


@dataclass(slots=True)
class _IcarusLeg:
    """`icarus.execution.Trade` wearing the shape `assemble` expects.

    The two engines log closed trades differently: Astra's emulator mirrors
    Pine and records bar indices plus currency excursions, while `icarus/`
    records timestamps and excursions in R. Rather than fork the metrics, the
    narrower record is widened here -- bar indices come from the tape's own
    ordering, and R is converted to currency through the trade's own realised
    R-per-dollar so MFE capture stays a pure ratio.
    """

    direction: int
    entry_bar: int
    exit_bar: int
    entry_ts: float
    exit_ts: float
    profit: float
    runup: float
    drawdown: float
    exit_comment: str


def from_icarus(trades, bars) -> list:
    """Adapt `icarus/` trades onto the leg interface `assemble` consumes."""
    index_of = {bar.ts: i for i, bar in enumerate(bars)}
    legs = []
    for trade in trades:
        entry_bar = index_of.get(trade.entry_ts, 0)
        exit_bar = index_of.get(trade.exit_ts, entry_bar + max(trade.bars_held, 0))
        # pnl / r is dollars-per-R for THIS trade; it recovers the currency
        # scale that mfe_r and mae_r were divided by. A scratch trade (r == 0)
        # has no scale to recover, so its excursions stay at zero rather than
        # being invented.
        per_r = trade.pnl / trade.r if trade.r else 0.0
        legs.append(
            _IcarusLeg(
                direction=trade.direction,
                entry_bar=entry_bar,
                exit_bar=exit_bar,
                entry_ts=trade.entry_ts.timestamp(),
                exit_ts=trade.exit_ts.timestamp(),
                profit=trade.pnl,
                runup=trade.mfe_r * per_r,
                drawdown=trade.mae_r * per_r,
                exit_comment=trade.reason_out,
            )
        )
    return legs


def assemble(closed) -> list[Position]:
    """Group closed legs into positions, keyed on the bar the entry filled."""
    grouped: dict[int, Position] = {}
    for leg in closed:
        pos = grouped.get(leg.entry_bar)
        if pos is None:
            pos = grouped[leg.entry_bar] = Position(leg.entry_bar, leg.direction, leg.entry_ts)
        pos.legs.append(leg)
    for pos in grouped.values():
        pos.legs.sort(key=lambda leg: (leg.exit_bar, leg.exit_ts))
    return [grouped[k] for k in sorted(grouped)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b else default


def _pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def _max_streak(flags: list[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def _run_lengths(flags: list[bool]) -> tuple[list[int], list[int]]:
    """Every consecutive run, split into True-runs and False-runs.

    Max streak alone is a single observation and mostly noise. The mean run
    length says whether wins genuinely cluster or one lucky sequence flattered
    the maximum.
    """
    wins: list[int] = []
    losses: list[int] = []
    if not flags:
        return wins, losses
    current, run = flags[0], 1
    for flag in flags[1:]:
        if flag == current:
            run += 1
        else:
            (wins if current else losses).append(run)
            current, run = flag, 1
    (wins if current else losses).append(run)
    return wins, losses


def _drawdown_curve(profits: list[float]) -> tuple[float, int, float]:
    """Peak-to-trough on the cumulative curve: depth, duration in trades, ulcer index."""
    equity = peak = 0.0
    depth = 0.0
    longest = current = 0
    squares = []
    for profit in profits:
        equity += profit
        if equity > peak:
            peak, current = equity, 0
        else:
            current += 1
            longest = max(longest, current)
        drop = peak - equity
        depth = max(depth, drop)
        squares.append((_safe_div(drop, peak) * 100.0) ** 2 if peak > 0 else 0.0)
    ulcer = math.sqrt(st.fmean(squares)) if squares else 0.0
    return depth, longest, ulcer


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Report:
    # --- EDGE -------------------------------------------------------------
    trades: int = 0
    net: float = 0.0
    expectancy: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    payoff_ratio: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0

    # --- CONSISTENCY ------------------------------------------------------
    # The operator's stated priority. A system whose edge is concentrated in a
    # handful of trades, or in one month, is not the system it appears to be.
    block_expectancies: list = field(default_factory=list)
    consistency: float = 0.0        # 1 - (std/|mean|) across blocks, floored at 0
    positive_block_rate: float = 0.0
    top_trade_share: float = 0.0    # share of net profit from the single best trade
    top_decile_share: float = 0.0   # ...from the best 10% of trades
    gini: float = 0.0               # inequality of the profit distribution
    max_losing_streak: int = 0
    max_winning_streak: int = 0
    mean_winning_run: float = 0.0
    mean_losing_run: float = 0.0
    streak_ratio: float = 0.0       # max winning streak / max losing streak
    mean_run_ratio: float = 0.0     # mean winning run / mean losing run
    streak_vs_random: float = 0.0   # observed losing streak / binomial expectation

    # --- LEG STRUCTURE ----------------------------------------------------
    tp1_rate: float = 0.0
    tp2_rate: float = 0.0
    tp_gap_pp: float = 0.0
    runner_legs: int = 0
    runner_win_rate: float | None = None
    runner_breakeven_rate: float | None = None
    runner_expectancy: float | None = None
    runner_share_of_net: float | None = None

    # --- RISK -------------------------------------------------------------
    max_drawdown: float = 0.0
    max_drawdown_trades: int = 0
    ulcer_index: float = 0.0
    recovery_factor: float = 0.0
    tail_ratio: float = 0.0
    worst_case_loss: float = 0.0

    # --- EXECUTION --------------------------------------------------------
    mean_hold: float = 0.0
    median_hold: float = 0.0
    same_bar_rate: float = 0.0
    trades_per_day: float = 0.0
    mfe_capture: float = 0.0        # realised / best-available, per position
    mae_ratio: float = 0.0          # how much heat per unit of result
    edge_ratio: float = 0.0         # mean MFE / mean |MAE|

    exits: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def analyse(closed, *, span_days: float = 0.0, block_size: int = 25) -> Report:
    """Characterise a finished run. ``closed`` is a list of ClosedTrade."""
    report = Report()
    positions = assemble(closed)
    if not positions:
        return report

    profits = [p.profit for p in positions]
    wins = [x for x in profits if x > 0.0]
    losses = [x for x in profits if x < 0.0]
    flats = [x for x in profits if x == 0.0]
    n = len(positions)

    # --- EDGE -------------------------------------------------------------
    report.trades = n
    report.net = sum(profits)
    report.expectancy = st.fmean(profits)
    report.win_rate = _pct(len(wins), n)
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    report.profit_factor = _safe_div(gross_win, gross_loss, float("inf") if gross_win else 0.0)
    report.avg_win = st.fmean(wins) if wins else 0.0
    report.avg_loss = st.fmean(losses) if losses else 0.0
    report.payoff_ratio = _safe_div(report.avg_win, abs(report.avg_loss))
    report.largest_win = max(profits)
    report.largest_loss = min(profits)

    # --- CONSISTENCY ------------------------------------------------------
    blocks = [profits[i:i + block_size] for i in range(0, n, block_size)]
    blocks = [b for b in blocks if len(b) >= max(5, block_size // 3)]
    if blocks:
        means = [st.fmean(b) for b in blocks]
        report.block_expectancies = [round(m, 2) for m in means]
        report.positive_block_rate = _pct(sum(1 for m in means if m > 0), len(means))
        if len(means) > 1 and st.fmean(means) != 0:
            cv = st.pstdev(means) / abs(st.fmean(means))
            report.consistency = max(0.0, 1.0 - cv)

    if report.net > 0:
        ordered = sorted(profits, reverse=True)
        report.top_trade_share = _pct(int(ordered[0]), int(report.net)) if report.net else 0.0
        top_decile = ordered[: max(1, n // 10)]
        report.top_decile_share = 100.0 * sum(top_decile) / report.net

    # Gini over the profit distribution: 0 = every trade contributes equally,
    # 1 = one trade is the entire result.
    shifted = sorted(x - min(profits) for x in profits)
    total = sum(shifted)
    if total > 0:
        cumulative = sum((i + 1) * x for i, x in enumerate(shifted))
        report.gini = (2.0 * cumulative) / (n * total) - (n + 1.0) / n

    report.max_losing_streak = _max_streak([x <= 0 for x in profits])
    report.max_winning_streak = _max_streak([x > 0 for x in profits])
    report.streak_ratio = _safe_div(report.max_winning_streak,
                                    max(report.max_losing_streak, 1))
    win_runs, lose_runs = _run_lengths([x > 0 for x in profits])
    report.mean_winning_run = st.fmean(win_runs) if win_runs else 0.0
    report.mean_losing_run = st.fmean(lose_runs) if lose_runs else 0.0
    report.mean_run_ratio = _safe_div(report.mean_winning_run,
                                      max(report.mean_losing_run, 1e-9))
    loss_p = _safe_div(len(losses) + len(flats), n)
    if 0.0 < loss_p < 1.0 and n > 1:
        expected = math.log(n * (1 - loss_p)) / -math.log(loss_p) if loss_p > 0 else 0.0
        report.streak_vs_random = _safe_div(report.max_losing_streak, max(expected, 1e-9))

    # --- LEG STRUCTURE ----------------------------------------------------
    tp1 = sum(1 for p in positions if p.first_leg.exit_comment.endswith("TP1"))
    tp2 = sum(1 for p in positions
              if any(leg.exit_comment.endswith("TP2") for leg in p.runner_legs))
    report.tp1_rate, report.tp2_rate = _pct(tp1, n), _pct(tp2, n)
    report.tp_gap_pp = abs(report.tp1_rate - report.tp2_rate)

    runners = [leg for p in positions for leg in p.runner_legs]
    report.runner_legs = len(runners)
    if runners:
        rw = [leg for leg in runners if leg.profit > 0.0]
        rf = [leg for leg in runners if leg.profit == 0.0]
        report.runner_win_rate = _pct(len(rw), len(runners))
        report.runner_breakeven_rate = _pct(len(rf), len(runners))
        report.runner_expectancy = st.fmean([leg.profit for leg in runners])
        if report.net:
            report.runner_share_of_net = 100.0 * sum(leg.profit for leg in runners) / report.net

    # --- RISK -------------------------------------------------------------
    depth, longest, ulcer = _drawdown_curve(profits)
    report.max_drawdown = depth
    report.max_drawdown_trades = longest
    report.ulcer_index = ulcer
    report.recovery_factor = _safe_div(report.net, depth)
    if len(profits) >= 20:
        ordered = sorted(profits)
        p95 = ordered[int(0.95 * (n - 1))]
        p05 = ordered[int(0.05 * (n - 1))]
        report.tail_ratio = _safe_div(abs(p95), abs(p05))
    report.worst_case_loss = min(profits)

    # --- EXECUTION --------------------------------------------------------
    holds = [p.bars_held for p in positions]
    report.mean_hold = st.fmean(holds)
    report.median_hold = st.median(holds)
    report.same_bar_rate = _pct(sum(1 for h in holds if h <= 0), n)
    report.trades_per_day = _safe_div(n, span_days)

    runups = [p.runup for p in positions]
    draws = [abs(p.drawdown) for p in positions]
    captures = [_safe_div(p.profit, p.runup) for p in positions if p.runup > 0]
    if captures:
        report.mfe_capture = st.fmean(captures)
    report.edge_ratio = _safe_div(st.fmean(runups), st.fmean(draws)) if draws else 0.0
    report.mae_ratio = _safe_div(st.fmean(draws), abs(report.expectancy)) if report.expectancy else 0.0

    report.exits = dict(Counter(leg.exit_comment for leg in closed).most_common(10))
    return report
