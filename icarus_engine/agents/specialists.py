from __future__ import annotations

import math

from .contracts import AgentVerdict, CandidateEvidence, clamp01, stability_score


def _confidence(e: CandidateEvidence) -> float:
    sample = 1.0 - math.exp(-e.trade_count / 250.0)
    coverage = min(e.provenance_coverage, e.point_in_time_coverage)
    return clamp01(0.45 * sample + 0.35 * coverage + 0.20 * e.probabilistic_sharpe)


class RobustnessGuardianAgent:
    """Fail-closed defense against leakage, overfit, fragile costs and regime collapse."""

    name = "robustness-guardian"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        hard = []
        if e.lookahead_flags:
            hard.append("lookahead evidence present")
        if e.holdout_touched:
            hard.append("protected holdout was touched")
        if e.provenance_coverage < 0.99:
            hard.append("insufficient provenance coverage")
        if e.point_in_time_coverage < 0.99:
            hard.append("insufficient point-in-time coverage")
        if e.oos_windows < 3 or e.regime_count < 3:
            hard.append("insufficient out-of-sample/regime breadth")
        if e.replay_determinism < 0.99:
            hard.append("deterministic replay evidence below 99%")
        if e.net_expectancy_lcb_bps <= 0:
            hard.append("net expectancy lower bound is non-positive")
        if e.stressed_net_expectancy_bps <= 0:
            hard.append("edge does not survive execution-cost stress")
        if hard:
            return AgentVerdict(self.name, "reject", 0.0, _confidence(e), True, tuple(hard))

        dsr = clamp01((e.deflated_sharpe - 0.25) / 1.25)
        sample = 1.0 - math.exp(-e.trade_count / 250.0)
        stress_retention = clamp01(e.stressed_net_expectancy_bps / max(e.net_expectancy_bps, 1e-9))
        regime = stability_score(e.regime_returns, 0.18)
        walk = stability_score(e.walkforward_returns, 0.08)
        drawdown = clamp01(1.0 - e.max_drawdown / 0.40)
        quality_penalty = min(0.20, 0.04 * len(e.data_quality_flags))
        score = clamp01(
            0.16 * dsr
            + 0.10 * e.probabilistic_sharpe
            + 0.10 * sample
            + 0.10 * stress_retention
            + 0.10 * regime
            + 0.08 * walk
            + 0.10 * e.perturbation_pass_rate
            + 0.10 * e.parameter_stability
            + 0.06 * drawdown
            + 0.05 * e.provenance_coverage
            + 0.03 * e.point_in_time_coverage
            + 0.02 * (1.0 - e.probability_backtest_overfit)
            - quality_penalty
        )
        decision = "promote" if score >= 0.70 else "hold" if score >= 0.55 else "reject"
        reasons = (
            f"deflated_sharpe={e.deflated_sharpe:.3f}",
            f"stress_retention={stress_retention:.3f}",
            f"regime_stability={regime:.3f}",
            f"walkforward_stability={walk:.3f}",
        )
        return AgentVerdict(self.name, decision, score, _confidence(e), False, reasons)


