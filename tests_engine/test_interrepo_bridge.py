from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from icarus_engine.interrepo_bridge import build_peer_packet
from tools.export_peer_intelligence import (
    _normalize_canonical_acceptance,
    export_packet,
    verify_packet_source_identity,
    verify_packet_source_inputs,
)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _fixture_root(tmp_path):
    _write(
        tmp_path / "automation_intelligence/restored_five_native/control_plane.json",
        {
            "schema_version": "restored-five-native-control-v1",
            "repository": "reppiks490/Icarus-engine",
            "execution_authorized": False,
            "lanes": [
                {
                    "name": "robustness_guardian",
                    "title": "Robustness Guardian Evolution",
                    "minute": 5,
                    "scheduler_id": "rg-1",
                    "worker_root": "automation_intelligence/agent_fabric/robustness_guardian",
                    "run_prefix": "robustness-guardian",
                },
                {
                    "name": "advanced_csv",
                    "title": "Advanced CSV Data Collector",
                    "minute": 15,
                    "scheduler_id": "csv-1",
                    "worker_repository": "reppiks490/icarus-csv-evidence-lab",
                    "worker_root": "automation_intelligence/advanced_csv",
                    "run_prefix": "advanced-csv",
                },
            ],
        },
    )
    _write(
        tmp_path / "automation_intelligence/agent_fabric/manifest.json",
        {
            "schema_version": "agent-fabric-scheduler-bindings-v1",
            "repository": "reppiks490/Icarus-engine",
            "execution_authorized": False,
            "lanes": {
                "robustness_guardian": {
                    "runtime_status_source": "automation_intelligence/agent_fabric/robustness_guardian/heartbeat.json",
                    "finalization_state": "automation_intelligence/agent_fabric/robustness_guardian/finalization_state.json",
                }
            },
        },
    )
    _write(
        tmp_path / "automation_intelligence/mcp_interface/contract.json",
        {
            "schema_version": "icarus-mcp-interface-contract-v1",
            "event_root": "automation_intelligence/mcp_interface/events",
            "ui_api": "/api/mcp/control",
            "trading_execution_authorized": False,
        },
    )
    _write(
        tmp_path / "automation_intelligence/agent_fabric/robustness_guardian/heartbeat.json",
        {
            "RUN_ID": "robustness-guardian-20261002T150500Z",
            "RUN_STATUS": "RUN_PERSISTED",
            "finalization_commit_sha": "d" * 40,
            "execution_authorized": False,
        },
    )
    _write(
        tmp_path / "automation_intelligence/agent_fabric/robustness_guardian/finalization_state.json",
        {
            "RUN_ID": "robustness-guardian-20261002T150500Z",
            "RUN_STATUS": "RUN_PERSISTED",
            "completion_semantics": "DURABILITY_RECEIPT_ONLY",
            "receipt_origin": "github_watchdog_stabilization_fallback",
            "worker_execution_observed": False,
            "execution_authorized": False,
            "payload": {"result": "SCHEDULER_WORKER_RECEIPT_MISSED"},
        },
    )
    _write(
        tmp_path / "automation_intelligence/agent_fabric/robustness_guardian/latest.json",
        {
            "schema_version": "agent-fabric-persistence-v3",
            "agent": "robustness_guardian",
            "RUN_ID": "robustness-guardian-20260929T180500Z",
            "RUN_STATUS": "RUN_PERSISTED",
            "RUN_CORE": {
                "execution_authorized": False,
                "base_main_sha": "1" * 40,
                "final_main_sha": "2" * 40,
                "findings": [
                    "Protected holdout lineage is incomplete.",
                    "Replay determinism remains intact.",
                ],
                "built_changes": ["No behavioral code change."],
                "NEXT": "Bind immutable dataset and holdout identities.",
            },
            "RUN_CORE_SHA256": "3" * 64,
            "history_mode": "primary_immutable_file",
            "history_blob_sha": "4" * 40,
            "execution_authorized": False,
        },
    )
    return tmp_path


def test_peer_packet_is_deterministic_research_only_and_provenance_bound(tmp_path):
    root = _fixture_root(tmp_path)
    kwargs = dict(
        source_commit="a" * 40,
        observed_at="2026-10-02T15:40:00Z",
    )
    one = build_peer_packet(root, **kwargs)
    two = build_peer_packet(root, **kwargs)

    assert one["packet_id"] == two["packet_id"]
    assert len(one["packet_id"]) == 64
    assert one["source_repository"] == "reppiks490/Icarus-engine"
    assert one["source_commit"] == "a" * 40
    assert set(one["source_contract_blobs"]) == {
        "control_plane",
        "agent_fabric",
        "mcp_interface",
    }
    assert all(len(value) == 40 for value in one["source_contract_blobs"].values())
    assert one["execution_authorized"] is False
    assert one["production_decision_authorized"] is False
    assert one["peer_write_authorized"] is False


