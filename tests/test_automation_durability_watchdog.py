from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "automation_durability_watchdog.py"
_spec = importlib.util.spec_from_file_location("automation_durability_watchdog", MODULE_PATH)
assert _spec and _spec.loader
_watchdog = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _watchdog
_spec.loader.exec_module(_watchdog)

Artifact = _watchdog.Artifact
load_watchdog_config = _watchdog.load_watchdog_config
iter_expected_slots = _watchdog.iter_expected_slots
plan_reconciliation = _watchdog.plan_reconciliation
scan_lane_receipts = _watchdog.scan_lane_receipts
write_artifacts = _watchdog.write_artifacts
load_v3_watchdog_config = _watchdog.load_v3_watchdog_config
iter_v3_expected_slots = _watchdog.iter_v3_expected_slots
scan_v3_receipts = _watchdog.scan_v3_receipts
plan_v3_reconciliation = _watchdog.plan_v3_reconciliation

CONTROL_PLANE_ID = "omega-aion-daedalus-native-v2"
PROTOCOL = "omega-stack-persistence-v4.3-append-first"
BRANCH = "automation/omega-native-v2"
NS = "automation_intelligence/omega_stack_native_v2"
IDS = {
    "omega": "6abb57443c0c81919676c71d87493353",
    "macro": "6ab8174517b48191b67ac472205a28d3",
    "flow": "6ab817544e68819197b5db21eb2cbe2b",
    "aion": "6abb1618be1c8191943f5d4e2d88978d",
    "daedalus": "6ab8177918b48191a97e56c44b57d2c5",
}
MINUTES = {"omega": 0, "macro": 12, "flow": 24, "aion": 36, "daedalus": 48}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def control_plane(bound_at: str = "2026-09-29T06:14:28Z") -> dict:
    active = []
    for lane in ("omega", "macro", "flow", "aion", "daedalus"):
        active.append(
            {
                "title": lane,
                "automation_id": IDS[lane],
                "minute": MINUTES[lane],
                "branch": BRANCH,
                "root": f"{NS}/{lane}",
            }
        )
    return {
        "schema_version": "omega-stack-control-v2",
        "control_plane_id": CONTROL_PLANE_ID,
        "namespace_root": NS,
        "active_count": 5,
        "timezone": "America/Chicago",
        "active": active,
        "persistence_protocol_version": PROTOCOL,
        "operational_state_branch": BRANCH,
        "created_at_utc": "2026-09-29T01:31:00Z",
        "identity_binding": {
            "bound_at_utc": bound_at,
            "authoritative_ids": IDS,
        },
        "scheduler_jitter_policy": {"tolerated_start_jitter_seconds": 360},
        "execution_authorized": False,
    }


def make_root(tmp_path: Path, *, bound_at: str = "2026-09-29T06:14:28Z") -> Path:
    root = tmp_path / "repo"
    write_json(root / NS / "control_plane.json", control_plane(bound_at))
    return root


def slot_for(config, lane_name: str, when_utc: str):
    target = datetime.fromisoformat(when_utc.replace("Z", "+00:00"))
    matches = [
        s
        for s in iter_expected_slots(config, target + timedelta(minutes=1), horizon_hours=2)
        if s.lane.name == lane_name
    ]
    assert matches
    return min(matches, key=lambda s: abs((s.scheduled_utc - target).total_seconds()))


def valid_receipt(slot, *, started_offset_seconds: int = 0, **overrides) -> dict:
    payload = {
        "engine": slot.lane.name,
        "RUN_ID": f"{slot.lane.name}-{slot.slot_id}",
        "RUN_STATUS": "RUN_PERSISTED",
        "FINALIZATION_STATUS": "LIVENESS_VERIFIED",
        "WORK_PHASE_STATUS": "PENDING",
        "CONTROL_PLANE_ID": CONTROL_PLANE_ID,
        "automation_id": slot.lane.automation_id,
        "persistence_protocol_version": PROTOCOL,
        "scheduled_for": slot.scheduled_local.isoformat(),
        "started_at_utc": (slot.scheduled_utc + timedelta(seconds=started_offset_seconds))
        .isoformat()
        .replace("+00:00", "Z"),
        "NET_NEW_DELTA": "LIVENESS_PERSISTED_WORK_PENDING",
        "DATA_GAPS": [],
        "CONFLICTS": [],
        "execution_authorized": False,
        "verification_method": "GITHUB_CREATE_FILE_RESPONSE",
        "run_origin": "NATURAL_SCHEDULE",
    }
    payload.update(overrides)
    return payload


