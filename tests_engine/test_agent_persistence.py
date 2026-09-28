import json
from copy import deepcopy
from pathlib import Path

import pytest

from icarus_engine.agents.persistence import (
    PersistenceError,
    canonical_run_core_sha256,
    validate_finalized_run,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _bundle():
    core = {
        "agent": "robustness_guardian",
        "RUN_ID": "robustness-guardian-20260928T200632Z",
        "persistence_protocol_version": "agent-fabric-persistence-v3",
        "execution_authorized": False,
        "findings": {"stress_gate": "verified"},
    }
    digest = canonical_run_core_sha256(core)
    history = {
        "schema_version": "agent-run-history-v3",
        "RUN_STATUS": "HISTORY_VERIFIED",
        "RUN_CORE": core,
        "RUN_CORE_SHA256": digest,
        "execution_authorized": False,
    }
    latest = {
        "schema_version": "agent-run-latest-v3",
        "RUN_STATUS": "RUN_PERSISTED",
        "RUN_CORE": deepcopy(core),
        "RUN_CORE_SHA256": digest,
        "history_blob_sha": "history-blob",
        "execution_authorized": False,
    }
    state = {
        "schema_version": "agent-loop-state-v2",
        "last_successful_run_id": core["RUN_ID"],
        "execution_authorized": False,
    }
    heartbeat = {
        "schema_version": "agent-loop-heartbeat-v3",
        "RUN_ID": core["RUN_ID"],
        "RUN_STATUS": "RUN_PERSISTED",
        "execution_authorized": False,
    }
    receipt = {
        "schema_version": "agent-finalization-receipt-v1",
        "RUN_ID": core["RUN_ID"],
        "RUN_STATUS": "FINALIZATION_VERIFIED",
        "RUN_CORE_SHA256": digest,
        "history_blob_sha": "history-blob",
        "latest_blob_sha": "latest-blob",
        "execution_authorized": False,
    }
    return history, latest, state, heartbeat, receipt


def test_canonical_run_core_hash_is_order_independent_and_content_sensitive():
    first = {"b": [2, 1], "a": {"y": 2, "x": 1}}
    second = {"a": {"x": 1, "y": 2}, "b": [2, 1]}
    changed = {"a": {"x": 1, "y": 3}, "b": [2, 1]}
    assert canonical_run_core_sha256(first) == canonical_run_core_sha256(second)
    assert canonical_run_core_sha256(first) != canonical_run_core_sha256(changed)


def test_finalized_run_requires_mutually_bound_history_latest_state_heartbeat_and_receipt():
    history, latest, state, heartbeat, receipt = _bundle()
    result = validate_finalized_run(
        history=history,
        latest=latest,
        state=state,
        heartbeat=heartbeat,
        finalization=receipt,
        actual_history_blob_sha="history-blob",
        actual_latest_blob_sha="latest-blob",
    )
    assert result["status"] == "FINALIZATION_VERIFIED"
    assert result["RUN_ID"] == history["RUN_CORE"]["RUN_ID"]
    assert result["execution_authorized"] is False


@pytest.mark.parametrize(
    "mutator",
    [
        lambda h, l, s, b, r: l["RUN_CORE"].update({"findings": {"stress_gate": "tampered"}}),
        lambda h, l, s, b, r: s.update({"last_successful_run_id": "other-run"}),
        lambda h, l, s, b, r: b.update({"RUN_STATUS": "IN_PROGRESS"}),
        lambda h, l, s, b, r: r.update({"latest_blob_sha": "wrong"}),
        lambda h, l, s, b, r: r.update({"history_blob_sha": "wrong"}),
        lambda h, l, s, b, r: r.update({"RUN_CORE_SHA256": "0" * 64}),
    ],
)
def test_finalized_run_fails_closed_on_pointer_or_content_mismatch(mutator):
    history, latest, state, heartbeat, receipt = _bundle()
    mutator(history, latest, state, heartbeat, receipt)
    with pytest.raises(PersistenceError):
        validate_finalized_run(
            history=history,
            latest=latest,
            state=state,
            heartbeat=heartbeat,
            finalization=receipt,
            actual_history_blob_sha="history-blob",
            actual_latest_blob_sha="latest-blob",
        )


def test_finalized_run_rejects_any_execution_authority():
    history, latest, state, heartbeat, receipt = _bundle()
    for artifact in (history["RUN_CORE"], history, latest, state, heartbeat, receipt):
        candidate = deepcopy((history, latest, state, heartbeat, receipt))
        h, l, s, b, r = candidate
        targets = [h["RUN_CORE"], h, l, s, b, r]
        index = [history["RUN_CORE"], history, latest, state, heartbeat, receipt].index(artifact)
        targets[index]["execution_authorized"] = True
        if index == 0:
            h["RUN_CORE_SHA256"] = canonical_run_core_sha256(h["RUN_CORE"])
            l["RUN_CORE"] = deepcopy(h["RUN_CORE"])
            l["RUN_CORE_SHA256"] = h["RUN_CORE_SHA256"]
            r["RUN_CORE_SHA256"] = h["RUN_CORE_SHA256"]
        with pytest.raises(PersistenceError):
            validate_finalized_run(
                history=h,
                latest=l,
                state=s,
                heartbeat=b,
                finalization=r,
                actual_history_blob_sha="history-blob",
                actual_latest_blob_sha="latest-blob",
            )


def test_agent_fabric_persistence_contract_declares_finalization_receipt_and_startup_gate():
    contract = json.loads(
        (REPO_ROOT / "automation_intelligence" / "agent_fabric" / "persistence_contract.json").read_text()
    )
    assert contract["schema_version"] == "agent-fabric-persistence-v3"
    assert contract["startup"]["heartbeat_readback_required"] is True
    assert contract["finalization"]["receipt_required"] is True
    assert contract["finalization"]["state_pointer_required"] is True
    assert contract["execution_authorized"] is False
