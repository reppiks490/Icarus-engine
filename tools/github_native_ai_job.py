from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.github_native_ai_dispatcher import ControlPlane, Slot, load_control_plane, resolve_due_slot, terminal_artifact_exists
from tools.github_native_ai_runner import run_lane


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("requested slot must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("requested slot must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def should_execute(control: ControlPlane, *, event_name: str, execute_model: bool) -> bool:
    if event_name == "workflow_dispatch":
        return execute_model
    if event_name in {"schedule", "push", "workflow_run"}:
        return control.mode in {"SHADOW", "AUTHORITATIVE"}
    return False


def select_slot(
    control: ControlPlane,
    now_utc: datetime,
    *,
    requested_lane: str = "",
    requested_slot_utc: str = "",
) -> Slot | None:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    lane_request = requested_lane.strip().lower()
    if lane_request == "auto":
        lane_request = ""

    if requested_slot_utc.strip():
        requested = _parse_utc(requested_slot_utc.strip())
        slot = resolve_due_slot(requested, control, tolerance_minutes=0)
        if slot is None:
            raise ValueError("requested slot is not a lane boundary")
        if lane_request and slot.lane.name != lane_request:
            raise ValueError("requested lane does not match requested slot boundary")
        return slot

    now = now_utc.astimezone(timezone.utc)
    slot = resolve_due_slot(now, control, tolerance_minutes=control.dispatch_tolerance_minutes)
    if slot is None:
        return None
    if slot.scheduled_utc > now:
        return None
    if lane_request and slot.lane.name != lane_request:
        return None
    return slot



def select_pending_slots(
    root: Path,
    control: ControlPlane,
    now_utc: datetime,
    *,
    limit: int = 5,
) -> list[Slot]:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    if limit <= 0:
        raise ValueError("limit must be positive")
    if control.mode not in {"SHADOW", "AUTHORITATIVE"}:
        return []
    if control.activated_at_utc is None:
        raise ValueError("active control plane requires activated_at_utc")

    now = now_utc.astimezone(timezone.utc)
    start = max(
        control.activated_at_utc,
        now - timedelta(minutes=control.catchup_horizon_minutes),
    )
    cursor = start.replace(second=0, microsecond=0)
    if cursor < start:
        cursor += timedelta(minutes=1)

    slots: list[Slot] = []
    while cursor <= now and len(slots) < limit:
        slot = resolve_due_slot(cursor, control, tolerance_minutes=0)
        if slot is not None and slot.scheduled_utc >= control.activated_at_utc:
            if not terminal_artifact_exists(root, slot):
                slots.append(slot)
        cursor += timedelta(minutes=1)
    return slots


def select_pending_slot(
    root: Path,
    control: ControlPlane,
    now_utc: datetime,
) -> Slot | None:
    slots = select_pending_slots(root, control, now_utc, limit=1)
    return slots[0] if slots else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one GitHub-native AI lane if a slot is due.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch"))
    parser.add_argument("--requested-lane", default="")
    parser.add_argument("--requested-slot-utc", default="")
    parser.add_argument("--execute-model", action="store_true")
    parser.add_argument("--max-pending-slots", type=int, default=1)
    args = parser.parse_args(argv)

    root = Path(args.root)
    control = load_control_plane(root)
    now_override = os.environ.get("GITHUB_NATIVE_NOW_UTC", "")
    now = _parse_utc(now_override) if now_override else datetime.now(timezone.utc)
    if args.max_pending_slots <= 0:
        raise ValueError("--max-pending-slots must be positive")

    if args.event_name in {"schedule", "push", "workflow_run"} and not args.requested_slot_utc:
        slots = select_pending_slots(
            root,
            control,
            now,
            limit=args.max_pending_slots,
        )
    else:
        slot = select_slot(
            control,
            now,
            requested_lane=args.requested_lane,
            requested_slot_utc=args.requested_slot_utc,
        )
        slots = [slot] if slot is not None else []

    base = {
        "control_mode": control.mode,
        "event_name": args.event_name,
        "execute_model": bool(args.execute_model),
        "selected_lane": slots[0].lane.name if slots else None,
        "selected_slot_id": slots[0].slot_id if slots else None,
        "selected_slots": [
            {"lane": slot.lane.name, "slot_id": slot.slot_id}
            for slot in slots
        ],
    }

    if not slots:
        print(json.dumps({**base, "status": "NO_DUE_SLOT"}, sort_keys=True))
        return 0

    if not should_execute(control, event_name=args.event_name, execute_model=args.execute_model):
        status = "DIAGNOSTIC_ONLY" if args.event_name == "workflow_dispatch" else "DARK_NOOP"
        print(json.dumps({**base, "status": status}, sort_keys=True))
        return 0

    results: list[dict[str, object]] = []
    all_ok = True
    for slot in slots:
        result = run_lane(root, slot, os.environ)
        ok = result.status in {"RUN_PERSISTED", "DUPLICATE_SUPPRESSED"}
        all_ok = all_ok and ok
        results.append(
            {
                "lane": slot.lane.name,
                "slot_id": slot.slot_id,
                "status": result.status,
                "receipt_path": str(result.receipt_path) if result.receipt_path else None,
                "output_path": str(result.output_path) if result.output_path else None,
                "failure_path": str(result.failure_path) if result.failure_path else None,
            }
        )

    overall_status = (
        results[0]["status"]
        if len(results) == 1
        else ("BATCH_PERSISTED" if all_ok else "BATCH_PARTIAL_FAILURE")
    )
    print(
        json.dumps(
            {
                **base,
                "status": overall_status,
                "results": results,
            },
            sort_keys=True,
        )
    )
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
