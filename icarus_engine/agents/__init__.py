"""Evidence-gated ICARUS advisory agents.

These agents evaluate research candidates and can only recommend shadow eligibility.
They intentionally expose no trading or broker execution surface.
"""
from .apex import ApexCouncilAgent, CouncilConfig
from .contracts import AgentVerdict, CandidateEvidence, CouncilDecision, EvidenceError
from .specialists import AlphaSynthesisAgent, RobustnessGuardianAgent

__all__ = [
    "ApexCouncilAgent",
    "CouncilConfig",
    "AgentVerdict",
    "CandidateEvidence",
    "CouncilDecision",
    "EvidenceError",
    "AlphaSynthesisAgent",
    "RobustnessGuardianAgent",
]