def test_peer_packet_preserves_durability_only_truth(tmp_path):
    packet = build_peer_packet(
        _fixture_root(tmp_path),
        source_commit="b" * 40,
        observed_at="2026-10-02T15:41:00Z",
    )
    lane = next(x for x in packet["lanes"] if x["name"] == "robustness_guardian")
    assert lane["evidence_status"] == "DURABILITY_ONLY"
    assert lane["worker_execution_observed"] is False
    assert lane["run_id"] == "robustness-guardian-20261002T150500Z"
    assert lane["finalization_commit_sha"] == "d" * 40
    assert lane["substantive_research_evidence"] is False
    assert lane["heartbeat_path"].endswith("/heartbeat.json")
    assert lane["finalization_path"].endswith("/finalization_state.json")
    assert len(lane["heartbeat_blob_sha"]) == 40
    assert len(lane["finalization_blob_sha"]) == 40


def test_peer_packet_does_not_invent_remote_sibling_state(tmp_path):
    packet = build_peer_packet(
        _fixture_root(tmp_path),
        source_commit="c" * 40,
        observed_at="2026-10-02T15:42:00Z",
    )
    lane = next(x for x in packet["lanes"] if x["name"] == "advanced_csv")
    assert lane["worker_repository"] == "reppiks490/icarus-csv-evidence-lab"
    assert lane["evidence_status"] == "REMOTE_PEER_UNREAD"
    assert lane["run_id"] is None
    assert lane["substantive_research_evidence"] is False
    assert lane["heartbeat_path"] is None
    assert lane["heartbeat_blob_sha"] is None
    assert lane["finalization_path"] is None
    assert lane["finalization_blob_sha"] is None


def test_peer_packet_exposes_mcp_contract_without_granting_authority(tmp_path):
    packet = build_peer_packet(
        _fixture_root(tmp_path),
        source_commit="e" * 40,
        observed_at="2026-10-02T15:43:00Z",
    )
    assert packet["mcp_interface"]["schema_version"] == "icarus-mcp-interface-contract-v1"
    assert packet["mcp_interface"]["event_root"] == "automation_intelligence/mcp_interface/events"
    assert packet["mcp_interface"]["trading_execution_authorized"] is False


def test_peer_packet_rejects_invalid_git_sha_and_authority_escalation(tmp_path):
    root = _fixture_root(tmp_path)
    with pytest.raises(ValueError, match="40-character Git SHA"):
        build_peer_packet(root, source_commit="short", observed_at="2026-10-02T15:44:00Z")

    control = json.loads(
        (root / "automation_intelligence/restored_five_native/control_plane.json").read_text()
    )
    control["execution_authorized"] = True
    _write(root / "automation_intelligence/restored_five_native/control_plane.json", control)
    with pytest.raises(ValueError, match="execution_authorized"):
        build_peer_packet(root, source_commit="f" * 40, observed_at="2026-10-02T15:45:00Z")


def test_packet_id_changes_when_lane_state_changes(tmp_path):
    root = _fixture_root(tmp_path)
    one = build_peer_packet(root, source_commit="1" * 40, observed_at="2026-10-02T15:46:00Z")

    heartbeat = json.loads(
        (root / "automation_intelligence/agent_fabric/robustness_guardian/heartbeat.json").read_text()
    )
    heartbeat["RUN_ID"] = "robustness-guardian-20261002T160500Z"
    _write(root / "automation_intelligence/agent_fabric/robustness_guardian/heartbeat.json", heartbeat)

    two = build_peer_packet(root, source_commit="1" * 40, observed_at="2026-10-02T15:46:00Z")
    assert one["packet_id"] != two["packet_id"]


