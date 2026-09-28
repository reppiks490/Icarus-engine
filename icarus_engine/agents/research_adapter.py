from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from .contracts import CandidateEvidence, EvidenceError


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvidenceError(f"{name} must be finite")
    return float(value)


def _unit(value, name):
    value = _finite(value, name)
    if not 0.0 <= value <= 1.0:
        raise EvidenceError(f"{name} must be within [0,1]")
    return value


def _series(values, name):
    if not isinstance(values, tuple) or not values:
        raise EvidenceError(f"{name} must be a non-empty tuple")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise EvidenceError(f"{name} must contain finite numbers")
    return values


def _flags(values, name):
    if not isinstance(values, tuple) or any(not isinstance(v, str) or not v for v in values):
        raise EvidenceError(f"{name} must be a tuple of non-empty strings")
    return values


def _sha256(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value


@dataclass(frozen=True)
class AdvancedAgentEvidence:
    """Metrics that the bounded research job cannot truthfully derive by itself.

    The adapter never synthesizes these fields. Callers must provide them from a
    separately validated point-in-time evaluation process.
    """

    study_hash: str
    dataset_hash: str
    baseline_hash: str
    provenance_coverage: float
    point_in_time_coverage: float
    cost_model_coverage: float
    annualized_return: float
    gross_expectancy_bps: float
    net_expectancy_lcb_bps: float
    sharpe: float
    deflated_sharpe: float
    probabilistic_sharpe: float
    expected_shortfall: float
    turnover: float
    capacity_utilization: float
    regime_returns: tuple[float, ...]
    walkforward_returns: tuple[float, ...]
    perturbation_pass_rate: float
    parameter_stability: float
    calibration_error: float
    max_strategy_correlation: float
    probability_backtest_overfit: float
    bootstrap_positive_rate: float
    ood_stability: float
    latency_stress_pass_rate: float
    replay_determinism: float
    lookahead_flags: tuple[str, ...] = ()
    data_quality_flags: tuple[str, ...] = ()
    protected_holdout_touched: bool = False

    def __post_init__(self):
        for name in ("study_hash", "dataset_hash", "baseline_hash"):
            _sha256(getattr(self, name), name)
        for name in ("provenance_coverage", "point_in_time_coverage", "cost_model_coverage"):
            _unit(getattr(self, name), name)
        for name in (
            "annualized_return", "gross_expectancy_bps", "net_expectancy_lcb_bps",
            "sharpe", "deflated_sharpe", "turnover",
        ):
            _finite(getattr(self, name), name)
        if self.turnover < 0:
            raise EvidenceError("turnover cannot be negative")
        for name in (
            "probabilistic_sharpe", "expected_shortfall", "capacity_utilization",
            "perturbation_pass_rate", "parameter_stability", "calibration_error",
            "max_strategy_correlation", "probability_backtest_overfit",
            "bootstrap_positive_rate", "ood_stability", "latency_stress_pass_rate",
            "replay_determinism",
        ):
            _unit(getattr(self, name), name)
        _series(self.regime_returns, "regime_returns")
        _series(self.walkforward_returns, "walkforward_returns")
        _flags(self.lookahead_flags, "lookahead_flags")
        _flags(self.data_quality_flags, "data_quality_flags")
        if type(self.protected_holdout_touched) is not bool:
            raise EvidenceError("protected_holdout_touched must be Boolean")


def _qualified_result(job: Mapping) -> tuple[Mapping, Mapping, Mapping]:
    if not isinstance(job, Mapping) or job.get("status") != "complete":
        raise ValueError("a completed qualified research job is required")
    result = job.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "complete" or result.get("research_qualified") is not True:
        raise ValueError("a completed qualified research job is required")
    if result.get("execution_authorized") is not False:
        raise ValueError("research job must explicitly deny execution authority")
    if not result.get("selected") or result.get("holdout_consumed") is not True:
        raise ValueError("qualified research job must contain a consumed fixed holdout")
    manifest = result.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("research manifest is missing")
    if manifest.get("dataset_hash") != job.get("dataset_hash") or manifest.get("baseline_hash") != job.get("baseline_hash"):
        raise ValueError("research job fingerprint mismatch")
    _sha256(job.get("dataset_hash"), "dataset_hash")
    _sha256(job.get("baseline_hash"), "baseline_hash")
    _sha256(result.get("study_hash"), "study_hash")
    holdout = result.get("holdout")
    stress = result.get("stress")
    if not isinstance(holdout, Mapping) or not isinstance(stress, Mapping):
        raise ValueError("qualified holdout evidence is missing")
    if not isinstance(result.get("holdout_comparison"), Mapping) or result["holdout_comparison"].get("passed") is not True:
        raise ValueError("normal-cost holdout comparison is not qualified")
    if stress.get("status") != "enabled" or not isinstance(stress.get("holdout"), Mapping):
        raise ValueError("stress-cost holdout evidence is required")
    if not isinstance(stress.get("holdout_comparison"), Mapping) or stress["holdout_comparison"].get("passed") is not True:
        raise ValueError("stress-cost holdout comparison is not qualified")
    return result, holdout, stress


def _verify_replay_evidence(value: Mapping, name: str):
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} replay evidence is missing")
    for field in ("result_sha256", "source_config_sha256", "subbars_sha256", "deep_sha256"):
        _sha256(value.get(field), f"{name}.{field}")


