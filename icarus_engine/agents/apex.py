from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median, pstdev

from .contracts import CandidateEvidence, CouncilDecision, canonical_hash, clamp01
from .specialists import (
    AdversarialSentinelAgent,
    AlphaSynthesisAgent,
    CalibrationSentinelAgent,
    DataIntegrityAgent,
    ExecutionSentinelAgent,
    RegimeSentinelAgent,
    MultipleTestingSentinelAgent,
    OODSentinelAgent,
    RobustnessGuardianAgent,
    TailRiskSentinelAgent,
)


@dataclass(frozen=True)
class CouncilConfig:
    quorum: int = 9
    promote_score: float = 0.72
    max_disagreement: float = 0.16
    minimum_promote_votes: int = 8

    def __post_init__(self):
        if not 1 <= self.quorum <= 10:
            raise ValueError("quorum must be within [1,10]")
        if not 0.0 <= self.promote_score <= 1.0 or not 0.0 <= self.max_disagreement <= 1.0:
            raise ValueError("council thresholds must be within [0,1]")
        if not 1 <= self.minimum_promote_votes <= 10:
            raise ValueError("minimum_promote_votes must be within [1,10]")


class ApexCouncilAgent:
    """Hierarchical advisory council with independent specialist vetoes.

    The council can only mark a candidate eligible for shadow evaluation. It has no
    broker handle, cannot place orders, and always emits execution_authorized=False.
    """

    def __init__(self, config: CouncilConfig | None = None):
        self.config = config or CouncilConfig()
        self.members = (
            RobustnessGuardianAgent(),
            AlphaSynthesisAgent(),
            DataIntegrityAgent(),
            RegimeSentinelAgent(),
            ExecutionSentinelAgent(),
            TailRiskSentinelAgent(),
            AdversarialSentinelAgent(),
            CalibrationSentinelAgent(),
            MultipleTestingSentinelAgent(),
            OODSentinelAgent(),
        )

    def evaluate(self, evidence: CandidateEvidence) -> CouncilDecision:
        children = tuple(member.evaluate(evidence) for member in self.members)
        veto_agents = tuple(item.agent for item in children if item.veto)
        non_reject = sum(item.decision != "reject" for item in children)
        promote_votes = sum(item.decision == "promote" for item in children)
        quorum_met = non_reject >= self.config.quorum
        scores = tuple(item.score for item in children)
        score = clamp01(median(scores))
        disagreement = pstdev(scores) if len(scores) > 1 else 0.0
        confidence = clamp01(median(tuple(item.confidence for item in children)) * (1.0 - disagreement))
        dissent_agents = tuple(item.agent for item in children if item.decision != "promote")

        if veto_agents:
            decision = "reject"
        elif (
            quorum_met
            and promote_votes >= self.config.minimum_promote_votes
            and score >= self.config.promote_score
            and disagreement <= self.config.max_disagreement
        ):
            decision = "promote"
        elif quorum_met and score >= 0.50:
            decision = "hold"
        else:
            decision = "reject"

        trace_payload = {
            "evidence": evidence.audit_payload(),
            "config": asdict(self.config),
            "children": [item.audit_payload() for item in children],
            "decision": decision,
            "score": score,
            "confidence": confidence,
            "quorum_met": quorum_met,
            "execution_authorized": False,
        }
        return CouncilDecision(
            decision=decision,
            score=score,
            confidence=confidence,
            quorum_met=quorum_met,
            shadow_eligible=decision == "promote",
            execution_authorized=False,
            veto_agents=veto_agents,
            dissent_agents=dissent_agents,
            child_verdicts=children,
            trace_hash=canonical_hash(trace_payload),
        )
