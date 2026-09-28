import dataclasses

import pytest

from icarus_engine.agents import AdvancedAgentEvidence, ApexCouncilAgent, evidence_from_research_job
from icarus_engine.research_service import ResearchWorkspace
from tests_engine.test_research_service import portfolio, qualified


def advanced(**overrides):
    values = dict(
        annualized_return=0.24,
        gross_expectancy_bps=9.0,
        net_expectancy_lcb_bps=3.0,
        sharpe=1.8,
        deflated_sharpe=1.2,
        probabilistic_sharpe=0.96,
        expected_shortfall=0.05,
        turnover=3.0,
        capacity_utilization=0.25,
        regime_returns=(0.18, 0.12, 0.09, 0.21),
        walkforward_returns=(0.05, 0.04, 0.06, 0.03),
        perturbation_pass_rate=0.93,
        parameter_stability=0.90,
        calibration_error=0.04,
        max_strategy_correlation=0.32,
        probability_backtest_overfit=0.08,
        bootstrap_positive_rate=0.92,
        ood_stability=0.87,
        latency_stress_pass_rate=0.90,
        replay_determinism=1.0,
        lookahead_flags=(),
        data_quality_flags=(),
        protected_holdout_touched=False,
    )
    values.update(overrides)
    return AdvancedAgentEvidence(**values)


def test_qualified_research_job_binds_to_candidate_evidence_without_execution_authority(portfolio):
    ws = ResearchWorkspace(portfolio)
    job = qualified(ws)
    evidence = evidence_from_research_job(job, advanced())

    assert evidence.candidate_id == f"NQ:{job['result']['study_hash']}"
    assert evidence.trade_count == job["result"]["holdout"]["entries"]
    assert evidence.net_expectancy_bps > 0
    assert evidence.stressed_net_expectancy_bps > 0
    assert evidence.provenance_coverage == 1.0
    assert evidence.point_in_time_coverage == 1.0
    assert evidence.cost_model_coverage == 1.0
    assert evidence.holdout_touched is False

    decision = ApexCouncilAgent().evaluate(evidence)
    assert decision.execution_authorized is False


def test_adapter_rejects_unqualified_or_execution_authorized_research_job(portfolio):
    ws = ResearchWorkspace(portfolio)
    job = qualified(ws)

    bad = {**job, "result": {**job["result"], "research_qualified": False}}
    with pytest.raises(ValueError, match="qualified"):
        evidence_from_research_job(bad, advanced())

    bad = {**job, "result": {**job["result"], "execution_authorized": True}}
    with pytest.raises(ValueError, match="execution"):
        evidence_from_research_job(bad, advanced())


def test_adapter_requires_real_advanced_evidence_instead_of_fabricating_it(portfolio):
    ws = ResearchWorkspace(portfolio)
    job = qualified(ws)
    with pytest.raises(TypeError):
        evidence_from_research_job(job, {"deflated_sharpe": 1.2})


def test_workspace_agent_shadow_evaluate_is_bound_to_qualified_job_and_never_executes(portfolio):
    ws = ResearchWorkspace(portfolio)
    job = qualified(ws)
    result = ws.agent_shadow_evaluate(job["id"], advanced())

    assert result["candidate_id"] == f"NQ:{job['result']['study_hash']}"
    assert result["decision"] in {"promote", "hold", "reject"}
    assert result["execution_authorized"] is False
    assert len(result["trace_hash"]) == 64
    assert set(result["child_agents"]) == {
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


def test_advanced_evidence_rejects_nonfinite_or_out_of_domain_values():
    with pytest.raises(ValueError):
        advanced(probability_backtest_overfit=1.1)
    with pytest.raises(ValueError):
        advanced(annualized_return=float("nan"))