def test_config_loads_exact_authoritative_topology(tmp_path):
    cfg = load_watchdog_config(make_root(tmp_path))
    assert cfg.control_plane_id == CONTROL_PLANE_ID
    assert cfg.protocol == PROTOCOL
    assert cfg.authoritative_branch == BRANCH
    assert cfg.timezone == "America/Chicago"
    assert {x.name: (x.automation_id, x.minute) for x in cfg.lanes} == {
        lane: (IDS[lane], MINUTES[lane]) for lane in IDS
    }


def test_config_rejects_identity_binding_mismatch(tmp_path):
    root = make_root(tmp_path)
    p = root / NS / "control_plane.json"
    data = json.loads(p.read_text())
    data["identity_binding"]["authoritative_ids"]["omega"] = "wrong"
    write_json(p, data)
    with pytest.raises(ValueError, match="identity"):
        load_watchdog_config(root)


def test_expected_slots_clamp_to_identity_binding(tmp_path):
    cfg = load_watchdog_config(make_root(tmp_path, bound_at="2026-09-29T18:30:00Z"))
    slots = iter_expected_slots(cfg, datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc), horizon_hours=48)
    assert slots
    assert min(s.scheduled_utc for s in slots) >= datetime(2026, 9, 29, 18, 30, tzinfo=timezone.utc)


def test_expected_slots_cover_each_lane_hourly(tmp_path):
    cfg = load_watchdog_config(make_root(tmp_path, bound_at="2026-09-29T00:00:00Z"))
    slots = iter_expected_slots(cfg, datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc), horizon_hours=1)
    assert {s.lane.name for s in slots} == set(IDS)


def test_expected_slots_use_canonical_utc_slot_ids(tmp_path):
    cfg = load_watchdog_config(make_root(tmp_path, bound_at="2026-09-29T00:00:00Z"))
    slots = iter_expected_slots(cfg, datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc), horizon_hours=1)
    assert all(s.slot_id == s.scheduled_utc.strftime("%Y%m%dT%H%M%SZ") for s in slots)


def test_dst_fall_back_produces_distinct_utc_slots(tmp_path):
    cfg = load_watchdog_config(make_root(tmp_path, bound_at="2026-11-01T00:00:00Z"))
    slots = iter_expected_slots(cfg, datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc), horizon_hours=8)
    ids = [s.slot_id for s in slots]
    assert len(ids) == len(set(ids))
    omega_ones = [s for s in slots if s.lane.name == "omega" and s.scheduled_local.hour == 1]
    assert len(omega_ones) == 2
    assert omega_ones[0].scheduled_utc != omega_ones[1].scheduled_utc


def test_dst_spring_forward_does_not_create_nonexistent_local_slots(tmp_path):
    cfg = load_watchdog_config(make_root(tmp_path, bound_at="2027-03-14T00:00:00Z"))
    slots = iter_expected_slots(cfg, datetime(2027, 3, 14, 12, 0, tzinfo=timezone.utc), horizon_hours=10)
    assert not any(s.scheduled_local.hour == 2 for s in slots)


def test_valid_receipt_satisfies_slot(tmp_path):
    root = make_root(tmp_path, bound_at="2026-09-29T00:00:00Z")
    cfg = load_watchdog_config(root)
    slot = slot_for(cfg, "aion", "2026-09-29T17:36:00Z")
    path = root / slot.lane.root / "runs" / "aion-20260929T173625Z.json"
    write_json(path, valid_receipt(slot, started_offset_seconds=25, RUN_ID="aion-20260929T173625Z"))
    match, checks = scan_lane_receipts(root, slot, cfg)
    assert match is not None
    assert match.path == path.relative_to(root).as_posix()
    assert any(c.valid for c in checks)


@pytest.mark.parametrize(
    "field,value,error_fragment",
    [
        ("automation_id", "wrong", "automation_id"),
        ("CONTROL_PLANE_ID", "wrong", "CONTROL_PLANE_ID"),
        ("persistence_protocol_version", "wrong", "protocol"),
        ("run_origin", "GITHUB_WATCHDOG", "run_origin"),
        ("execution_authorized", True, "execution_authorized"),
        ("RUN_STATUS", "FAILED", "RUN_STATUS"),
        ("FINALIZATION_STATUS", "FAILED", "FINALIZATION_STATUS"),
        ("verification_method", "READBACK", "verification_method"),
    ],
)
def test_receipt_rejects_wrong_identity_or_status(tmp_path, field, value, error_fragment):
    root = make_root(tmp_path, bound_at="2026-09-29T00:00:00Z")
    cfg = load_watchdog_config(root)
    slot = slot_for(cfg, "omega", "2026-09-29T19:00:00Z")
    write_json(root / slot.lane.root / "runs" / "bad.json", valid_receipt(slot, **{field: value}))
    match, checks = scan_lane_receipts(root, slot, cfg)
    assert match is None
    assert any(error_fragment in err for c in checks for err in c.errors)


