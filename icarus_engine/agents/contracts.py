from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from statistics import pstdev


class EvidenceError(ValueError):
    """Raised when an agent receives malformed or non-auditable evidence."""


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def canonical_hash(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stability_score(values: tuple[float, ...], scale: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return 1.0
    return clamp01(1.0 - pstdev(values) / scale)


@dataclass(frozen=True)
class CandidateEvidence:
    """Point-in-time evaluation evidence shared by all advisory agents.

    Percent-style risk and return values are decimal fractions (0.10 == 10%).
    Expectancy values are basis points per trade after the evaluator's stated costs.
    This object deliberately carries no broker/order handle and grants no execution authority.
    """

    candidate_id: str
    trials: int
    trade_count: int
    oos_windows: int
    regime_count: int
    annualized_return: float
    gross_expectancy_bps: float
    net_expectancy_bps: float
    net_expectancy_lcb_bps: float
    stressed_net_expectancy_bps: float
    sharpe: float
    deflated_sharpe: float
    probabilistic_sharpe: float
    max_drawdown: float
    expected_shortfall: float
    turnover: float
    capacity_utilization: float
    regime_returns: tuple[float, ...]
    walkforward_returns: tuple[float, ...]
    perturbation_pass_rate: float
    parameter_stability: float
    provenance_coverage: float
    point_in_time_coverage: float
    calibration_error: float
    max_strategy_correlation: float
    probability_backtest_overfit: float
    bootstrap_positive_rate: float
    ood_stability: float
    cost_model_coverage: float
    latency_stress_pass_rate: float
    replay_determinism: float
    lookahead_flags: tuple[str, ...] = ()
    data_quality_flags: tuple[str, ...] = ()
    holdout_touched: bool = False

    def __post_init__(self):
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip() or len(self.candidate_id) > 160:
            raise EvidenceError("candidate_id must be a non-empty string of at most 160 characters")
        for name in ("trials", "trade_count", "oos_windows", "regime_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise EvidenceError(f"{name} must be a positive integer")
        if self.oos_windows != len(self.walkforward_returns):
            raise EvidenceError("oos_windows must exactly match walkforward_returns")
        if self.regime_count != len(self.regime_returns):
            raise EvidenceError("regime_count must exactly match regime_returns")
        if type(self.holdout_touched) is not bool:
            raise EvidenceError("holdout_touched must be Boolean")
        for name in (
            "annualized_return", "gross_expectancy_bps", "net_expectancy_bps",
            "net_expectancy_lcb_bps", "stressed_net_expectancy_bps", "sharpe",
            "deflated_sharpe", "turnover",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise EvidenceError(f"{name} must be finite")
        for name in (
            "probabilistic_sharpe", "max_drawdown", "expected_shortfall",
            "capacity_utilization", "perturbation_pass_rate", "parameter_stability",
            "provenance_coverage", "point_in_time_coverage", "calibration_error",
            "max_strategy_correlation", "probability_backtest_overfit",
            "bootstrap_positive_rate", "ood_stability", "cost_model_coverage",
            "latency_stress_pass_rate", "replay_determinism",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise EvidenceError(f"{name} must be finite and within [0, 1]")
        if self.turnover < 0:
            raise EvidenceError("turnover cannot be negative")
        for name, values in (("regime_returns", self.regime_returns), ("walkforward_returns", self.walkforward_returns)):
            if not isinstance(values, tuple) or not values:
                raise EvidenceError(f"{name} must be a non-empty tuple")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise EvidenceError(f"{name} must contain finite numbers")
        for name in ("lookahead_flags", "data_quality_flags"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(v, str) or not v for v in values):
                raise EvidenceError(f"{name} must be a tuple of non-empty strings")

    def audit_payload(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AgentVerdict:
    agent: str
    decision: str
    score: float
    confidence: float
    veto: bool
    reasons: tuple[str, ...]

    def __post_init__(self):
        if self.decision not in {"promote", "hold", "reject"}:
            raise ValueError("invalid decision")
        if not 0.0 <= self.score <= 1.0 or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("score and confidence must be within [0,1]")

    def audit_payload(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CouncilDecision:
    decision: str
    score: float
    confidence: float
    quorum_met: bool
    shadow_eligible: bool
    execution_authorized: bool
    veto_agents: tuple[str, ...]
    dissent_agents: tuple[str, ...]
    child_verdicts: tuple[AgentVerdict, ...]
    trace_hash: str

    def __post_init__(self):
        if self.execution_authorized:
            raise ValueError("agent council can never authorize execution")
        if self.decision not in {"promote", "hold", "reject"}:
            raise ValueError("invalid council decision")
