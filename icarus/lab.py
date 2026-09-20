"""The comparison bench: Pulse vs Suite vs Hybrid, across timeframes.

This module exists to answer one question with numbers instead of opinion:
**does the Suite's exit model actually beat the engine's, and does the hybrid
beat both?** It runs the identical entry engine under different exit policies on
the identical tape, so every difference in the output is attributable to the
exit layer and nothing else.

What it reports, beyond the usual P&L statistics:

  * ``same_bar_pct``   -- trades that died on the bar they opened
  * ``median_hold``    -- the number the whole exercise is about
  * ``stop_pct``       -- how stop-dominated the policy is
  * ``median_risk_atr``-- how much room the stop was actually given
  * ``mfe_capture``    -- realised R divided by maximum favourable excursion,
    i.e. how much of the move the exit actually kept
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence

from icarus.backtest import PerformanceReport, permutation_test, summarise
from icarus.config import AssetClass, Profile, profile_for
from icarus.data import Bar
from icarus.exits import ExitPolicy
from icarus.strategy import IcarusEngine
from icarus.timeframe import at_timeframe, parse_timeframe, resample


@dataclass(slots=True)
class HoldStats:
    """Exit-behaviour statistics -- the part a P&L summary hides."""

    trades: int
    same_bar_pct: float
    within_one_bar_pct: float
    median_hold: float
    mean_hold: float
    p90_hold: float
    stop_pct: float
    median_risk_atr: float
    mean_mfe_r: float
    mean_mae_r: float
    mfe_capture: float
    exit_mix: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyResult:
    """One policy, on one timeframe, on one tape."""

    policy: str
    timeframe: str
    report: PerformanceReport
    holds: HoldStats

    def row(self) -> str:
        report, holds = self.report, self.holds
        profit_factor = "inf" if report.profit_factor == float("inf") else f"{report.profit_factor:.2f}"
        return (
            f"{self.policy:7s} {self.timeframe:>5s} {report.trades:5d} "
            f"{holds.median_hold:7.1f} {holds.same_bar_pct:8.1f} {holds.stop_pct:7.1f} "
            f"{holds.median_risk_atr:8.2f} {report.sum_r:+8.2f} {report.expectancy_r:+9.3f} "
            f"{report.win_rate:6.1f} {profit_factor:>6s} {holds.mfe_capture:8.2f} "
            f"{report.max_drawdown_pct:7.2f}"
        )


HEADER = (
    f"{'policy':7s} {'tf':>5s} {'n':>5s} {'medHold':>7s} {'sameBar%':>8s} {'stop%':>7s} "
    f"{'riskATR':>8s} {'sumR':>8s} {'expR':>9s} {'win%':>6s} {'PF':>6s} {'MFEcap':>8s} {'maxDD%':>7s}"
)


def hold_stats(engine: IcarusEngine, risk_atrs: Sequence[float]) -> HoldStats:
    """Summarise how the policy actually behaved, not just what it earned."""
    trades = engine.blotter.trades
    if not trades:
        return HoldStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, {})

    holds = [trade.bars_held for trade in trades]
    ordered = sorted(holds)
    p90 = ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
    stops = sum(1 for trade in trades if trade.reason_out == "stop")

    # How much of the best price the trade ever saw did the exit actually keep?
    captures = [trade.r / trade.mfe_r for trade in trades if trade.mfe_r > 0.05]

    return HoldStats(
        trades=len(trades),
        same_bar_pct=100.0 * sum(1 for h in holds if h == 0) / len(holds),
        within_one_bar_pct=100.0 * sum(1 for h in holds if h <= 1) / len(holds),
        median_hold=statistics.median(holds),
        mean_hold=statistics.fmean(holds),
        p90_hold=float(p90),
        stop_pct=100.0 * stops / len(trades),
        median_risk_atr=statistics.median(risk_atrs) if risk_atrs else 0.0,
        mean_mfe_r=statistics.fmean([t.mfe_r for t in trades]),
        mean_mae_r=statistics.fmean([t.mae_r for t in trades]),
        mfe_capture=statistics.fmean(captures) if captures else 0.0,
        exit_mix=dict(Counter(trade.reason_out for trade in trades)),
    )


def run_policy(
    bars: Sequence[Bar],
    profile: Profile,
    policy: str | ExitPolicy,
    timeframe: str | int | None = None,
    starting_equity: float = 100_000.0,
    htf: str | int = "4h",
) -> tuple[IcarusEngine, list[float]]:
    """Drive one policy over one tape, capturing stop distance at every entry."""
    engine = IcarusEngine(profile, starting_equity=starting_equity, exit_policy=policy,
                          timeframe=timeframe, htf=htf)
    risk_atrs: list[float] = []
    original = engine._open_position

    def instrumented(bar, pending, _o=original, _e=engine, _r=risk_atrs):
        intent = _o(bar, pending)
        if intent is not None and _e.position is not None and pending.atr > 0:
            _r.append(_e.position.risk_unit / pending.atr)
        return intent

    engine._open_position = instrumented
    for bar in bars:
        engine.on_bar(bar)
    return engine, risk_atrs


def compare(
    bars: Sequence[Bar],
    asset: AssetClass | str = AssetClass.MICRO_FUTURES,
    policies: Sequence[str] = ("pulse", "suite", "hybrid"),
    timeframes: Sequence[str | int] | None = None,
    starting_equity: float = 100_000.0,
    permutations: int = 0,
    seed: int = 3,
    htf: str | int = "4h",
) -> list[PolicyResult]:
    """Cross-examine every policy on every timeframe, on the same source tape.

    ``bars`` are the finest-grained bars available; each timeframe is built by
    resampling them, so no policy ever sees data another did not.
    """
    base = profile_for(asset)
    frames = list(timeframes) if timeframes else [base.base_timeframe_min]
    results: list[PolicyResult] = []

    for frame in frames:
        minutes = parse_timeframe(frame)
        tape = resample(bars, minutes)
        if len(tape) < 300:
            raise ValueError(f"{minutes}m tape has only {len(tape)} bars -- supply more data")
        label = f"{minutes}m"
        for policy in policies:
            engine, risk_atrs = run_policy(tape, base, policy, timeframe=minutes,
                                           starting_equity=starting_equity, htf=htf)
            observed = sum(trade.r for trade in engine.blotter.trades)
            p_value = None
            if permutations > 0:
                scoped = at_timeframe(base, minutes)
                p_value = _policy_permutation(tape, scoped, policy, observed, permutations,
                                              starting_equity, seed, htf)
            report = summarise(engine, tape, permutation_p_value=p_value,
                               permutation_runs=permutations)
            results.append(PolicyResult(policy=str(policy), timeframe=label, report=report,
                                        holds=hold_stats(engine, risk_atrs)))
    return results


def _policy_permutation(tape, profile, policy, observed, runs, equity, seed, htf) -> float:
    """Permutation null, run under the same exit policy as the observed result."""
    import random

    from icarus.backtest import shuffle_bars

    rng = random.Random(seed)
    beats = 0
    for _ in range(runs):
        surrogate = shuffle_bars(tape, rng)
        engine = IcarusEngine(profile, starting_equity=equity, exit_policy=policy, htf=htf)
        for bar in surrogate:
            engine.on_bar(bar)
        if sum(trade.r for trade in engine.blotter.trades) >= observed:
            beats += 1
    return (beats + 1) / (runs + 1)


def render(results: Sequence[PolicyResult], title: str = "") -> str:
    """Operator-facing comparison table."""
    lines = []
    if title:
        lines.append(title)
    lines.append(HEADER)
    lines.append("-" * len(HEADER))
    lines.extend(result.row() for result in results)

    ranked = [r for r in results if r.report.trades >= 20]
    if ranked:
        best = max(ranked, key=lambda r: r.report.expectancy_r)
        lines.append("")
        lines.append(f"best expectancy (>=20 trades): {best.policy} @ {best.timeframe} "
                     f"-> {best.report.expectancy_r:+.3f}R over {best.report.trades} trades")
    for result in results:
        if result.report.permutation_p_value is not None:
            lines.append(f"  {result.policy:7s} {result.timeframe:>5s}  {result.report.verdict}")
    return "\n".join(lines)
