from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CONTROL_REL = Path("automation_intelligence/restored_five_native/control_plane.json")
LEDGER_ROOT = Path("automation_intelligence/restored_five_native/receipts")


@dataclass(frozen=True)
class Lane:
    name: str
    title: str
    minute: int
    scheduler_id: str
    worker_root: str
    run_prefix: str
    worker_repository: str | None = None


@dataclass(frozen=True)
class Control:
    repository: str
    activated_at_utc: datetime
    grace_minutes: int
    catchup_horizon_minutes: int
    timezone: str
    lanes: tuple[Lane, ...]


def utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def load_control(root: Path) -> Control:
    payload = json.loads((root / CONTROL_REL).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "restored-five-native-control-v1":
        raise ValueError("control schema mismatch")
    if payload.get("execution_authorized") is not False:
        raise ValueError("execution_authorized must remain false")
    tz_name = payload.get("timezone")
    if tz_name != "America/Chicago":
        raise ValueError("timezone mismatch")
    ZoneInfo(tz_name)
    lanes = tuple(
        Lane(
            name=str(item["name"]),
            title=str(item["title"]),
            minute=int(item["minute"]),
            scheduler_id=str(item["scheduler_id"]),
            worker_root=str(item["worker_root"]),
            run_prefix=str(item["run_prefix"]),
            worker_repository=(
                str(item["worker_repository"])
                if item.get("worker_repository")
                else None
            ),
        )
        for item in payload["lanes"]
    )
    if not lanes:
        raise ValueError("at least one lane is required")
    minutes = [lane.minute for lane in lanes]
    if any(minute < 0 or minute > 59 for minute in minutes):
        raise ValueError("lane minute out of range")
    if len(set(minutes)) != len(minutes):
        raise ValueError("lane minutes must be unique")
    if len({lane.scheduler_id for lane in lanes}) != len(lanes):
        raise ValueError("scheduler IDs must be unique")
    return Control(
        repository=str(payload["repository"]),
        activated_at_utc=parse_utc(str(payload["activated_at_utc"])),
        grace_minutes=int(payload["grace_minutes"]),
        catchup_horizon_minutes=int(payload["catchup_horizon_minutes"]),
        timezone=tz_name,
        lanes=lanes,
    )


def expected_slots(control: Control, now_utc: datetime):
    now = now_utc.astimezone(timezone.utc)
    start = max(control.activated_at_utc, now - timedelta(minutes=control.catchup_horizon_minutes))
    cursor = start.replace(second=0, microsecond=0)
    by_minute = {lane.minute: lane for lane in control.lanes}
    while cursor <= now - timedelta(minutes=control.grace_minutes):
        lane = by_minute.get(cursor.minute)
        if lane is not None:
            yield lane, cursor
        cursor += timedelta(minutes=1)


def _read_external_json(repository: str, path: str) -> tuple[str, dict]:
    url = f"https://raw.githubusercontent.com/{repository}/main/{path}"
    request = Request(url, headers={"User-Agent": "restored-five-native-liveness/1"})
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        if exc.code == 404:
            return "MISSING", {}
        return "UNAVAILABLE", {}
    except (URLError, TimeoutError, OSError):
        return "UNAVAILABLE", {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "MALFORMED", {}
    return ("FOUND", payload) if isinstance(payload, dict) else ("MALFORMED", {})


def worker_receipt_status(
    root: Path,
    control: Control,
    lane: Lane,
    slot_utc: datetime,
    *,
    external_reader=_read_external_json,
) -> tuple[str, dict]:
    expected_run_id = f"{lane.run_prefix}-{slot_utc.strftime('%Y%m%dT%H%M%SZ')}"
    worker_repo = lane.worker_repository or control.repository
    relpath = f"{lane.worker_root}/finalization_state.json"

    if worker_repo == control.repository:
        path = root / relpath
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return "WORKER_RECEIPT_MISSING", {}
    else:
        read_status, obj = external_reader(worker_repo, relpath)
        if read_status == "UNAVAILABLE":
            return "WORKER_RECEIPT_CHECK_UNAVAILABLE", {}
        if read_status != "FOUND":
            return "WORKER_RECEIPT_MISSING", {}

    valid = (
        obj.get("RUN_ID") == expected_run_id
        and obj.get("RUN_STATUS") == "RUN_PERSISTED"
        and obj.get("schema_version") == "scheduler-finalization-v5.7"
        and obj.get("completion_semantics") == "DURABILITY_RECEIPT_ONLY"
        and obj.get("execution_authorized") is False
    )
    return ("CHATGPT_CANONICAL_RECEIPT_PRESENT" if valid else "WORKER_RECEIPT_MISSING"), obj


def receipt_path(root: Path, lane: Lane, slot_utc: datetime) -> Path:
    slot_id = slot_utc.strftime("%Y%m%dT%H%M%SZ")
    return root / LEDGER_ROOT / lane.name / f"{slot_id}.json"


def persist_slot(root: Path, control: Control, lane: Lane, slot_utc: datetime, now_utc: datetime) -> Path | None:
    path = receipt_path(root, lane, slot_utc)
    if path.exists():
        return None
    status, worker = worker_receipt_status(root, control, lane, slot_utc)
    expected_run_id = f"{lane.run_prefix}-{slot_utc.strftime('%Y%m%dT%H%M%SZ')}"
    payload = {
        "schema_version": "restored-five-native-liveness-receipt-v1",
        "control_plane_id": "restored-five-native-liveness-v1",
        "lane": lane.name,
        "scheduler_id": lane.scheduler_id,
        "slot_utc": utc_z(slot_utc),
        "expected_RUN_ID": expected_run_id,
        "observed_at_utc": utc_z(now_utc),
        "origin": "GITHUB_ACTIONS_NATIVE_LIVENESS",
        "worker_receipt_status": status,
        "slot_status": "WORKER_RECEIPT_VERIFIED" if status == "CHATGPT_CANONICAL_RECEIPT_PRESENT" else "FALLBACK_LIVENESS_ONLY",
        "substantive_work_claimed": False,
        "execution_authorized": False,
        "observed_worker_RUN_ID": worker.get("RUN_ID"),
        "observed_worker_schema_version": worker.get("schema_version"),
        "observed_worker_RUN_STATUS": worker.get("RUN_STATUS"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return path


def run(root: Path, now_utc: datetime) -> list[str]:
    control = load_control(root)
    changed: list[str] = []
    for lane, slot in expected_slots(control, now_utc):
        path = persist_slot(root, control, lane, slot, now_utc)
        if path is not None:
            changed.append(str(path.relative_to(root)))
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--now-utc")
    args = parser.parse_args()
    now = parse_utc(args.now_utc) if args.now_utc else datetime.now(timezone.utc)
    changed = run(Path(args.root).resolve(), now)
    print(json.dumps({"changed": changed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