def test_receipt_rejects_malformed_json(tmp_path):
    root = make_root(tmp_path, bound_at="2026-09-29T00:00:00Z")
    cfg = load_watchdog_config(root)
    slot = slot_for(cfg, "omega", "2026-09-29T19:00:00Z")
    path = root / slot.lane.root / "runs" / "bad.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    match, checks = scan_lane_receipts(root, slot, cfg)
    assert match is None
    assert any("malformed" in err for c in checks for err in c.errors)


def test_receipt_rejects_wrong_nominal_slot(tmp_path):
    root = make_root(tmp_path, bound_at="2026-09-29T00:00:00Z")
    cfg = load_watchdog_config(root)
    slot = slot_for(cfg, "omega", "2026-09-29T19:00:00Z")
    wrong = valid_receipt(slot)
    wrong["scheduled_for"] = (slot.scheduled_local - timedelta(hours=1)).isoformat()
    write_json(root / slot.lane.root / "runs" / "wrong-slot.json", wrong)
    match, checks = scan_lane_receipts(root, slot, cfg)
    assert match is None
    assert any("scheduled_for" in err for c in checks for err in c.errors)


def test_receipt_jitter_boundary(tmp_path):
    root = make_root(tmp_path, bound_at="2026-09-29T00:00:00Z")
    cfg = load_watchdog_config(root)
    slot = slot_for(cfg, "flow", "2026-09-29T19:24:00Z")
    run_dir = root / slot.lane.root / "runs"
    write_json(run_dir / "late.json", valid_receipt(slot, started_offset_seconds=361))
    match, checks = scan_lane_receipts(root, slot, cfg)
    assert match is None
    assert any("jitter" in err for c in checks for err in c.errors)
    (run_dir / "late.json").unlink()
    write_json(run_dir / "ok.json", valid_receipt(slot, started_offset_seconds=360))
    match, _ = scan_lane_receipts(root, slot, cfg)
    assert match is not None


def test_before_grace_creates_no_artifacts(tmp_path):
    root = make_root(tmp_path, bound_at="2026-09-29T19:00:00Z")
    cfg = load_watchdog_config(root)
    arts = plan_reconciliation(
        root,
        cfg,
        datetime(2026, 9, 29, 19, 35, tzinfo=timezone.utc),
        grace_minutes=12,
        horizon_hours=1,
    )
    assert not [a for a in arts if a.payload.get("slot_utc") == "2026-09-29T19:24:00Z"]


def test_missing_after_grace_creates_incident_and_backlog(tmp_path):
    root = make_root(tmp_path, bound_at="2026-09-29T19:00:00Z")
    cfg = load_watchdog_config(root)
    arts = plan_reconciliation(
        root,
        cfg,
        datetime(2026, 9, 29, 19, 40, tzinfo=timezone.utc),
        grace_minutes=12,
        horizon_hours=1,
    )
    flow = [
        a
        for a in arts
        if "/flow/" in a.path.as_posix() and a.payload.get("slot_utc") == "2026-09-29T19:24:00Z"
    ]
    assert {a.payload.get("kind") for a in flow} == {
        "CHATGPT_NATURAL_RECEIPT_MISSING",
        "RECOVERY_BACKLOG_ITEM",
    }
    incident = next(a for a in flow if a.payload["kind"] == "CHATGPT_NATURAL_RECEIPT_MISSING")
    backlog = next(a for a in flow if a.payload["kind"] == "RECOVERY_BACKLOG_ITEM")
    assert incident.payload["fallback_origin"] == "GITHUB_WATCHDOG"
    assert incident.payload["natural_receipt_found"] is False
    assert incident.payload["scheduler_evidence_status"] == "UNKNOWN"
    assert incident.payload["execution_authorized"] is False
    assert backlog.payload["status"] == "RECOVERY_PENDING_AI"
    assert "run_origin" not in incident.payload
    assert "run_origin" not in backlog.payload