def test_peer_packet_preserves_historical_substantive_research_separately(tmp_path):
    packet = build_peer_packet(
        _fixture_root(tmp_path),
        source_commit="2" * 40,
        observed_at="2026-10-02T15:47:00Z",
    )
    artifacts = packet["historical_artifacts"]
    assert len(artifacts) == 1
    row = artifacts[0]
    assert row["lane"] == "robustness_guardian"
    assert row["artifact_kind"] == "HISTORICAL_LATEST"
    assert row["evidence_status"] == "HISTORICAL_RESEARCH_EVIDENCE"
    assert row["run_id"] == "robustness-guardian-20260929T180500Z"
    assert len(row["source_artifact_blob_sha"]) == 40
    assert row["research_context_eligible"] is True
    assert row["candidate_evidence_eligible"] is False
    assert row["summary"]["findings"] == [
        "Protected holdout lineage is incomplete.",
        "Replay determinism remains intact.",
    ]
    assert row["summary"]["next"] == "Bind immutable dataset and holdout identities."


def test_historical_collection_evidence_is_context_not_candidate_proof(tmp_path):
    root = _fixture_root(tmp_path)
    _write(
        root / "automation_intelligence/flow/latest.json",
        {
            "engine": "flow",
            "schema_version": "microstructure-collection-v4",
            "RUN_ID": "flow-20260929T173500Z",
            "RUN_STATUS": "RUN_PERSISTED",
            "COLLECTION_ONLY": True,
            "execution_authorized": False,
            "NET_NEW_DELTA": {"btc": "fresh funding evidence"},
            "observations": {"BTC": {"funding_percent": 0.003}},
            "source_provenance": [{"source": "venue", "event_time": "2026-09-29T00:00:00Z"}],
            "DATA_GAPS": ["No direct NQ depth."],
            "history_blob_sha": "5" * 40,
        },
    )
    control = json.loads(
        (root / "automation_intelligence/restored_five_native/control_plane.json").read_text()
    )
    control["lanes"].append({
        "name": "flow_microstructure",
        "title": "Microstructure Sensor Grid",
        "minute": 35,
        "scheduler_id": "flow-1",
        "worker_root": "automation_intelligence/flow",
        "run_prefix": "flow",
    })
    _write(root / "automation_intelligence/restored_five_native/control_plane.json", control)

    packet = build_peer_packet(
        root,
        source_commit="6" * 40,
        observed_at="2026-10-02T15:48:00Z",
    )
    flow = next(x for x in packet["historical_artifacts"] if x["lane"] == "flow_microstructure")
    assert flow["evidence_status"] == "HISTORICAL_COLLECTION_EVIDENCE"
    assert flow["research_context_eligible"] is True
    assert flow["candidate_evidence_eligible"] is False
    assert flow["summary"]["observation_keys"] == ["BTC"]
    assert flow["summary"]["data_gaps"] == ["No direct NQ depth."]


def test_historical_artifact_with_execution_authority_is_rejected(tmp_path):
    root = _fixture_root(tmp_path)
    latest = json.loads(
        (root / "automation_intelligence/agent_fabric/robustness_guardian/latest.json").read_text()
    )
    latest["execution_authorized"] = True
    _write(root / "automation_intelligence/agent_fabric/robustness_guardian/latest.json", latest)
    with pytest.raises(ValueError, match="execution_authorized"):
        build_peer_packet(
            root,
            source_commit="7" * 40,
            observed_at="2026-10-02T15:49:00Z",
        )

def test_peer_export_contract_and_workflow_are_research_only():
    root = Path(__file__).resolve().parents[1]
    consumer = json.loads(
        (root / "automation_intelligence/mcp_interface/icarus_consumer_contract.json")
        .read_text(encoding="utf-8")
    )
    peer = consumer["peer_packet"]
    assert peer["path"] == "automation_intelligence/interrepo/latest.json"
    assert peer["schema_version"] == "icarus-peer-intelligence-packet-v1"
    assert peer["authority"] == "OBSERVE"
    assert peer["source_commit_required"] is True
    assert peer["git_blob_verification_required"] is True
    assert peer["required_for_event_ingest"] is False
    assert peer["source_contract_blob_witnesses_required"] is True
    assert peer["source_contract_blob_witness_keys"] == [
        "control_plane",
        "agent_fabric",
        "mcp_interface",
    ]
    assert peer["semantics"]["source_contract_blobs_are_revision_bound"] is True
    assert peer["lane_source_witnesses_required"] is True
    assert peer["lane_source_witness_fields"] == [
        "heartbeat_path",
        "heartbeat_blob_sha",
        "finalization_path",
        "finalization_blob_sha",
    ]
    assert peer["semantics"]["lane_state_source_blobs_are_revision_bound"] is True
    assert peer["semantics"]["durability_only_is_not_substantive_research_evidence"] is True
    assert peer["semantics"]["automatic_execution_authority"] is False

    workflow = (
        root / ".github/workflows/interrepo-peer-intelligence.yml"
    ).read_text(encoding="utf-8")
    assert "python tools/export_peer_intelligence.py" in workflow
    assert "--root ." in workflow
    assert "--require-head-match" in workflow
    assert "--canonical-acceptance" in workflow
    assert "canonical-icarus/automation_intelligence/federation/icarus_engine_acceptance.json" in workflow
    assert "automation_intelligence/interrepo/latest.json" in workflow
    assert "git add automation_intelligence/interrepo/latest.json" in workflow
    assert 'cron: "*/10 * * * *"' in workflow
    assert "workflow_run:" in workflow
    assert "automation-durability-watchdog" in workflow
    assert "restored-five-durability-watchdog" in workflow
    assert "restored-five-native-liveness" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'schedule'" in workflow
    assert "permissions:\n  contents: write" in workflow