class AlphaSynthesisAgent:
    """Scores profitability only after costs, uncertainty, drawdown, capacity and correlation."""

    name = "alpha-synthesis"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        hard = []
        if e.net_expectancy_lcb_bps <= 0:
            hard.append("lower-confidence-bound expectancy is non-positive")
        if e.stressed_net_expectancy_bps <= 0:
            hard.append("profitability disappears under stressed costs/slippage")
        if hard:
            return AgentVerdict(self.name, "reject", 0.0, _confidence(e), True, tuple(hard))

        ret = clamp01(e.annualized_return / 0.30)
        lcb = clamp01(e.net_expectancy_lcb_bps / 5.0)
        stress = clamp01(e.stressed_net_expectancy_bps / max(e.net_expectancy_bps, 1e-9))
        dsr = clamp01((e.deflated_sharpe - 0.20) / 1.20)
        drawdown_eff = clamp01(e.annualized_return / max(2.0 * e.max_drawdown, 1e-9))
        tail = clamp01(1.0 - e.expected_shortfall / 0.20)
        diversification = clamp01(1.0 - e.max_strategy_correlation)
        capacity = clamp01(1.0 - e.capacity_utilization)
        score = clamp01(
            0.16 * ret
            + 0.14 * lcb
            + 0.12 * stress
            + 0.13 * dsr
            + 0.10 * e.probabilistic_sharpe
            + 0.10 * drawdown_eff
            + 0.08 * tail
            + 0.07 * diversification
            + 0.05 * capacity
            + 0.03 * e.parameter_stability
            + 0.02 * e.bootstrap_positive_rate
        )
        decision = "promote" if score >= 0.68 else "hold" if score >= 0.52 else "reject"
        reasons = (
            f"net_lcb_bps={e.net_expectancy_lcb_bps:.3f}",
            f"stressed_net_bps={e.stressed_net_expectancy_bps:.3f}",
            f"drawdown_efficiency={drawdown_eff:.3f}",
            f"diversification={diversification:.3f}",
        )
        return AgentVerdict(self.name, decision, score, _confidence(e), False, reasons)


class DataIntegrityAgent:
    name = "data-integrity"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        problems = []
        if e.lookahead_flags:
            problems.append("lookahead flags")
        if e.holdout_touched:
            problems.append("holdout touched")
        if e.point_in_time_coverage < 0.995:
            problems.append("point-in-time coverage below 99.5%")
        if e.replay_determinism < 0.99:
            problems.append("deterministic replay below 99%")
        if e.provenance_coverage < 0.995:
            problems.append("provenance coverage below 99.5%")
        severe = tuple(flag for flag in e.data_quality_flags if flag.startswith(("leakage", "corrupt", "unresolved")))
        problems.extend(severe)
        if problems:
            return AgentVerdict(self.name, "reject", 0.0, min(e.provenance_coverage, e.point_in_time_coverage), True, tuple(problems))
        score = clamp01(min(e.provenance_coverage, e.point_in_time_coverage, e.replay_determinism) - 0.03 * len(e.data_quality_flags))
        return AgentVerdict(self.name, "promote" if score >= 0.90 else "hold", score, score, False,
                            ("point-in-time and provenance gates clear",))


class RegimeSentinelAgent:
    name = "regime-sentinel"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        if e.regime_count < 3:
            return AgentVerdict(self.name, "reject", 0.0, 0.5, True, ("fewer than three regimes",))
        worst = min(e.regime_returns)
        positive = sum(v > 0 for v in e.regime_returns) / len(e.regime_returns)
        stability = stability_score(e.regime_returns, 0.18)
        score = clamp01(0.55 * stability + 0.45 * positive)
        veto = worst < -0.25
        decision = "reject" if veto else "promote" if score >= 0.70 else "hold" if score >= 0.50 else "reject"
        return AgentVerdict(self.name, decision, score, _confidence(e), veto,
                            (f"worst_regime={worst:.4f}", f"positive_regime_fraction={positive:.3f}"))


class ExecutionSentinelAgent:
    name = "execution-sentinel"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        if e.stressed_net_expectancy_bps <= 0:
            return AgentVerdict(self.name, "reject", 0.0, _confidence(e), True,
                                ("stressed execution turns edge non-positive",))
        if e.cost_model_coverage < 0.95:
            return AgentVerdict(self.name, "reject", 0.0, _confidence(e), True,
                                ("cost-model coverage below 95%",))
        if e.latency_stress_pass_rate < 0.60:
            return AgentVerdict(self.name, "reject", 0.0, _confidence(e), True,
                                ("latency stress pass rate below 60%",))
        retention = clamp01(e.stressed_net_expectancy_bps / max(e.net_expectancy_bps, 1e-9))
        capacity = clamp01(1.0 - e.capacity_utilization)
        score = clamp01(0.30 + 0.20 * retention + 0.15 * capacity + 0.15 * e.cost_model_coverage + 0.20 * e.latency_stress_pass_rate)
        decision = "promote" if score >= 0.70 else "hold"
        return AgentVerdict(self.name, decision, score, _confidence(e), False,
                            (f"stress_retention={retention:.3f}", f"capacity_headroom={capacity:.3f}"))