def test_repeat_evaluation_is_idempotent(tmp_path):
    root = make_root(tmp_path, bound_at="2026-09-29T19:00:00Z")
    cfg = load_watchdog_config(root)
    now = datetime(2026, 9, 29, 19, 40, tzinfo=timezone.utc)
    first = plan_reconciliation(root, cfg, now, grace_minutes=12, horizon_hours=1)
    write_artifacts(root, first)
    assert plan_reconciliation(root, cfg, now, grace_minutes=12, horizon_hours=1) == []


def test_late_arrival_preserves_incident_and_appends_late_record(tmp_path):
    root = make_root(tmp_path, bound_at="2026-09-29T19:00:00Z")
    cfg = load_watchdog_config(root)
    now = datetime(2026, 9, 29, 19, 40, tzinfo=timezone.utc)
    written = write_artifacts(root, plan_reconciliation(root, cfg, now, grace_minutes=12, horizon_hours=1))
    incident_path = next(p for p in written if "/missed/flow/" in p.as_posix())
    before = incident_path.read_bytes()
    slot = slot_for(cfg, "flow", "2026-09-29T19:24:00Z")
    write_json(
        root / slot.lane.root / "runs" / "flow-late.json",
        valid_receipt(slot, started_offset_seconds=30, RUN_ID="flow-late"),
    )
    later = plan_reconciliation(root, cfg, now + timedelta(minutes=5), grace_minutes=12, horizon_hours=1)
    late = [a for a in later if "/late_arrival/flow/" in a.path.as_posix()]
    assert len(late) == 1
    assert late[0].payload["classification"] == "LATE_NATURAL_RECEIPT_AFTER_INCIDENT"
    assert incident_path.read_bytes() == before
    assert not [a for a in later if "/backlog/flow/" in a.path.as_posix()]


def test_rolling_horizon_never_creates_pre_binding_incidents(tmp_path):
    root = make_root(tmp_path, bound_at="2026-09-29T18:30:00Z")
    cfg = load_watchdog_config(root)
    arts = plan_reconciliation(
        root,
        cfg,
        datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc),
        grace_minutes=12,
        horizon_hours=48,
    )
    assert arts
    assert all(
        datetime.fromisoformat(a.payload["slot_utc"].replace("Z", "+00:00")) >= cfg.identity_bound_at_utc
        for a in arts
    )


@pytest.mark.parametrize(
    "bad_path",
    [
        "/tmp/escape.json",
        "../escape.json",
        f"{NS}/omega/runs/fake.json",
        f"{NS}/omega/work/fake.json",
        "somewhere/else.json",
    ],
)
def test_writer_rejects_paths_outside_reconciliation(tmp_path, bad_path):
    root = make_root(tmp_path)
    with pytest.raises(ValueError, match="reconciliation"):
        write_artifacts(root, [Artifact(Path(bad_path), {"x": 1})])


def test_writer_is_immutable_and_deterministic(tmp_path):
    root = make_root(tmp_path)
    path = Path(f"{NS}/reconciliation/missed/omega/20260929T190000Z.json")
    art = Artifact(path, {"b": 2, "a": 1})
    [written] = write_artifacts(root, [art])
    assert written.read_text() == '{\n  "a": 1,\n  "b": 2\n}\n'
    assert write_artifacts(root, [art]) == []
    with pytest.raises(ValueError, match="immutable"):
        write_artifacts(root, [Artifact(path, {"a": 9})])


