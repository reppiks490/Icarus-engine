from __future__ import annotations

import json

import pytest

from icarus_engine.interrepo_bridge import build_peer_packet


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
