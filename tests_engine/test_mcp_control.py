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
