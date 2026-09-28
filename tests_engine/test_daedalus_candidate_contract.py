import pytest

from icarus_engine.agents.daedalus_contract import AionCandidateRequest, CandidateContractError


def valid_request(**overrides):
    values = dict(
        candidate_id="candidate-001",
        candidate_version="v1",
        code_commit="8e39edaa5bed4dd97c70a60fef253be1145a7f7b",
        data_manifest_hash="sha256:" + "a" * 64,
        tune_window=("2025-01-01T00:00:00Z", "2025-09-30T23:59:59Z"),
        holdout_window=("2025-10-01T00:00:00Z", "2026-09-01T23:59:59Z"),
        trial_family="apex-v1-location-premise",
        cost_model_id="mnq-friction-v2",
        hypothesis_mechanism="Failed sweep plus structure break should preserve net expectancy after realistic costs.",
        falsification_evidence=("permutation-null:p=0.031", "friction-stress:passed"),
    )
    values.update(overrides)
    return AionCandidateRequest(**values)


def test_complete_aion_request_is_accepted_and_auditable():
    request = valid_request()
    assert request.candidate_id == "candidate-001"
    assert request.execution_authorized is False
    assert request.audit_payload()["code_commit"].startswith("8e39")


@pytest.mark.parametrize("field,value", [
    ("candidate_version", ""),
    ("code_commit", "not-a-commit"),
    ("data_manifest_hash", "sha256:short"),
    ("trial_family", ""),
    ("cost_model_id", ""),
    ("hypothesis_mechanism", ""),
    ("falsification_evidence", ()),
])
def test_missing_or_malformed_required_evidence_fails_closed(field, value):
    with pytest.raises(CandidateContractError):
        valid_request(**{field: value})


def test_holdout_must_start_strictly_after_tune_window():
    with pytest.raises(CandidateContractError):
        valid_request(holdout_window=("2025-09-01T00:00:00Z", "2026-09-01T00:00:00Z"))


def test_falsification_evidence_rejects_blank_entries():
    with pytest.raises(CandidateContractError):
        valid_request(falsification_evidence=("permutation-null:p=0.031", ""))
