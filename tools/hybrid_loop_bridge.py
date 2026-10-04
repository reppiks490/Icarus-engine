from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("automation_intelligence/hybrid_loop_fabric_v1")
REGISTRY = ROOT / "registry.json"
FABRIC_ID = "icarus-account-hybrid-loop-fabric-v1"
REQUEST_SCHEMA = "icarus-hybrid-work-request-v1"
RESULT_SCHEMA = "icarus-hybrid-work-result-v1"
SCHEDULE_TO_LANE = {
    "0 * * * *": "omega",
    "12 * * * *": "macro",
    "24 * * * *": "flow",
    "36 * * * *": "aion",
    "48 * * * *": "daedalus",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_registry(repo_root: Path) -> dict[str, Any]:
    path = repo_root / REGISTRY
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "icarus-hybrid-loop-registry-v1":
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


def result_valid(repo_root: Path, lane: str, automation_id: str, request_id: str) -> bool:
    path = repo_root / result_path_for(lane, request_id)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("schema_version") == RESULT_SCHEMA
        and payload.get("fabric_id") == FABRIC_ID
        and payload.get("request_id") == request_id
        and payload.get("lane") == lane
        and payload.get("automation_id") == automation_id
        and payload.get("execution_authorized") is False
    )


def unresolved_requests(repo_root: Path, lane: str, automation_id: str, limit: int = 24) -> list[str]:
    directory = repo_root / request_dir_for(lane)
    if not directory.is_dir():
        return []
    files = sorted(
        [p for p in directory.glob("*.json") if p.name != "latest.json"],
        key=lambda p: p.name,
    )
    if limit > 0:
        files = files[-limit:]
    unresolved: list[str] = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        request_id = payload.get("request_id")
        if not isinstance(request_id, str):
            continue
        if not result_valid(repo_root, lane, automation_id, request_id):
            unresolved.append(request_id)
    return unresolved


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


def select_lanes(registry: dict[str, Any], event_name: str, schedule: str, requested_lane: str) -> list[str]:
    lanes = registry["lanes"]
    if event_name == "schedule":
        lane = SCHEDULE_TO_LANE.get(schedule)
        if lane is None:
            raise ValueError(f"unknown schedule expression: {schedule!r}")
        if lane not in lanes:
            raise ValueError(f"scheduled lane absent from registry: {lane}")
        if lanes[lane].get("state") != "ACTIVE":
            raise ValueError(f"scheduled lane is not ACTIVE: {lane}")
        return [lane]

    requested = requested_lane.strip() or "all_active"
    if requested == "all_active":
        return [name for name, cfg in lanes.items() if cfg.get("state") == "ACTIVE"]
    if requested == "all_registered":
        return list(lanes.keys())
    if requested not in lanes:
        raise ValueError(f"unknown requested lane: {requested}")
    return [requested]


def enqueue(
    repo_root: Path,
    registry: dict[str, Any],
    lane: str,
    event_name: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    now: datetime,
) -> dict[str, Any]:
    cfg = registry["lanes"][lane]
    automation_id = str(cfg["automation_id"])
    prior_unresolved = unresolved_requests(repo_root, lane, automation_id, limit=24)

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
        "lane_state_at_dispatch": cfg.get("state"),
        "requested_at_utc": z(now),
        "request_origin": "GITHUB_ACTIONS_SCHEDULE" if event_name == "schedule" else "GITHUB_ACTIONS_MANUAL",
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "scheduled_minute_local": registry.get("active_schedule", {}).get("github_dispatch_minutes", {}).get(lane),
        "contract_fingerprint": canonical_sha256(cfg),
        "contract_registry_path": str(REGISTRY),
        "bridge_contract_path": str(ROOT / "CONTRACT.md"),
        "required_result_path": str(required_result),
        "prior_unresolved_request_ids": prior_unresolved,
        "backfill_policy": registry.get("active_schedule", {}).get("backfill_policy"),
        "substantive_ai_inference_required": True,
        "github_liveness_receipt_is_not_completion": True,
        "execution_authorized": False,
    }

    write_json_exclusive(immutable_path, request)
    write_json_replace(repo_root / request_dir_for(lane) / "latest.json", request)

    unresolved_after = prior_unresolved + [request_id]
    health = {
        "schema_version": "icarus-hybrid-loop-health-v1",
        "fabric_id": FABRIC_ID,
        "lane": lane,
        "title": cfg["title"],
        "automation_id": automation_id,
        "observed_at_utc": z(now),
        "latest_request_id": request_id,
        "unresolved_request_ids_hot_window": unresolved_after,
        "unresolved_count_hot_window": len(unresolved_after),
        "health": "PENDING" if len(prior_unresolved) == 0 else "BACKLOG",
        "execution_authorized": False,
    }
    write_json_replace(repo_root / ROOT / "health" / f"{lane}.json", health)
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--schedule", default="")
    parser.add_argument("--requested-lane", default="all_active")
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    registry = load_registry(repo_root)
    selected = select_lanes(registry, args.event_name, args.schedule, args.requested_lane)
    now = utc_now()

    emitted = []
    for lane in selected:
        emitted.append(
            enqueue(
                repo_root=repo_root,
                registry=registry,
                lane=lane,
                event_name=args.event_name,
                workflow_run_id=args.workflow_run_id,
                workflow_run_attempt=args.workflow_run_attempt,
                now=now,
            )
        )

    print(json.dumps({"fabric_id": FABRIC_ID, "requests": emitted}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
