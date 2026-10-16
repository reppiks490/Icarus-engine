import json
from pathlib import Path

from icarus_engine.mcp_control import MCPControlPlane


def write_json(root: Path, relative: str, value: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def seed(tmp_path: Path) -> None:
    write_json(tmp_path, "automation_intelligence/omega_stack_native_v3/control_plane.json", {
        "control_plane_id": "v3",
        "mode": "AUTHORITATIVE",
        "authoritative_scope": "LIVENESS_PERSISTENCE_ONLY",
        "inference_backend": "deterministic_liveness",
        "substantive_ai_inference": False,
        "execution_authorized": False,
        "lanes": [
            {"name": "omega", "title": "OMEGA", "minute": 0},
            {"name": "flow", "title": "Flow", "minute": 24},
        ],
    })
    write_json(tmp_path, "automation_intelligence/omega_stack_native_v3/cutover/acceptance.json", {
        "phase": "ZERO_COST_AUTHORITATIVE_LIVENESS",
        "zero_cost": True,
        "persistence_hardening": {"main_ref_race_retry_enabled": True},
    })
    for lane, slot in (("omega", "20261001T020000Z"), ("flow", "20261001T012400Z")):
        write_json(tmp_path, f"automation_intelligence/omega_stack_native_v3/lanes/{lane}/runs/{slot}/{lane}-{slot}.json", {
            "RUN_ID": f"{lane}-{slot}",
            "RUN_STATUS": "RUN_PERSISTED",
            "FINALIZATION_STATUS": "VERIFIED",
            "output_validation_status": "VALID",
            "slot_utc": "2026-10-01T02:00:00Z",
            "run_origin": "GITHUB_NATIVE_LIVENESS",
            "inference_backend": "deterministic_liveness",
            "model": "none",
            "DATA_GAPS": ["SUBSTANTIVE_AI_INFERENCE_NOT_EXECUTED"],
            "CONFLICTS": [],
        })
    write_json(tmp_path, "automation_intelligence/restored_five_native/control_plane.json", {
        "control_plane_id": "restored",
        "execution_authorized": False,
        "lanes": [{"name": "guardian", "title": "Guardian", "minute": 5, "scheduler_id": "abc"}],
    })
    write_json(tmp_path, "automation_intelligence/restored_five_native/receipts/guardian/20261001T010500Z.json", {
        "slot_utc": "2026-10-01T01:05:00Z",
        "slot_status": "FALLBACK_LIVENESS_ONLY",
        "worker_receipt_status": "WORKER_RECEIPT_MISSING",
        "substantive_work_claimed": False,
    })
    write_json(tmp_path, "automation_intelligence/mcp_interface/contract.json", {
        "schema_version": "icarus-mcp-interface-contract-v1",
        "purpose": "surface MCP work",
        "event_root": "automation_intelligence/mcp_interface/events",
        "required_categories": ["REPAIR", "AUDIT", "EVOLUTION", "INTEGRATION"],
        "required_fields": ["event_id"],
        "ui_api": "/api/mcp/control",
        "ui_tab": "MCP / Automation",
    })
    write_json(tmp_path, "automation_intelligence/mcp_interface/events/20261001T020000Z-test.json", {
        "event_id": "test",
        "at_utc": "2026-10-01T02:00:00Z",
        "category": "REPAIR",
        "status": "VERIFIED",
        "severity": "IMPORTANT",
        "summary": "repair",
        "surface": "automation",
        "source": "MCP",
        "paths": ["x"],
        "evidence": ["y"],
        "execution_authorized": False,
    })


def seed_coordination(tmp_path: Path) -> None:
    write_json(tmp_path, "automation_intelligence/coordination/index.json", {
        "schema_version": "icarus-coordination-index-v2",
        "generated_at_utc": "2026-10-16T03:10:15Z",
        "owner_status": {
            "claude": {"active": False, "return_date": None, "note": "inactive per owner"},
            "live_broker_arming": False,
        },
        "counts": {"active": 2, "terminal": 4, "stale": 1, "collisions": 1},
        "active_sessions": [
            {
                "session_id": "chat-a", "actor": "ChatGPT", "model_family": "openai",
                "goal": "UI", "home_repo": "reppiks490/Icarus-engine", "branch": "chatgpt/ui", "pr": "#1",
                "status": "active", "phase": "waiting", "latest_type": "WAITING",
                "latest_summary": "waiting on CI", "last_event_at_utc": "2026-10-16T03:10:00Z",
                "dependencies": ["github-run:123"],
                "reserved_targets": [{"repo": "reppiks490/Icarus-engine", "path": "icarus_engine/mcp-ui.js"}],
                "stale": False, "reclaimable": False,
            },
            {
                "session_id": "chat-b", "actor": "ChatGPT", "model_family": "openai",
                "goal": "repair", "home_repo": "reppiks490/Icarus", "branch": "chatgpt/repair", "pr": None,
                "status": "active", "phase": "coding", "latest_type": "UPDATE",
                "latest_summary": "repairing", "last_event_at_utc": "2026-10-16T02:00:00Z",
                "dependencies": [], "reserved_targets": [], "stale": True, "reclaimable": True,
            },
        ],
        "terminal_sessions": [],
        "collisions": [{
            "sessions": ["chat-a", "chat-c"], "repo": "reppiks490/Icarus-engine",
            "target_pairs": [["icarus_engine/mcp-ui.js", "icarus_engine"]],
            "severity": "collision",
        }],
    })


def test_status_projects_v3_restored_and_mcp_events(tmp_path: Path) -> None:
    seed(tmp_path)
    status = MCPControlPlane(tmp_path).status()

    assert status["execution_authorized"] is False
    assert status["trading_execution_authorized"] is False
    assert status["summary"]["v3_lanes"] == 2
    assert status["summary"]["v3_verified"] == 2
    assert status["v3"]["mode"] == "AUTHORITATIVE"
    assert {lane["health"] for lane in status["v3"]["lanes"]} == {"VERIFIED"}
    assert status["restored_five"]["lanes"][0]["health"] == "LIVENESS_ONLY"
    assert status["contract"]["present"] is True
    assert status["events"][0]["event_id"] == "test"
    assert status["events"][0]["execution_authorized"] is False


def test_latest_valid_receipt_wins_and_corrupt_json_is_ignored(tmp_path: Path) -> None:
    seed(tmp_path)
    runs = tmp_path / "automation_intelligence/omega_stack_native_v3/lanes/omega/runs"
    write_json(tmp_path, "automation_intelligence/omega_stack_native_v3/lanes/omega/runs/20261001T030000Z/omega-good.json", {
        "RUN_ID": "newest-good",
        "RUN_STATUS": "RUN_PERSISTED",
        "FINALIZATION_STATUS": "VERIFIED",
        "output_validation_status": "VALID",
        "slot_utc": "2026-10-01T03:00:00Z",
    })
    bad = runs / "20261001T040000Z" / "omega-bad.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json", encoding="utf-8")

    status = MCPControlPlane(tmp_path).status()
    omega = next(l for l in status["v3"]["lanes"] if l["name"] == "omega")
    assert omega["run_id"] == "newest-good"
    assert omega["health"] == "VERIFIED"