def test_peer_exporter_writes_exact_deterministic_packet(tmp_path):
    root = _fixture_root(tmp_path)
    output = Path("automation_intelligence/interrepo/test-latest.json")
    path, packet = export_packet(
        root,
        source_commit="2" * 40,
        observed_at="2026-10-02T20:55:00Z",
        output=output,
    )
    assert path == root.resolve() / output
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == packet
    assert stored["source_commit"] == "2" * 40
    assert stored["execution_authorized"] is False
    assert stored["production_decision_authorized"] is False
    assert stored["peer_write_authorized"] is False

def test_peer_exporter_verifies_exact_source_head_and_packet_authority(tmp_path):
    root = _fixture_root(tmp_path)
    _path, packet = export_packet(
        root,
        source_commit="8" * 40,
        observed_at="2026-10-02T21:50:00Z",
        output=Path("automation_intelligence/interrepo/test-source-proof.json"),
    )
    verify_packet_source_identity(packet, expected_head="8" * 40)

    with pytest.raises(ValueError, match="source_commit does not match export HEAD"):
        verify_packet_source_identity(packet, expected_head="9" * 40)

    escalated = dict(packet)
    escalated["execution_authorized"] = True
    with pytest.raises(ValueError, match="authority invariant failed"):
        verify_packet_source_identity(escalated, expected_head="8" * 40)

    tampered = dict(packet)
    tampered["observed_at"] = "2026-10-02T21:51:00Z"
    with pytest.raises(ValueError, match="packet_id does not match canonical packet content"):
        verify_packet_source_identity(tampered, expected_head="8" * 40)

def test_historical_artifact_binds_exact_latest_file_blob(tmp_path):
    root = _fixture_root(tmp_path)
    packet = build_peer_packet(
        root,
        source_commit="9" * 40,
        observed_at="2026-10-02T22:20:00Z",
    )
    artifact = packet["historical_artifacts"][0]
    source = (
        root
        / "automation_intelligence/agent_fabric/robustness_guardian/latest.json"
    ).read_bytes()
    header = f"blob {len(source)}\0".encode("ascii")
    expected = __import__("hashlib").sha1(header + source).hexdigest()
    assert artifact["source_artifact_blob_sha"] == expected

    latest_path = root / "automation_intelligence/agent_fabric/robustness_guardian/latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["RUN_CORE"]["findings"].append("new historical observation")
    _write(latest_path, latest)
    changed = build_peer_packet(
        root,
        source_commit="9" * 40,
        observed_at="2026-10-02T22:20:00Z",
    )
    assert changed["historical_artifacts"][0]["source_artifact_blob_sha"] != expected
    assert changed["historical_artifacts"][0]["artifact_id"] != artifact["artifact_id"]


def test_historical_context_contract_requires_exact_artifact_blob_binding():
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (root / "automation_intelligence/mcp_interface/icarus_consumer_contract.json")
        .read_text(encoding="utf-8")
    )
    historical = contract["historical_context"]
    assert historical["source_artifact_blob_required"] is True
    assert historical["artifact_id_sha256_required"] is True
    assert historical["packet_projection_verification_required"] is True
    assert (
        historical["truth_contract"]["historical_packet_projection_is_source_derived"]
        is True
    )

def _commit_fixture(root: Path) -> str:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "ICARUS tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=root, check=True, capture_output=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_peer_exporter_proves_all_local_inputs_match_claimed_source_revision(tmp_path):
    root = _fixture_root(tmp_path)
    head = _commit_fixture(root)
    _path, packet = export_packet(
        root,
        source_commit=head,
        observed_at="2026-10-02T22:45:00Z",
        output=Path("automation_intelligence/interrepo/test-source-input-proof.json"),
    )
    verify_packet_source_inputs(packet, root=root, expected_head=head)


