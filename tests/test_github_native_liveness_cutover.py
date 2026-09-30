from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools.automation_durability_watchdog import (
    iter_v3_expected_slots,
    load_v3_watchdog_config,
)
from tools.github_native_liveness_cutover import evaluate_cutover, promote_if_ready

UTC = timezone.utc
NS = "automation_intelligence/omega_stack_native_v3"


def _seed_root(tmp_path: Path, *, mode: str = "SHADOW", backend: str = "deterministic_liveness") -> Path:
    root = tmp_path / "repo"
    source_root = Path(NS)
    target_root = root / NS
    target_root.mkdir(parents=True)
    shutil.copy2(source_root / "control_plane.json", target_root / "control_plane.json")
    (target_root / "cutover").mkdir(parents=True)
    shutil.copy2(source_root / "cutover" / "acceptance.json", target_root / "cutover" / "acceptance.json")

    control_path = target_root / "control_plane.json"
    control = json.loads(control_path.read_text(encoding="utf-8"))
    control["mode"] = mode
    control["inference_backend"] = backend
    control["activated_at_utc"] = "2026-09-30T20:00:00Z"
    control["execution_authorized"] = False
    control_path.write_text(json.dumps(control, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return root


def _receipt(slot) -> dict[str, object]:
    return {
        "schema_version": "omega-stack-github-native-run-v1",
        "engine": slot.lane.name,
        "lane": slot.lane.name,
        "RUN_ID": f"{slot.lane.name}-{slot.slot_id}-999-1",
        "SLOT_ID": slot.slot_id,
        "slot_local": slot.scheduled_local.isoformat(),
        "slot_utc": slot.scheduled_utc.isoformat().replace("+00:00", "Z"),
        "started_at_utc": slot.scheduled_utc.isoformat().replace("+00:00", "Z"),
        "completed_at_utc": slot.scheduled_utc.isoformat().replace("+00:00", "Z"),
        "run_origin": "GITHUB_NATIVE_LIVENESS",
        "control_plane_id": "omega-aion-daedalus-github-native-v3",
        "inference_backend": "deterministic_liveness",
        "workflow_run_id": "999",
        "workflow_run_attempt": "1",
        "workflow_sha": "abc123",
        "repository": "reppiks490/Icarus-engine",
        "branch": "main",
        "model": "none",
        "reasoning_effort": "none",
        "request_fingerprint": "a" * 64,
        "response_id": f"deterministic:{slot.slot_id}:999.1",
        "response_status": "not_applicable",
        "output_validation_status": "VALID",
        "RUN_STATUS": "RUN_PERSISTED",
        "FINALIZATION_STATUS": "VERIFIED",
        "DATA_GAPS": ["SUBSTANTIVE_AI_INFERENCE_NOT_EXECUTED"],
        "CONFLICTS": [],
        "execution_authorized": False,
    }


def _write_receipt(root: Path, slot) -> None:
    path = root / slot.lane.root / "runs" / slot.slot_id / f"{slot.lane.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_receipt(slot), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed_latest_slots(root: Path, now: datetime, *, per_lane: int = 2, omit: tuple[str, str] | None = None) -> None:
    cfg = load_v3_watchdog_config(root)
    slots = iter_v3_expected_slots(cfg, now, horizon_hours=4)
    by_lane: dict[str, list] = {}
    for slot in slots:
        by_lane.setdefault(slot.lane.name, []).append(slot)
    for lane, lane_slots in by_lane.items():
        for slot in sorted(lane_slots, key=lambda s: s.scheduled_utc, reverse=True)[:per_lane]:
            if omit == (lane, slot.slot_id):
                continue
            _write_receipt(root, slot)


def test_not_ready_with_only_one_consecutive_receipt_per_lane(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    now = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
    _seed_latest_slots(root, now, per_lane=1)

    result = evaluate_cutover(root, now, required_consecutive=2)

    assert result["ready"] is False
    assert all(value < 2 for value in result["consecutive_valid_by_lane"].values())


def test_missing_latest_expected_slot_breaks_consecutive_chain(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    now = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
    cfg = load_v3_watchdog_config(root)
    latest_flow = max(
        (s for s in iter_v3_expected_slots(cfg, now, horizon_hours=4) if s.lane.name == "flow"),
        key=lambda s: s.scheduled_utc,
    )
    _seed_latest_slots(root, now, per_lane=2, omit=("flow", latest_flow.slot_id))

    result = evaluate_cutover(root, now, required_consecutive=2)

    assert result["ready"] is False
    assert result["consecutive_valid_by_lane"]["flow"] == 0


def test_two_consecutive_valid_receipts_per_lane_are_ready(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    now = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
    _seed_latest_slots(root, now, per_lane=2)

    result = evaluate_cutover(root, now, required_consecutive=2)

    assert result["ready"] is True
    assert result["consecutive_valid_by_lane"] == {
        "omega": 2,
        "macro": 2,
        "flow": 2,
        "aion": 2,
        "daedalus": 2,
    }
    assert all(len(refs) == 2 for refs in result["evidence_receipts"].values())


def test_promotion_is_liveness_only_and_preserves_execution_false(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    now = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
    _seed_latest_slots(root, now, per_lane=2)

    result = promote_if_ready(root, now, required_consecutive=2)

    assert result["promoted"] is True
    control = json.loads((root / NS / "control_plane.json").read_text(encoding="utf-8"))
    acceptance = json.loads((root / NS / "cutover" / "acceptance.json").read_text(encoding="utf-8"))

    assert control["mode"] == "AUTHORITATIVE"
    assert control["authoritative_scope"] == "LIVENESS_PERSISTENCE_ONLY"
    assert control["substantive_ai_inference"] is False
    assert control["execution_authorized"] is False
    assert acceptance["phase"] == "ZERO_COST_AUTHORITATIVE_LIVENESS"
    assert acceptance["authoritative_execution_source"] == "GITHUB_NATIVE_LIVENESS"
    assert acceptance["authoritative_scope"] == "LIVENESS_PERSISTENCE_ONLY"
    assert acceptance["zero_cost"] is True
    assert acceptance["execution_authorized"] is False


def test_openai_backend_cannot_be_auto_promoted_by_zero_cost_evaluator(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, backend="openai")
    now = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)

    result = promote_if_ready(root, now, required_consecutive=2)

    assert result["promoted"] is False
    assert result["reason"] == "BACKEND_NOT_DETERMINISTIC_LIVENESS"


def test_authoritative_mode_is_idempotent(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, mode="AUTHORITATIVE")
    control_path = root / NS / "control_plane.json"
    control = json.loads(control_path.read_text(encoding="utf-8"))
    control["authoritative_scope"] = "LIVENESS_PERSISTENCE_ONLY"
    control_path.write_text(json.dumps(control, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    before = control_path.read_bytes()
    result = promote_if_ready(root, datetime(2026, 9, 30, 22, 0, tzinfo=UTC), required_consecutive=2)

    assert result["promoted"] is False
    assert result["reason"] == "ALREADY_AUTHORITATIVE"
    assert control_path.read_bytes() == before