def test_event_limit_and_newest_first(tmp_path: Path) -> None:
    seed(tmp_path)
    for idx in range(3):
        write_json(tmp_path, f"automation_intelligence/mcp_interface/events/20261001T02000{idx}Z-{idx}.json", {
            "event_id": str(idx),
            "at_utc": f"2026-10-01T02:00:0{idx}Z",
            "category": "AUDIT",
            "status": "VERIFIED",
            "severity": "INFO",
            "summary": str(idx),
            "surface": "x",
            "source": "MCP",
            "paths": [],
            "evidence": [],
            "execution_authorized": False,
        })
    events = MCPControlPlane(tmp_path).status(event_limit=2)["events"]
    assert len(events) == 2
    assert [e["event_id"] for e in events] == ["2", "1"]


def test_missing_repository_evidence_is_safe(tmp_path: Path) -> None:
    status = MCPControlPlane(tmp_path).status()
    assert status["v3"]["present"] is False
    assert status["restored_five"]["present"] is False
    assert status["events"] == []
    assert status["execution_authorized"] is False
    assert status["coordination"]["present"] is False
    assert status["coordination"]["execution_authorized"] is False


def test_coordination_snapshot_is_read_only_bounded_projection(tmp_path: Path) -> None:
    seed(tmp_path)
    seed_coordination(tmp_path)
    status = MCPControlPlane(tmp_path).status()
    coord = status["coordination"]

    assert coord["present"] is True
    assert coord["schema_version"] == "icarus-coordination-index-v2"
    assert coord["generated_at_utc"] == "2026-10-16T03:10:15Z"
    assert coord["counts"] == {"active": 2, "terminal": 4, "stale": 1, "collisions": 1}
    assert coord["owner_status"]["claude"]["active"] is False
    assert coord["owner_status"]["live_broker_arming"] is False
    assert coord["active_sessions"][0]["phase"] == "waiting"
    assert coord["active_sessions"][0]["reserved_targets"][0]["path"] == "icarus_engine/mcp-ui.js"
    assert coord["collisions"][0]["repo"] == "reppiks490/Icarus-engine"
    assert coord["execution_authorized"] is False
    assert coord["trading_execution_authorized"] is False
    assert coord["source_path"] == "automation_intelligence/coordination/index.json"


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

    assert "*/5 * * * *" in workflow
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
    ui = (root / "mcp-ui.js").read_text(encoding="utf-8")

    assert '<script src="/mcp-ui.js"></script>' in dashboard
    assert 'data-v="mcp">MCP / Automation</span>' in dashboard
    assert "view === 'mcp'" in dashboard
    assert 'p.path == "/mcp-ui.js"' in server
    assert 'p.path == "/api/mcp/control"' in server
    assert "/admin/" not in ui
    assert "https://" not in ui