def _expectancy_bps(metrics: Mapping, name: str) -> float:
    expectancy = _finite(metrics.get("expectancy_after_costs"), f"{name}.expectancy_after_costs")
    capital = _finite(metrics.get("capital"), f"{name}.capital")
    if capital <= 0:
        raise ValueError(f"{name}.capital must be positive")
    return expectancy / capital * 10000.0


def evidence_from_research_job(job: Mapping, advanced: AdvancedAgentEvidence) -> CandidateEvidence:
    """Bind one qualified ICARUS research job to the agent evidence contract.

    Only metrics proven by the bounded research workflow are derived here.
    Advanced statistical/robustness metrics must arrive as AdvancedAgentEvidence;
    dictionaries and partial model claims are intentionally rejected.
    """

    if not isinstance(advanced, AdvancedAgentEvidence):
        raise TypeError("advanced evidence must be AdvancedAgentEvidence")
    result, holdout, stress = _qualified_result(job)
    if (
        advanced.study_hash != result["study_hash"]
        or advanced.dataset_hash != job["dataset_hash"]
        or advanced.baseline_hash != job["baseline_hash"]
    ):
        raise ValueError("advanced evidence is not bound to this exact study/dataset/baseline")
    _verify_replay_evidence(result.get("holdout_evidence"), "holdout")
    _verify_replay_evidence(stress.get("holdout_evidence"), "stress.holdout")
    if holdout.get("historical_scale_asof_valid") is not True or stress["holdout"].get("historical_scale_asof_valid") is not True:
        raise ValueError("point-in-time historical-scale provenance is incomplete")

    entries = holdout.get("entries")
    trials = result.get("total_combinations")
    if type(entries) is not int or entries < 1:
        raise ValueError("holdout entries must be a positive integer")
    if type(trials) is not int or trials < 1:
        raise ValueError("total_combinations must be a positive integer")

    normal_dd = _finite(holdout.get("max_drawdown_pct"), "holdout.max_drawdown_pct")
    stress_dd = _finite(stress["holdout"].get("max_drawdown_pct"), "stress.holdout.max_drawdown_pct")
    max_drawdown = max(normal_dd, stress_dd) / 100.0
    if not 0.0 <= max_drawdown <= 1.0:
        raise ValueError("derived max drawdown is outside [0,1]")

    normal_expectancy_bps = _expectancy_bps(holdout, "holdout")
    stressed_expectancy_bps = _expectancy_bps(stress["holdout"], "stress.holdout")
    if advanced.net_expectancy_lcb_bps > normal_expectancy_bps:
        raise ValueError("lower-bound expectancy cannot exceed normal net expectancy")
    if stressed_expectancy_bps > normal_expectancy_bps:
        raise ValueError("stressed expectancy cannot exceed normal net expectancy")

    asset = job.get("asset")
    if not isinstance(asset, str) or not asset:
        raise ValueError("research asset is missing")

    return CandidateEvidence(
        candidate_id=f"{asset}:{result['study_hash']}",
        trials=trials,
        trade_count=entries,
        oos_windows=len(advanced.walkforward_returns),
        regime_count=len(advanced.regime_returns),
        annualized_return=advanced.annualized_return,
        gross_expectancy_bps=advanced.gross_expectancy_bps,
        net_expectancy_bps=normal_expectancy_bps,
        net_expectancy_lcb_bps=advanced.net_expectancy_lcb_bps,
        stressed_net_expectancy_bps=stressed_expectancy_bps,
        sharpe=advanced.sharpe,
        deflated_sharpe=advanced.deflated_sharpe,
        probabilistic_sharpe=advanced.probabilistic_sharpe,
        max_drawdown=max_drawdown,
        expected_shortfall=advanced.expected_shortfall,
        turnover=advanced.turnover,
        capacity_utilization=advanced.capacity_utilization,
        regime_returns=advanced.regime_returns,
        walkforward_returns=advanced.walkforward_returns,
        perturbation_pass_rate=advanced.perturbation_pass_rate,
        parameter_stability=advanced.parameter_stability,
        provenance_coverage=advanced.provenance_coverage,
        point_in_time_coverage=advanced.point_in_time_coverage,
        calibration_error=advanced.calibration_error,
        max_strategy_correlation=advanced.max_strategy_correlation,
        probability_backtest_overfit=advanced.probability_backtest_overfit,
        bootstrap_positive_rate=advanced.bootstrap_positive_rate,
        ood_stability=advanced.ood_stability,
        cost_model_coverage=advanced.cost_model_coverage,
        latency_stress_pass_rate=advanced.latency_stress_pass_rate,
        replay_determinism=advanced.replay_determinism,
        lookahead_flags=advanced.lookahead_flags,
        data_quality_flags=advanced.data_quality_flags,
        holdout_touched=advanced.protected_holdout_touched,
    )