def test_cli_writes_reconciliation_and_returns_zero(tmp_path, capsys):
    root = make_root(tmp_path, bound_at="2026-09-29T19:00:00Z")
    rc = _watchdog.main(
        [
            "--root",
            str(root),
            "--now-utc",
            "2026-09-29T19:40:00Z",
            "--grace-minutes",
            "12",
            "--horizon-hours",
            "1",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"
    assert out["counts"]["missed"] >= 1
    assert out["counts"]["backlog"] >= 1


def test_cli_fails_closed_on_bad_control_plane(tmp_path, capsys):
    root = make_root(tmp_path)
    p = root / NS / "control_plane.json"
    data = json.loads(p.read_text())
    data["control_plane_id"] = "wrong"
    write_json(p, data)
    rc = _watchdog.main(["--root", str(root), "--now-utc", "2026-09-29T19:40:00Z"])
    assert rc != 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"


def test_workflow_contract():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "automation-durability-watchdog.yml"
    )
    text = workflow.read_text(encoding="utf-8")
    assert 'cron: "2-52/10 * * * *"' in text
    assert 'cron: "7-57/10 * * * *"' in text
    assert 'cron: "*/5 * * * *"' not in text
    assert 'branches: [main]' in text
    assert 'branches: [main]\n    paths:' not in text
    assert "workflow_dispatch:" in text
    assert "contents: write" in text
    assert "cancel-in-progress: false" in text
    assert "ref: main" in text
    assert "path: control" in text
    assert "ref: automation/omega-native-v2" in text
    assert "path: state" in text
    assert 'python-version: "3.11"' in text
    assert "--grace-minutes 12" in text
    assert "--horizon-hours 48" in text
    assert (
        "git -C state add automation_intelligence/omega_stack_native_v2/reconciliation"
        in text
    )
    assert "--force" not in text
    assert "force-with-lease" not in text
    assert "secrets." not in text


V3_NS = "automation_intelligence/omega_stack_native_v3"
V3_CONTROL_PLANE_ID = "omega-aion-daedalus-github-native-v3"


def v3_control_plane(bound_at: str = "2026-09-30T14:05:31Z") -> dict:
    return {
        "schema_version": "omega-stack-control-v3",
        "control_plane_id": V3_CONTROL_PLANE_ID,
        "repository": "reppiks490/Icarus-engine",
        "namespace_root": V3_NS,
        "timezone": "America/Chicago",
        "dispatch_tolerance_minutes": 4,
        "execution_authorized": False,
        "mode": "DARK",
        "created_at_utc": bound_at,
        "model_defaults": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
        "lanes": [
            {"name": "omega", "title": "omega", "minute": 0, "legacy_automation_id": IDS["omega"]},
            {"name": "macro", "title": "macro", "minute": 12, "legacy_automation_id": IDS["macro"]},
            {"name": "flow", "title": "flow", "minute": 24, "legacy_automation_id": IDS["flow"]},
            {"name": "aion", "title": "aion", "minute": 36, "legacy_automation_id": IDS["aion"]},
            {"name": "daedalus", "title": "daedalus", "minute": 48, "legacy_automation_id": IDS["daedalus"]},
        ],
    }


def make_v3_root(tmp_path: Path, *, bound_at: str = "2026-09-30T14:05:31Z") -> Path:
    root = tmp_path / "repo-v3"
    write_json(root / V3_NS / "control_plane.json", v3_control_plane(bound_at))
    return root


def v3_slot_for(config, lane_name: str, when_utc: str):
    target = datetime.fromisoformat(when_utc.replace("Z", "+00:00"))
    matches = [
        s
        for s in iter_v3_expected_slots(config, target + timedelta(minutes=1), horizon_hours=2)
        if s.lane.name == lane_name
    ]
    assert matches
    return min(matches, key=lambda s: abs((s.scheduled_utc - target).total_seconds()))


def valid_v3_receipt(slot, **overrides) -> dict:
    payload = {
        "schema_version": "omega-stack-github-native-run-v1",
        "engine": slot.lane.name,
        "lane": slot.lane.name,
        "RUN_ID": f"{slot.lane.name}-{slot.slot_id}-12345-1",
        "SLOT_ID": slot.slot_id,
        "slot_local": slot.scheduled_local.isoformat(),
        "slot_utc": slot.scheduled_utc.isoformat().replace("+00:00", "Z"),
        "started_at_utc": (slot.scheduled_utc + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        "completed_at_utc": (slot.scheduled_utc + timedelta(seconds=40)).isoformat().replace("+00:00", "Z"),
        "run_origin": "GITHUB_NATIVE_AI",
        "control_plane_id": V3_CONTROL_PLANE_ID,
        "workflow_run_id": "12345",
        "workflow_run_attempt": "1",
        "workflow_sha": "abc123",
        "repository": "reppiks490/Icarus-engine",
        "branch": "main",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "request_fingerprint": "a" * 64,
        "response_id": "resp_ok",
        "response_status": "completed",
        "output_validation_status": "VALID",
        "RUN_STATUS": "RUN_PERSISTED",
        "FINALIZATION_STATUS": "VERIFIED",
        "DATA_GAPS": [],
        "CONFLICTS": [],
        "execution_authorized": False,
    }
    payload.update(overrides)
    return payload


def test_v3_config_loads_exact_five_lane_topology(tmp_path):
    cfg = load_v3_watchdog_config(make_v3_root(tmp_path))
    assert cfg.control_plane_id == V3_CONTROL_PLANE_ID
    assert cfg.namespace_root == V3_NS
    assert [(lane.name, lane.minute) for lane in cfg.lanes] == [
        ("omega", 0),
        ("macro", 12),
        ("flow", 24),
        ("aion", 36),
        ("daedalus", 48),
    ]


def test_v3_valid_receipt_satisfies_exact_slot(tmp_path):
    root = make_v3_root(tmp_path)
    cfg = load_v3_watchdog_config(root)
    slot = v3_slot_for(cfg, "aion", "2026-09-30T14:36:00Z")
    path = root / slot.lane.root / "runs" / slot.slot_id / "aion.json"
    write_json(path, valid_v3_receipt(slot))
    match, checks = scan_v3_receipts(root, slot, cfg)
    assert match is not None
    assert match.path == path.relative_to(root).as_posix()
    assert any(c.valid for c in checks)


@pytest.mark.parametrize(
    "field,value,error_fragment",
    [
        ("run_origin", "NATURAL_SCHEDULE", "run_origin"),
        ("SLOT_ID", "wrong", "SLOT_ID"),
        ("lane", "omega", "lane"),
        ("execution_authorized", True, "execution_authorized"),
        ("output_validation_status", "INVALID", "output_validation_status"),
        ("response_status", "failed", "response_status"),
        ("control_plane_id", "wrong", "control_plane_id"),
    ],
)
def test_v3_receipt_rejects_wrong_provenance_or_status(tmp_path, field, value, error_fragment):
    root = make_v3_root(tmp_path)
    cfg = load_v3_watchdog_config(root)
    slot = v3_slot_for(cfg, "aion", "2026-09-30T14:36:00Z")
    path = root / slot.lane.root / "runs" / slot.slot_id / "bad.json"
    write_json(path, valid_v3_receipt(slot, **{field: value}))
    match, checks = scan_v3_receipts(root, slot, cfg)
    assert match is None
    assert any(error_fragment in err for c in checks for err in c.errors)


def test_v3_missing_after_grace_creates_v3_incident_and_backlog(tmp_path):
    root = make_v3_root(tmp_path, bound_at="2026-09-30T14:00:00Z")
    cfg = load_v3_watchdog_config(root)
    arts = plan_v3_reconciliation(
        root,
        cfg,
        datetime(2026, 9, 30, 14, 50, tzinfo=timezone.utc),
        grace_minutes=12,
        horizon_hours=1,
    )
    aion = [
        a
        for a in arts
        if "/aion/" in a.path.as_posix() and a.payload.get("slot_utc") == "2026-09-30T14:36:00Z"
    ]
    assert {a.payload.get("kind") for a in aion} == {
        "GITHUB_NATIVE_AI_RECEIPT_MISSING",
        "RECOVERY_BACKLOG_ITEM",
    }
    assert all(a.payload["execution_authorized"] is False for a in aion)
    written = write_artifacts(root, aion)
    assert len(written) == 2
    assert all(V3_NS in p.as_posix() for p in written)


def test_repository_v3_control_plane_is_watchdog_compatible():
    cfg = load_v3_watchdog_config(Path("."))
    assert cfg.control_plane_id == V3_CONTROL_PLANE_ID
    assert cfg.identity_bound_at_utc.tzinfo is not None
    assert [(lane.name, lane.minute) for lane in cfg.lanes] == [
        ("omega", 0),
        ("macro", 12),
        ("flow", 24),
        ("aion", 36),
        ("daedalus", 48),
    ]


def test_v3_cli_writes_reconciliation_and_returns_zero(tmp_path, capsys):
    root = make_v3_root(tmp_path, bound_at="2026-09-30T14:00:00Z")
    rc = _watchdog.main(
        [
            "--root",
            str(root),
            "--control-version",
            "v3",
            "--now-utc",
            "2026-09-30T14:50:00Z",
            "--grace-minutes",
            "12",
            "--horizon-hours",
            "1",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"
    assert out["control_version"] == "v3"
    assert out["counts"]["missed"] >= 1
    assert out["counts"]["backlog"] >= 1
    assert all(path.startswith(f"{V3_NS}/reconciliation/") for path in out["written"])


def test_workflow_contract_includes_v3_reconciliation_plane():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "automation-durability-watchdog.yml"
    )
    text = workflow.read_text(encoding="utf-8")
    assert "path: v3state" in text
    assert "--control-version v3" in text
    assert "git -C v3state add automation_intelligence/omega_stack_native_v3/reconciliation" in text
    assert "git -C v3state pull --rebase origin main" in text
    assert "git -C v3state push origin HEAD:main" in text
    assert "git -C v3state push --force" not in text