def test_peer_exporter_fails_closed_on_uncommitted_lane_input_drift(tmp_path):
    root = _fixture_root(tmp_path)
    head = _commit_fixture(root)
    heartbeat_path = (
        root
        / "automation_intelligence/agent_fabric/robustness_guardian/heartbeat.json"
    )
    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    heartbeat["RUN_ID"] = "robustness-guardian-uncommitted-drift"
    _write(heartbeat_path, heartbeat)

    _path, packet = export_packet(
        root,
        source_commit=head,
        observed_at="2026-10-02T22:46:00Z",
        output=Path("automation_intelligence/interrepo/test-drift-proof.json"),
    )
    with pytest.raises(ValueError, match="packet input drift from source revision"):
        verify_packet_source_inputs(packet, root=root, expected_head=head)


def test_peer_exporter_fails_closed_on_uncommitted_historical_artifact_drift(tmp_path):
    root = _fixture_root(tmp_path)
    head = _commit_fixture(root)
    latest_path = (
        root
        / "automation_intelligence/agent_fabric/robustness_guardian/latest.json"
    )
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["RUN_CORE"]["findings"].append("uncommitted historical drift")
    _write(latest_path, latest)

    _path, packet = export_packet(
        root,
        source_commit=head,
        observed_at="2026-10-02T22:47:00Z",
        output=Path("automation_intelligence/interrepo/test-historical-drift-proof.json"),
    )
    with pytest.raises(ValueError, match="packet input drift from source revision"):
        verify_packet_source_inputs(packet, root=root, expected_head=head)

def test_peer_lane_source_witnesses_change_with_source_bytes(tmp_path):
    root = _fixture_root(tmp_path)
    before = build_peer_packet(
        root,
        source_commit="a" * 40,
        observed_at="2026-10-02T22:55:00Z",
    )
    lane_before = next(
        row for row in before["lanes"] if row["name"] == "robustness_guardian"
    )
    heartbeat_path = root / lane_before["heartbeat_path"]
    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    heartbeat["RUN_ID"] = "robustness-guardian-source-witness-change"
    _write(heartbeat_path, heartbeat)

    after = build_peer_packet(
        root,
        source_commit="a" * 40,
        observed_at="2026-10-02T22:55:00Z",
    )
    lane_after = next(
        row for row in after["lanes"] if row["name"] == "robustness_guardian"
    )
    assert lane_after["heartbeat_path"] == lane_before["heartbeat_path"]
    assert lane_after["heartbeat_blob_sha"] != lane_before["heartbeat_blob_sha"]
    assert after["packet_id"] != before["packet_id"]

def test_peer_exporter_fails_closed_on_source_contract_blob_witness_substitution(tmp_path):
    root = _fixture_root(tmp_path)
    head = _commit_fixture(root)
    _path, packet = export_packet(
        root,
        source_commit=head,
        observed_at="2026-10-02T23:05:00Z",
        output=Path("automation_intelligence/interrepo/test-contract-blob-proof.json"),
    )
    packet["source_contract_blobs"]["agent_fabric"] = "0" * 40
    unsigned = dict(packet)
    unsigned.pop("packet_id", None)
    packet["packet_id"] = __import__("hashlib").sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="source contract blob witness mismatch"):
        verify_packet_source_inputs(packet, root=root, expected_head=head)


def test_source_contract_blob_witness_changes_with_contract_bytes(tmp_path):
    root = _fixture_root(tmp_path)
    before = build_peer_packet(
        root,
        source_commit="b" * 40,
        observed_at="2026-10-02T23:06:00Z",
    )
    control_path = root / "automation_intelligence/restored_five_native/control_plane.json"
    control = json.loads(control_path.read_text(encoding="utf-8"))
    control["grace_minutes"] = 9
    _write(control_path, control)
    after = build_peer_packet(
        root,
        source_commit="b" * 40,
        observed_at="2026-10-02T23:06:00Z",
    )
    assert (
        after["source_contract_blobs"]["control_plane"]
        != before["source_contract_blobs"]["control_plane"]
    )
    assert after["packet_id"] != before["packet_id"]

