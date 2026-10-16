from pathlib import Path
import json

import pytest

from icarus_engine.mcp_control import MCPControlPlane


def write_json(root: Path, rel: str, payload: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def seed(root: Path) -> None:
    write_json(root, "automation_intelligence/mcp_interface/latest.json", {
        "schema": "icarus.mcp_interface.latest/1",
        "generated_at": "2026-10-15T10:00:00Z",
        "event_count": 3,
        "latest_event": {"category": "RESEARCH", "status": "verified"},
    })
    write_json(root, "automation_intelligence/coordination/index.json", {
        "schema_version": "icarus-coordination-index-v2",
        "generated_at": "2026-10-15T10:00:00Z",
        "counts": {"active": 1, "stale": 0, "collisions": 0},
        "active_sessions": [
            {"session_id": "chat-a", "phase": "testing", "repo": "r/x", "branch": "b", "reserved_targets": ["r/x:a.py"]}
        ],
        "collisions": [],
        "owner_status": {"live_broker_arming": "disabled"},
    })


def test_status_is_read_only_and_coordination_is_bounded(tmp_path: Path) -> None:
    seed(tmp_path)
    plane = MCPControlPlane(tmp_path)
    before = sorted((p.relative_to(tmp_path).as_posix(), p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file())
    status = plane.status()
    after = sorted((p.relative_to(tmp_path).as_posix(), p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file())

    assert before == after
    assert status["coordination"]["present"] is True
    assert status["coordination"]["counts"] == {"active": 1, "stale": 0, "collisions": 0}
    assert len(status["coordination"]["active_sessions"]) == 1
    assert status["coordination"]["execution_authorized"] is False


def test_malformed_coordination_snapshot_fails_closed(tmp_path: Path) -> None:
    seed(tmp_path)
    write_json(tmp_path, "automation_intelligence/coordination/index.json", {
        "schema_version": "wrong", "active_sessions": "not-a-list", "collisions": []
    })
    coord = MCPControlPlane(tmp_path).status()["coordination"]
    assert coord["present"] is False
    assert coord["error"] == "INVALID_COORDINATION_SNAPSHOT"
    assert coord["execution_authorized"] is False


def test_coordination_mirror_and_ui_are_read_only_and_local(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/coordination-mirror.yml").read_text(encoding="utf-8")
    ui = (root / "icarus_engine/mcp-ui.js").read_text(encoding="utf-8")

    assert "3-58/5 * * * *" in workflow
    assert "workflow_run:" in workflow
    assert "restored-five-local-shadow" in workflow
    assert "reppiks490/icarus-owner-actions" in workflow
    assert "coordination/index.json" in workflow
    assert "icarus-coordination-index-v2" in workflow
    assert "automation_intelligence/coordination/index.json" in workflow
    assert "git reset --hard origin/main" in workflow
    assert "[skip ci]" in workflow
    assert "Multi-chat coordination" in ui
    assert "mcpCoordination" in ui
    assert "reserved_targets" in ui
    assert "reclaimable" in ui
    assert "collisions" in ui
    assert "/admin/" not in ui
    assert "https://" not in ui


def test_dashboard_and_server_wire_read_only_mcp_panel() -> None:
    root = Path(__file__).resolve().parents[1] / "icarus_engine"
    dashboard = (root / "dashboard.html").read_text(encoding="utf-8")
    server = (root / "server.py").read_text(encoding="utf-8")
    assert "mcpCoordination" in dashboard
    assert "mcp-ui.js" in dashboard
    assert "MCPControlPlane" in server


def test_coordination_snapshot_is_not_authority(tmp_path: Path) -> None:
    seed(tmp_path)
    write_json(tmp_path, "automation_intelligence/coordination/index.json", {
        "schema_version": "icarus-coordination-index-v2",
        "generated_at": "2026-10-15T10:00:00Z",
        "counts": {"active": 0, "stale": 0, "collisions": 0},
        "active_sessions": [],
        "collisions": [],
        "owner_status": {"execution_authorized": True, "live_broker_arming": "enabled"},
    })
    coord = MCPControlPlane(tmp_path).status()["coordination"]
    assert coord["execution_authorized"] is False


def test_status_never_emits_unbounded_coordination_collections(tmp_path: Path) -> None:
    seed(tmp_path)
    write_json(tmp_path, "automation_intelligence/coordination/index.json", {
        "schema_version": "icarus-coordination-index-v2",
        "generated_at": "2026-10-15T10:00:00Z",
        "counts": {"active": 600, "stale": 0, "collisions": 0},
        "active_sessions": [{"session_id": f"s{i}", "reserved_targets": []} for i in range(600)],
        "collisions": [],
        "owner_status": {},
    })
    coord = MCPControlPlane(tmp_path).status()["coordination"]
    assert len(coord["active_sessions"]) <= 512
