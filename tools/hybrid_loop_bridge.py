from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path("automation_intelligence/hybrid_loop_fabric_v1")
REGISTRY = ROOT / "registry.json"
FABRIC_ID = "icarus-account-hybrid-loop-fabric-v1"
REGISTRY_SCHEMAS = {"icarus-hybrid-loop-registry-v1", "icarus-hybrid-loop-registry-v2"}
REQUEST_SCHEMA = "icarus-hybrid-work-request-v1"
RESULT_SCHEMA = "icarus-hybrid-work-result-v1"
RESULT_OUTCOMES = {"MATERIAL_DELTA", "NO_MATERIAL_DELTA", "BLOCKED"}
SCHEDULE_TO_LANE = {
    "0 * * * *": "robustness_guardian",
    "10 * * * *": "advanced_csv",
    "20 * * * *": "alpha_synthesis",
    "30 * * * *": "microstructure_sensor_grid",
}
HISTORICAL_STATES = {"HISTORICAL_DISABLED", "REPOSITORY_ONLY_HISTORICAL"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def load_registry(repo_root: Path) -> dict[str, Any]:
    path = repo_root / REGISTRY
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") not in REGISTRY_SCHEMAS:
        raise ValueError("registry schema mismatch")
    if payload.get("fabric_id") != FABRIC_ID:
        raise ValueError("fabric id mismatch")
    if payload.get("execution_authorized") is not False:
        raise ValueError("execution_authorized must remain false")
    lanes = payload.get("lanes")
    if not isinstance(lanes, dict) or not lanes:
        raise ValueError("registry lanes missing")
    return payload


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def result_path_for(lane: str, request_id: str) -> Path:
    return ROOT / "results" / lane / f"{request_id}.json"


def request_dir_for(lane: str) -> Path:
    return ROOT / "requests" / lane


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def result_valid(repo_root: Path, lane: str, automation_id: str, request_id: str) -> bool:
    payload = load_json(repo_root / result_path_for(lane, request_id))
    if payload is None:
        return False

    required = {
        "schema_version",
        "fabric_id",
        "request_id",
        "lane",
        "automation_id",
        "started_at_utc",
        "completed_at_utc",
        "outcome",
        "substantive_work_performed",
        "summary",
        "evidence",
        "research_receipt_paths",
        "event_paths",
        "blockers",
        "backfilled_request_ids",
        "execution_authorized",
    }
    if not required.issubset(payload):
        return False
    if payload.get("outcome") not in RESULT_OUTCOMES:
        return False
    if not isinstance(payload.get("substantive_work_performed"), bool):
        return False
    for key in ("evidence", "research_receipt_paths", "event_paths", "blockers", "backfilled_request_ids"):
        if not isinstance(payload.get(key), list):
            return False

    return (
        payload.get("schema_version") == RESULT_SCHEMA
        and payload.get("fabric_id") == FABRIC_ID
        and payload.get("request_id") == request_id
        and payload.get("lane") == lane
        and payload.get("automation_id") == automation_id
        and payload.get("execution_authorized") is False
    )


def request_files(repo_root: Path, lane: str) -> list[Path]:
    directory = repo_root / request_dir_for(lane)
    if not directory.is_dir():
        return []
    return sorted(
        [p for p in directory.glob("*.json") if p.name != "latest.json"],
        key=lambda p: p.name,
    )


def unresolved_requests(repo_root: Path, lane: str, automation_id: str, limit: int = 24) -> list[str]:
    files = request_files(repo_root, lane)
    if limit > 0:
        files = files[-limit:]

    unresolved: list[str] = []
    for path in files:
        payload = load_json(path)
        if payload is None:
            continue
        request_id = payload.get("request_id")
        if not isinstance(request_id, str):
            continue
        if not result_valid(repo_root, lane, automation_id, request_id):
            unresolved.append(request_id)
    return unresolved


def existing_due_slots(repo_root: Path, lane: str) -> set[str]:
    slots: set[str] = set()
    for path in request_files(repo_root, lane):
        payload = load_json(path)
        if not payload:
            continue
        slot = payload.get("due_slot_utc")
        if isinstance(slot, str):
            slots.add(slot)
    return slots


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"immutable path already exists: {path}")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_json_replace(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def lane_state(cfg: dict[str, Any]) -> str:
    return str(cfg.get("current_state") or cfg.get("state") or "")


def select_lanes(
    registry: dict[str, Any],
    event_name: str,
    schedule: str,
    requested_lane: str,
) -> list[str]:
    lanes = registry["lanes"]

    if event_name == "schedule":
        lane = SCHEDULE_TO_LANE.get(schedule)
        if lane is None:
            raise ValueError(f"unknown schedule expression: {schedule!r}")
        cfg = lanes.get(lane)
        if cfg is None:
            raise ValueError(f"scheduled lane absent from registry: {lane}")
        if lane_state(cfg) != "ACTIVE":
            raise ValueError(f"scheduled lane is not ACTIVE: {lane}")
        return [lane]

    requested = requested_lane.strip() or "all_active"
    if requested == "all_active":
        return [name for name, cfg in lanes.items() if lane_state(cfg) == "ACTIVE"]

    if requested in {"all_registered", "all_historical"}:
        raise ValueError("bulk historical dispatch is forbidden; dispatch one historical lane at a time")

    if requested not in lanes:
        raise ValueError(f"unknown requested lane: {requested}")

    state = lane_state(lanes[requested])
    if state in HISTORICAL_STATES or state == "ACTIVE":
        return [requested]

    raise ValueError(f"lane is not dispatchable: {requested}")


def dispatch_minute(registry: dict[str, Any], lane: str) -> int:
    schedule = registry.get("active_schedule", {})
    mapping = schedule.get("github_dispatch_minutes_local", {})
    if lane not in mapping:
        raise ValueError(f"no dispatch minute registered for {lane}")
    minute = int(mapping[lane])
    if minute < 0 or minute > 59:
        raise ValueError(f"invalid dispatch minute for {lane}: {minute}")
    return minute


def due_slots_for_lane(
    repo_root: Path,
    registry: dict[str, Any],
    lane: str,
    now: datetime,
    max_slots: int = 24,
) -> list[datetime]:
    if lane_state(registry["lanes"][lane]) != "ACTIVE":
        return []

    activation_raw = registry.get("fabric_activated_at_utc")
    if not isinstance(activation_raw, str):
        raise ValueError("fabric_activated_at_utc missing from registry")
    activation = parse_utc(activation_raw)

    minute = dispatch_minute(registry, lane)
    first = activation.replace(minute=minute, second=0, microsecond=0)
    if first < activation:
        first += timedelta(hours=1)

    existing = existing_due_slots(repo_root, lane)
    missing: list[datetime] = []
    slot = first
    while slot <= now:
        if z(slot) not in existing:
            missing.append(slot)
        slot += timedelta(hours=1)

    return missing[:max_slots] if max_slots > 0 else missing


def build_health(
    repo_root: Path,
    lane: str,
    cfg: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    automation_id = str(cfg["automation_id"])
    unresolved = unresolved_requests(repo_root, lane, automation_id, limit=24)
    files = request_files(repo_root, lane)

    latest_request_id: str | None = None
    if files:
        latest_payload = load_json(files[-1])
        if latest_payload:
            latest_request_id = latest_payload.get("request_id")

    if unresolved:
        status = "BACKLOG" if len(unresolved) > 1 else "PENDING"
    elif latest_request_id:
        status = "RESOLVED"
    else:
        status = "IDLE"

    return {
        "schema_version": "icarus-hybrid-loop-health-v1",
        "fabric_id": FABRIC_ID,
        "lane": lane,
        "title": cfg["title"],
        "automation_id": automation_id,
        "observed_at_utc": z(now),
        "latest_request_id": latest_request_id,
        "oldest_unresolved_request_id": unresolved[0] if unresolved else None,
        "unresolved_request_ids_hot_window": unresolved,
        "unresolved_count_hot_window": len(unresolved),
        "health": status,
        "github_liveness_receipt_is_not_completion": True,
        "execution_authorized": False,
    }


def reconcile_lane(
    repo_root: Path,
    registry: dict[str, Any],
    lane: str,
    now: datetime,
) -> dict[str, Any]:
    cfg = registry["lanes"][lane]
    health = build_health(repo_root, lane, cfg, now)
    write_json_replace(repo_root / ROOT / "health" / f"{lane}.json", health)
    return health


def enqueue(
    repo_root: Path,
    registry: dict[str, Any],
    lane: str,
    event_name: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    now: datetime,
    due_slot: datetime | None = None,
) -> dict[str, Any]:
    cfg = registry["lanes"][lane]
    automation_id = str(cfg["automation_id"])
    state = lane_state(cfg)

    if event_name in {"schedule", "integrated_schedule"} and state != "ACTIVE":
        raise ValueError(f"scheduled dispatch forbidden for non-active lane {lane}")

    if event_name == "schedule":
        request_origin = "GITHUB_ACTIONS_SCHEDULE"
    elif event_name == "integrated_schedule":
        request_origin = "GITHUB_ACTIONS_INTEGRATED_SCHEDULE"
    else:
        request_origin = "GITHUB_ACTIONS_MANUAL"

    prior_unresolved = unresolved_requests(repo_root, lane, automation_id, limit=24)

    if due_slot is not None:
        request_id = f"{lane}-{compact_stamp(due_slot)}"
        immutable_path = repo_root / request_dir_for(lane) / f"{request_id}.json"
        if immutable_path.exists():
            payload = load_json(immutable_path)
            if payload is None:
                raise ValueError(f"existing immutable request is unreadable: {immutable_path}")
            return payload
    else:
        base_id = f"{lane}-{compact_stamp(now)}-gh-{workflow_run_id}-{workflow_run_attempt}"
        request_id = base_id
        immutable_path = repo_root / request_dir_for(lane) / f"{request_id}.json"
        suffix = 1
        while immutable_path.exists():
            request_id = f"{base_id}-{suffix}"
            immutable_path = repo_root / request_dir_for(lane) / f"{request_id}.json"
            suffix += 1

    required_result = result_path_for(lane, request_id)
    request = {
        "schema_version": REQUEST_SCHEMA,
        "fabric_id": FABRIC_ID,
        "request_id": request_id,
        "lane": lane,
        "title": cfg["title"],
        "automation_id": automation_id,
        "project_scope": cfg.get("project_scope"),
        "requested_at_utc": z(now),
        "request_origin": request_origin,
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "contract_fingerprint": canonical_sha256(cfg),
        "contract_registry_path": str(REGISTRY),
        "required_result_path": str(required_result),
        "prior_unresolved_request_ids": prior_unresolved,
        "backfill_policy": registry.get("backfill_policy"),
        "substantive_ai_inference_required": True,
        "github_liveness_receipt_is_not_completion": True,
        "execution_authorized": False,
    }
    if due_slot is not None:
        request["due_slot_utc"] = z(due_slot)
        request["request_created_at_utc"] = z(now)
        request["recovered_after_schedule_delay"] = now > due_slot + timedelta(minutes=10)

    write_json_exclusive(immutable_path, request)
    write_json_replace(repo_root / request_dir_for(lane) / "latest.json", request)
    reconcile_lane(repo_root, registry, lane, now)
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--schedule", default="")
    parser.add_argument("--requested-lane", default="all_active")
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--reconcile-only", action="store_true")
    parser.add_argument("--max-integrated-slots", type=int, default=24)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    registry = load_registry(repo_root)
    selected = select_lanes(
        registry,
        args.event_name,
        args.schedule,
        args.requested_lane,
    )
    now = utc_now()

    if args.reconcile_only:
        health = [
            reconcile_lane(repo_root, registry, lane, now)
            for lane in selected
        ]
        print(json.dumps({"fabric_id": FABRIC_ID, "health": health}, indent=2, sort_keys=True))
        return 0

    emitted: list[dict[str, Any]] = []

    if args.event_name == "integrated_schedule":
        for lane in selected:
            slots = due_slots_for_lane(
                repo_root=repo_root,
                registry=registry,
                lane=lane,
                now=now,
                max_slots=args.max_integrated_slots,
            )
            for slot in slots:
                emitted.append(
                    enqueue(
                        repo_root=repo_root,
                        registry=registry,
                        lane=lane,
                        event_name=args.event_name,
                        workflow_run_id=args.workflow_run_id,
                        workflow_run_attempt=args.workflow_run_attempt,
                        now=now,
                        due_slot=slot,
                    )
                )
            reconcile_lane(repo_root, registry, lane, now)
    else:
        emitted = [
            enqueue(
                repo_root=repo_root,
                registry=registry,
                lane=lane,
                event_name=args.event_name,
                workflow_run_id=args.workflow_run_id,
                workflow_run_attempt=args.workflow_run_attempt,
                now=now,
            )
            for lane in selected
        ]

    print(json.dumps({"fabric_id": FABRIC_ID, "requests": emitted}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
