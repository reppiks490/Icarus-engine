"""Event-driven backtest and the statistics that decide whether an edge is real.

There is no vectorised shortcut here on purpose. The backtest drives the exact
same ``IcarusEngine.on_bar`` that a live adapter drives, bar by bar, so a
research result and a production run cannot silently diverge.

The headline number is not the equity curve. It is ``PerformanceReport.verdict``
against the permutation null: an equity curve that a shuffled tape reproduces is
not an edge, it is a drawing.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterable, Sequence

from icarus.config import AssetClass, Profile, profile_for
from icarus.data import Bar
from icarus.execution import Trade
from icarus.features.sentiment import SentimentOverlay
from icarus.strategy import IcarusEngine


@dataclass(slots=True)
class PerformanceReport:
    """Everything needed to accept or reject the system on a dataset."""

    asset_class: str
    bars: int
    trades: int
    starting_equity: float
    ending_equity: float
    net_pnl: float
    return_pct: float
    sum_r: float
    expectancy_r: float
    win_rate: float
    profit_factor: float
    average_win_r: float
    average_loss_r: float
    payoff_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    max_consecutive_losses: int
    sharpe: float
    average_bars_held: float
    exposure_pct: float
    average_mae_r: float
    average_mfe_r: float
    exit_reasons: dict[str, int] = field(default_factory=dict)
    by_direction: dict[str, dict[str, float]] = field(default_factory=dict)
    permutation_p_value: float | None = None
    permutation_runs: int = 0

    @property
    def verdict(self) -> str:
        """A blunt read on whether this result deserves capital."""
        if self.trades < 30:
            return f"INSUFFICIENT SAMPLE ({self.trades} trades) -- no conclusion"
        if self.sum_r <= 0.0:
            return "REJECT -- negative expectancy"
        if self.permutation_p_value is None:
            return "UNVALIDATED -- run the permutation test before sizing up"
        if self.permutation_p_value > 0.05:
            return f"REJECT -- indistinguishable from shuffled tape (p={self.permutation_p_value:.3f})"
        if self.expectancy_r < 0.05:
            return f"MARGINAL -- edge survives the null (p={self.permutation_p_value:.3f}) but is thin"
        return f"ACCEPT -- expectancy {self.expectancy_r:.3f}R, p={self.permutation_p_value:.3f}"

    def render(self) -> str:
        """Operator-facing summary."""
        lines = [
            f"ICARUS ENGINE -- {self.asset_class.upper()}",
            f"  bars {self.bars:,}   trades {self.trades}   exposure {self.exposure_pct:.1f}%",
            f"  equity {self.starting_equity:,.2f} -> {self.ending_equity:,.2f}  ({self.return_pct:+.2f}%)",
            f"  sumR {self.sum_r:+.2f}   expectancy {self.expectancy_r:+.3f}R   win {self.win_rate:.1f}%",
            f"  profit factor {self.profit_factor:.2f}   payoff {self.payoff_ratio:.2f}"
            f"   avg win {self.average_win_r:+.2f}R   avg loss {self.average_loss_r:+.2f}R",
            f"  max DD {self.max_drawdown:,.2f} ({self.max_drawdown_pct:.2f}%)"
            f"   max losing streak {self.max_consecutive_losses}",
            f"  Sharpe {self.sharpe:.2f}   avg hold {self.average_bars_held:.1f} bars"
            f"   MAE {self.average_mae_r:.2f}R   MFE {self.average_mfe_r:.2f}R",
        ]
        if self.exit_reasons:
            breakdown = "  ".join(f"{name}:{count}" for name, count in sorted(self.exit_reasons.items()))
            lines.append(f"  exits  {breakdown}")
        for side, stats in sorted(self.by_direction.items()):
            lines.append(
                f"  {side:5s} n={int(stats['trades']):3d}  sumR {stats['sum_r']:+.2f}"
                f"  win {stats['win_rate']:.1f}%"
            )
        if self.permutation_p_value is not None:
            lines.append(f"  permutation null: {self.permutation_runs} shuffles, p={self.permutation_p_value:.4f}")
        lines.append(f"  VERDICT: {self.verdict}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Core run
# --------------------------------------------------------------------------

def run_engine(
    bars: Sequence[Bar],
    profile: Profile | AssetClass | str = AssetClass.FUTURES,
    starting_equity: float = 100_000.0,
    sentiment: SentimentOverlay | None = None,
) -> IcarusEngine:
    """Drive the engine across a bar series and return it for inspection."""
    engine = IcarusEngine(profile, starting_equity=starting_equity, sentiment=sentiment)
    for bar in bars:
        engine.on_bar(bar)
    return engine


def _sharpe(returns: Sequence[float], periods_per_year: float) -> float:
    """Annualised Sharpe from per-trade returns. Zero when undefined."""
    if len(returns) < 2:
        return 0.0
    deviation = statistics.pstdev(returns)
    if deviation <= 0.0:
        return 0.0
    return (statistics.fmean(returns) / deviation) * math.sqrt(periods_per_year)


def summarise(
    engine: IcarusEngine,
    bars: Sequence[Bar],
    permutation_p_value: float | None = None,
    permutation_runs: int = 0,
) -> PerformanceReport:
    """Turn a finished run into a decision-grade report."""
    trades: list[Trade] = engine.blotter.trades
    starting = engine.blotter.starting_equity
    ending = engine.blotter.equity

    r_values = [trade.r for trade in trades]
    wins = [value for value in r_values if value > 0.0]
    losses = [value for value in r_values if value <= 0.0]
    gross_win = sum(trade.pnl for trade in trades if trade.pnl > 0.0)
    gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl <= 0.0))

    streak = worst_streak = 0
    for value in r_values:
        streak = streak + 1 if value <= 0.0 else 0
        worst_streak = max(worst_streak, streak)

    bars_held = sum(trade.bars_held for trade in trades)
    span = len(bars) or 1

    # Trades per year, used to annualise the per-trade Sharpe.
    if len(bars) >= 2:
        elapsed = (bars[-1].ts - bars[0].ts) or timedelta(seconds=1)
        years = max(elapsed.total_seconds() / (365.25 * 24 * 3600), 1e-9)
        trades_per_year = len(trades) / years if years > 0 else 0.0
    else:
        trades_per_year = 0.0

    by_direction: dict[str, dict[str, float]] = {}
    for side, label in ((1, "long"), (-1, "short")):
        subset = [trade for trade in trades if trade.direction == side]
        if not subset:
            continue
        side_wins = [trade for trade in subset if trade.r > 0.0]
        by_direction[label] = {
            "trades": float(len(subset)),
            "sum_r": sum(trade.r for trade in subset),
            "win_rate": 100.0 * len(side_wins) / len(subset),
        }

    return PerformanceReport(
        asset_class=engine.profile.asset_class.value,
        bars=len(bars),
        trades=len(trades),
        starting_equity=starting,
        ending_equity=ending,
        net_pnl=ending - starting,
        return_pct=100.0 * (ending - starting) / starting if starting else 0.0,
        sum_r=sum(r_values),
        expectancy_r=statistics.fmean(r_values) if r_values else 0.0,
        win_rate=100.0 * len(wins) / len(trades) if trades else 0.0,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        average_win_r=statistics.fmean(wins) if wins else 0.0,
        average_loss_r=statistics.fmean(losses) if losses else 0.0,
        payoff_ratio=(abs(statistics.fmean(wins) / statistics.fmean(losses))
                      if wins and losses and statistics.fmean(losses) != 0 else 0.0),
        max_drawdown=engine.blotter.max_drawdown,
        max_drawdown_pct=100.0 * engine.blotter.max_drawdown / starting if starting else 0.0,
        max_consecutive_losses=worst_streak,
        sharpe=_sharpe(r_values, trades_per_year),
        average_bars_held=bars_held / len(trades) if trades else 0.0,
        exposure_pct=100.0 * bars_held / span,
        average_mae_r=statistics.fmean([trade.mae_r for trade in trades]) if trades else 0.0,
        average_mfe_r=statistics.fmean([trade.mfe_r for trade in trades]) if trades else 0.0,
        exit_reasons=dict(Counter(trade.reason_out for trade in trades)),
        by_direction=by_direction,
        permutation_p_value=permutation_p_value,
        permutation_runs=permutation_runs,
    )


# --------------------------------------------------------------------------
# The null hypothesis
# --------------------------------------------------------------------------

def shuffle_bars(bars: Sequence[Bar], rng: random.Random) -> list[Bar]:
    """Rebuild a tape from the same bars in a shuffled order.

    Bar-internal shape (range, wick asymmetry, volume, delta) is preserved and
    re-anchored to a rolling price, so the surrogate keeps the distribution of
    returns while destroying the sequence. Anything the engine still 'finds'
    in that tape is pattern-matching on noise.
    """
    order = list(range(len(bars)))
    rng.shuffle(order)
    out: list[Bar] = []
    price = bars[0].open
    for position, source_index in enumerate(order):
        source = bars[source_index]
        if source.open <= 0:
            continue
        scale = price / source.open
        out.append(
            Bar(
                ts=bars[position].ts,                 # keep the original clock
                open=source.open * scale,
                high=source.high * scale,
                low=source.low * scale,
                close=source.close * scale,
                volume=source.volume,
                bid_volume=source.bid_volume,
                ask_volume=source.ask_volume,
            )
        )
        price = out[-1].close
    return out


def permutation_test(
    bars: Sequence[Bar],
    profile: Profile | AssetClass | str,
    observed_sum_r: float,
    runs: int = 50,
    starting_equity: float = 100_000.0,
    seed: int = 1,
) -> float:
    """Fraction of shuffled tapes that match or beat the observed sumR.

    This is the p-value. Below 0.05 the result is unlikely to be luck; above
    it, the strategy is reading tea leaves and should not be sized up.
    """
    if runs <= 0:
        raise ValueError("runs must be >= 1")
    rng = random.Random(seed)
    at_least_as_good = 0
    for _ in range(runs):
        surrogate = shuffle_bars(bars, rng)
        engine = run_engine(surrogate, profile, starting_equity=starting_equity)
        null_sum_r = sum(trade.r for trade in engine.blotter.trades)
        if null_sum_r >= observed_sum_r:
            at_least_as_good += 1
    # +1 in numerator and denominator: the observed run is itself one sample,
    # which keeps the p-value from ever collapsing to a dishonest zero.
    return (at_least_as_good + 1) / (runs + 1)


def backtest(
    bars: Sequence[Bar],
    profile: Profile | AssetClass | str = AssetClass.FUTURES,
    starting_equity: float = 100_000.0,
    sentiment: SentimentOverlay | None = None,
    permutations: int = 0,
    seed: int = 1,
) -> PerformanceReport:
    """Run the engine and report. Pass ``permutations`` to test against the null."""
    bars = list(bars)
    if not bars:
        raise ValueError("no bars supplied")
    engine = run_engine(bars, profile, starting_equity=starting_equity, sentiment=sentiment)
    observed = sum(trade.r for trade in engine.blotter.trades)
    p_value = None
    if permutations > 0:
        p_value = permutation_test(bars, profile, observed, runs=permutations,
                                   starting_equity=starting_equity, seed=seed)
    return summarise(engine, bars, permutation_p_value=p_value, permutation_runs=permutations)


def walk_forward(
    bars: Sequence[Bar],
    profile: Profile | AssetClass | str = AssetClass.FUTURES,
    folds: int = 4,
    starting_equity: float = 100_000.0,
) -> list[PerformanceReport]:
    """Split the tape into contiguous folds and report each independently.

    Contiguous, never shuffled: an intraday system must survive regime change,
    and a randomly-sampled fold hides exactly that failure mode.
    """
    bars = list(bars)
    if folds < 2:
        raise ValueError("folds must be >= 2")
    size = len(bars) // folds
    if size < 100:
        raise ValueError(f"folds too small ({size} bars each) -- supply more data or fewer folds")
    reports: list[PerformanceReport] = []
    for fold in range(folds):
        start = fold * size
        end = len(bars) if fold == folds - 1 else start + size
        window = bars[start:end]
        engine = run_engine(window, profile, starting_equity=starting_equity)
        reports.append(summarise(engine, window))
    return reports
