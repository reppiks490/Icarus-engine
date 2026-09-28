import math
import pytest

from icarus_engine.agents import (
    ApexCouncilAgent,
    AlphaSynthesisAgent,
    CandidateEvidence,
    EvidenceError,
    RobustnessGuardianAgent,
)


def strong(**overrides):
    values = dict(
        candidate_id="candidate-001",
        trials=24,
        trade_count=480,
        oos_windows=8,
        regime_count=5,
        annualized_return=0.24,
        gross_expectancy_bps=9.0,
        net_expectancy_bps=6.0,
        net_expectancy_lcb_bps=3.2,
        stressed_net_expectancy_bps=1.8,
        sharpe=1.85,
        deflated_sharpe=1.28,
        probabilistic_sharpe=0.97,
        max_drawdown=0.105,
        expected_shortfall=0.045,
        turnover=3.2,
        capacity_utilization=0.25,
        regime_returns=(0.18, 0.12, 0.09, 0.21, 0.07),
        walkforward_returns=(0.05, 0.04, 0.06, 0.03, 0.05, 0.04, 0.02, 0.05),
        perturbation_pass_rate=0.94,
        parameter_stability=0.90,
        provenance_coverage=1.0,
        point_in_time_coverage=1.0,
        calibration_error=0.035,
        max_strategy_correlation=0.34,
        probability_backtest_overfit=0.08,
        bootstrap_positive_rate=0.93,
        ood_stability=0.88,
        cost_model_coverage=1.0,
        latency_stress_pass_rate=0.91,
        replay_determinism=1.0,
        lookahead_flags=(),
        data_quality_flags=(),
        holdout_touched=False,
    )
    values.update(overrides)
    return CandidateEvidence(**values)


def test_robustness_guardian_promotes_strong_evidence():
    verdict = RobustnessGuardianAgent().evaluate(strong())
    assert verdict.decision == "promote"
    assert verdict.veto is False
    assert verdict.score >= 0.70


def test_robustness_guardian_vetoes_lookahead_or_holdout_contamination():
    for evidence in (
        strong(lookahead_flags=("future_bar_used",)),
        strong(holdout_touched=True),
    ):
        verdict = RobustnessGuardianAgent().evaluate(evidence)
        assert verdict.decision == "reject"
        assert verdict.veto is True


def test_robustness_guardian_rejects_edge_that_dies_under_stress():
    verdict = RobustnessGuardianAgent().evaluate(
        strong(net_expectancy_lcb_bps=-0.1, stressed_net_expectancy_bps=-1.0)
    )
    assert verdict.decision == "reject"
    assert verdict.veto is True


def test_alpha_synthesis_rewards_net_edge_stability_and_diversification():
    verdict = AlphaSynthesisAgent().evaluate(strong())
    assert verdict.decision == "promote"
    assert verdict.score >= 0.68
    assert verdict.veto is False


def test_alpha_synthesis_refuses_cost_fragile_profitability():
    verdict = AlphaSynthesisAgent().evaluate(
        strong(net_expectancy_lcb_bps=0.05, stressed_net_expectancy_bps=-0.5)
    )
    assert verdict.decision == "reject"
    assert verdict.veto is True


def test_apex_council_contains_expected_internal_specialists_and_is_shadow_only():
    result = ApexCouncilAgent().evaluate(strong())
    names = {item.agent for item in result.child_verdicts}
    assert names == {
        "robustness-guardian",
        "alpha-synthesis",
        "data-integrity",
        "regime-sentinel",
        "execution-sentinel",
        "tail-risk-sentinel",
        "adversarial-sentinel",
        "calibration-sentinel",
        "multiple-testing-sentinel",
        "ood-sentinel",
    }
    assert result.decision == "promote"
    assert result.shadow_eligible is True
    assert result.execution_authorized is False
    assert result.quorum_met is True


def test_apex_council_hard_veto_beats_profitable_surface_metrics():
    result = ApexCouncilAgent().evaluate(strong(point_in_time_coverage=0.80))
    assert result.decision == "reject"
    assert result.shadow_eligible is False
    assert "data-integrity" in result.veto_agents


def test_apex_council_abstains_when_specialists_disagree_too_much():
    result = ApexCouncilAgent().evaluate(
        strong(
            calibration_error=0.19,
            max_strategy_correlation=0.94,
            expected_shortfall=0.14,
            max_drawdown=0.26,
            annualized_return=0.08,
        )
    )
    assert result.decision in {"hold", "reject"}
    assert result.shadow_eligible is False


def test_decision_trace_is_deterministic_and_sensitive_to_evidence():
    council = ApexCouncilAgent()
    first = council.evaluate(strong())
    second = council.evaluate(strong())
    changed = council.evaluate(strong(candidate_id="candidate-002"))
    assert first.trace_hash == second.trace_hash
    assert first.trace_hash != changed.trace_hash
    assert len(first.trace_hash) == 64


def test_evidence_validation_rejects_nonfinite_and_invalid_domains():
    with pytest.raises(EvidenceError):
        strong(sharpe=math.nan)
    with pytest.raises(EvidenceError):
        strong(probabilistic_sharpe=1.1)
    with pytest.raises(EvidenceError):
        strong(regime_count=2, regime_returns=(0.1, 0.2, 0.3))
    with pytest.raises(EvidenceError):
        strong(candidate_id="")


def test_apex_council_vetoes_high_probability_of_backtest_overfit():
    result = ApexCouncilAgent().evaluate(strong(probability_backtest_overfit=0.72))
    assert result.decision == "reject"
    assert "multiple-testing-sentinel" in result.veto_agents


def test_execution_and_data_integrity_fail_closed_on_weak_replay_or_latency_evidence():
    replay = ApexCouncilAgent().evaluate(strong(replay_determinism=0.70))
    assert replay.decision == "reject"
    assert "data-integrity" in replay.veto_agents
    latency = ApexCouncilAgent().evaluate(strong(latency_stress_pass_rate=0.40))
    assert latency.decision == "reject"
    assert "execution-sentinel" in latency.veto_agents


def test_ood_sentinel_blocks_brittle_distribution_shift_behavior():
    result = ApexCouncilAgent().evaluate(strong(ood_stability=0.35, bootstrap_positive_rate=0.52))
    assert result.decision == "reject"
    assert "ood-sentinel" in result.veto_agents


def test_robustness_guardian_rejects_missing_stress_evidence():
    for evidence in (strong(cost_model_coverage=0.50), strong(latency_stress_pass_rate=0.40), strong(perturbation_pass_rate=0.40), strong(parameter_stability=0.40), strong(probability_backtest_overfit=0.72), strong(ood_stability=0.35), strong(bootstrap_positive_rate=0.52)):
        verdict = RobustnessGuardianAgent().evaluate(evidence)
        assert verdict.decision == "reject"
        assert verdict.veto is True