def _canonical_acceptance(**overrides):
    payload = {
        "schema_version": "icarus-engine-federation-acceptance-v1",
        "validation_contract_version": 1,
        "source_receipt_schema": "icarus-live-bilateral-federation-receipt-v1",
        "accepted_by_repository": "reppiks490/Icarus",
        "producer_repository": "reppiks490/Icarus-engine",
        "accepted_by_icarus_commit": "1" * 40,
        "peer_packet_id": "2" * 64,
        "peer_packet_blob_sha": "3" * 40,
        "peer_source_commit": "4" * 40,
        "peer_source_commit_relation": "AHEAD",
        "peer_packet_fresh": True,
        "peer_source_contract_witness_count": 3,
        "peer_lane_count": 5,
        "peer_lane_witness_verified_count": 4,
        "peer_lane_contract_binding_verified_count": 5,
        "authority": "RESEARCH",
        "execution_authorized": False,
        "production_decision_authorized": False,
        "automatic_model_promotion": False,
        "truth_contract": {
            "foreign_peer_state_is_evidence_not_native_truth": True,
            "durability_only_is_not_substantive_research_evidence": True,
            "acceptance_is_not_execution_authority": True,
            "acceptance_is_not_production_decision_authority": True,
            "same_packet_is_idempotent": True,
        },
    }
    payload.update(overrides)
    return payload


def test_peer_export_embeds_verified_prior_canonical_acceptance(tmp_path):
    root = _fixture_root(tmp_path)
    head = _commit_fixture(root)
    acceptance_path = root / "canonical-acceptance.json"
    _write(acceptance_path, _canonical_acceptance())
    _path, packet = export_packet(
        root,
        source_commit=head,
        observed_at="2026-10-03T01:10:00Z",
        output=Path("automation_intelligence/interrepo/test-acceptance.json"),
        canonical_acceptance=Path("canonical-acceptance.json"),
    )
    ack = packet["canonical_acceptance"]
    assert ack["status"] == "VERIFIED_PRIOR_PACKET"
    assert ack["accepted_by_repository"] == "reppiks490/Icarus"
    assert ack["accepted_peer_packet_id"] == "2" * 64
    assert ack["accepted_peer_source_commit"] == "4" * 40
    assert ack["required_for_export"] is False
    assert ack["execution_authorized"] is False
    verify_packet_source_identity(packet, expected_head=head)


def test_peer_export_treats_missing_canonical_acceptance_as_optional(tmp_path):
    root = _fixture_root(tmp_path)
    head = _commit_fixture(root)
    _path, packet = export_packet(
        root,
        source_commit=head,
        observed_at="2026-10-03T01:11:00Z",
        output=Path("automation_intelligence/interrepo/test-no-acceptance.json"),
        canonical_acceptance=Path("missing-acceptance.json"),
    )
    assert packet["canonical_acceptance"]["status"] == "UNAVAILABLE"
    assert packet["canonical_acceptance"]["required_for_export"] is False
    assert packet["canonical_acceptance"]["execution_authorized"] is False
    verify_packet_source_identity(packet, expected_head=head)


def test_peer_export_rejects_incomplete_canonical_acceptance_contract(tmp_path):
    path = tmp_path / "acceptance.json"
    _write(path, _canonical_acceptance(peer_lane_contract_binding_verified_count=4))
    with pytest.raises(ValueError, match="lane contract binding is incomplete"):
        _normalize_canonical_acceptance(path)


def test_peer_export_rejects_canonical_acceptance_authority_escalation(tmp_path):
    path = tmp_path / "acceptance.json"
    _write(path, _canonical_acceptance(execution_authorized=True))
    with pytest.raises(ValueError, match="authority escalation"):
        _normalize_canonical_acceptance(path)


def test_consumer_contract_declares_optional_research_only_canonical_acceptance():
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (root / "automation_intelligence/mcp_interface/icarus_consumer_contract.json")
        .read_text(encoding="utf-8")
    )
    acceptance = contract["canonical_acceptance"]
    assert acceptance["repository"] == "reppiks490/Icarus"
    assert acceptance["ref"] == "main"
    assert acceptance["schema_version"] == "icarus-engine-federation-acceptance-v1"
    assert acceptance["authority"] == "RESEARCH"
    assert acceptance["required_for_export"] is False
    assert acceptance["execution_authorized"] is False
    assert acceptance["production_decision_authorized"] is False
    assert acceptance["semantics"]["prior_packet_acknowledgement_is_not_current_packet_qualification"] is True
    assert acceptance["semantics"]["automatic_execution_authority"] is False