class TailRiskSentinelAgent:
    name = "tail-risk-sentinel"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        veto = e.max_drawdown > 0.35 or e.expected_shortfall > 0.20
        dd = clamp01(1.0 - e.max_drawdown / 0.40)
        es = clamp01(1.0 - e.expected_shortfall / 0.20)
        score = 0.55 * dd + 0.45 * es
        decision = "reject" if veto else "promote" if score >= 0.68 else "hold" if score >= 0.45 else "reject"
        reasons = (f"max_drawdown={e.max_drawdown:.4f}", f"expected_shortfall={e.expected_shortfall:.4f}")
        return AgentVerdict(self.name, decision, clamp01(score), _confidence(e), veto, reasons)


class AdversarialSentinelAgent:
    name = "adversarial-sentinel"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        veto = e.perturbation_pass_rate < 0.65 or e.parameter_stability < 0.50
        score = 0.55 * e.perturbation_pass_rate + 0.45 * e.parameter_stability
        decision = "reject" if veto else "promote" if score >= 0.78 else "hold" if score >= 0.60 else "reject"
        return AgentVerdict(self.name, decision, clamp01(score), _confidence(e), veto,
                            (f"perturbation_pass_rate={e.perturbation_pass_rate:.3f}",
                             f"parameter_stability={e.parameter_stability:.3f}"))


class CalibrationSentinelAgent:
    name = "calibration-sentinel"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        veto = e.calibration_error > 0.25
        score = clamp01(1.0 - e.calibration_error / 0.20)
        decision = "reject" if veto else "promote" if score >= 0.75 else "hold" if score >= 0.40 else "reject"
        return AgentVerdict(self.name, decision, score, _confidence(e), veto,
                            (f"calibration_error={e.calibration_error:.4f}",))


class MultipleTestingSentinelAgent:
    name = "multiple-testing-sentinel"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        veto = e.probability_backtest_overfit > 0.50 or e.deflated_sharpe <= 0.0
        pbo_score = clamp01(1.0 - e.probability_backtest_overfit)
        dsr = clamp01((e.deflated_sharpe - 0.15) / 1.20)
        trial_pressure = clamp01(1.0 - math.log1p(max(0, e.trials - 1)) / 10.0)
        score = clamp01(0.50 * pbo_score + 0.35 * dsr + 0.15 * trial_pressure)
        decision = "reject" if veto else "promote" if score >= 0.72 else "hold" if score >= 0.50 else "reject"
        return AgentVerdict(self.name, decision, score, _confidence(e), veto,
                            (f"pbo={e.probability_backtest_overfit:.3f}",
                             f"trials={e.trials}", f"deflated_sharpe={e.deflated_sharpe:.3f}"))


class OODSentinelAgent:
    name = "ood-sentinel"

    def evaluate(self, e: CandidateEvidence) -> AgentVerdict:
        veto = e.ood_stability < 0.50 or e.bootstrap_positive_rate < 0.60
        score = clamp01(0.60 * e.ood_stability + 0.40 * e.bootstrap_positive_rate)
        decision = "reject" if veto else "promote" if score >= 0.78 else "hold" if score >= 0.60 else "reject"
        return AgentVerdict(self.name, decision, score, _confidence(e), veto,
                            (f"ood_stability={e.ood_stability:.3f}",
                             f"bootstrap_positive_rate={e.bootstrap_positive_rate:.3f}"))
