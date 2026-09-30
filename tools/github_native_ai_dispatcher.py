from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NAMESPACE_ROOT = "automation_intelligence/omega_stack_native_v3"
EXPECTED_LANES = (
    ("omega", 0),
    ("macro", 12),
    ("flow", 24),
    ("aion", 36),
    ("daedalus", 48),
)


@dataclass(frozen=True)
class LaneConfig:
    name: str
    title: str
    minute: int
    legacy_automation_id: str


@dataclass(frozen=True)
class ControlPlane:
    schema_version: str
    control_plane_id: str
    repository: str
    namespace_root: str
    timezone: str
    dispatch_tolerance_minutes: int
    execution_authorized: bool
    mode: str
    model: str
    reasoning_effort: str
    lanes: tuple[LaneConfig, ...]


@dataclass(frozen=True)
class Slot:
    lane: LaneConfig
    scheduled_local: datetime
    scheduled_utc: datetime
    slot_id: str


def load_control_plane(root: Path) -> ControlPlane:
    path = root / NAMESPACE_ROOT / "control_plane.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"v3 control plane missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"v3 control plane malformed: {path}") from exc

    if payload.get("schema_version") != "omega-stack-control-v3":
        raise ValueError("v3 schema mismatch")
    if payload.get("namespace_root") != NAMESPACE_ROOT:
        raise ValueError("v3 namespace mismatch")
    if payload.get("execution_authorized") is not False:
        raise ValueError("execution_authorized must be false")
    timezone_name = payload.get("timezone")
    if timezone_name != "America/Chicago":
        raise ValueError("timezone mismatch")
    ZoneInfo(timezone_name)

    raw_lanes = payload.get("lanes")
    if not isinstance(raw_lanes, list) or len(raw_lanes) != len(EXPECTED_LANES):
        raise ValueError("exactly five lanes are required")

    lanes: list[LaneConfig] = []
    observed: list[tuple[str, int]] = []
    for raw in raw_lanes:
        if not isinstance(raw, dict):
            raise ValueError("lane entry must be an object")
        lane = LaneConfig(
            name=str(raw.get("name")),
            title=str(raw.get("title")),
            minute=int(raw.get("minute")),
            legacy_automation_id=str(raw.get("legacy_automation_id")),
        )
        lanes.append(lane)
        observed.append((lane.name, lane.minute))
    if tuple(observed) != EXPECTED_LANES:
        raise ValueError("lane topology mismatch")
    if len({lane.legacy_automation_id for lane in lanes}) != 5:
        raise ValueError("lane automation identities must be unique")

    defaults = payload.get("model_defaults")
    if not isinstance(defaults, dict):
        raise ValueError("model_defaults missing")

    tolerance = payload.get("dispatch_tolerance_minutes")
    if not isinstance(tolerance, int) or tolerance < 0 or tolerance > 5:
        raise ValueError("invalid dispatch tolerance")

    return ControlPlane(
        schema_version=payload["schema_version"],
        control_plane_id=str(payload.get("control_plane_id")),
        repository=str(payload.get("repository")),
        namespace_root=payload["namespace_root"],
        timezone=timezone_name,
        dispatch_tolerance_minutes=tolerance,
        execution_authorized=False,
        mode=str(payload.get("mode")),
        model=str(defaults.get("model")),
        reasoning_effort=str(defaults.get("reasoning_effort")),
        lanes=tuple(lanes),
    )


def resolve_due_slot(
    now_utc: datetime,
    control: ControlPlane,
    tolerance_minutes: int | None = None,
) -> Slot | None:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    tolerance = control.dispatch_tolerance_minutes if tolerance_minutes is None else tolerance_minutes
    if tolerance < 0 or tolerance > 5:
        raise ValueError("tolerance_minutes must be between 0 and 5")

    now = now_utc.astimezone(timezone.utc)
    tz = ZoneInfo(control.timezone)
    by_minute = {lane.minute: lane for lane in control.lanes}
    start = (now - timedelta(minutes=tolerance)).replace(second=0, microsecond=0)
    end = now + timedelta(minutes=tolerance)

    candidates: list[tuple[float, datetime, LaneConfig, datetime]] = []
    cursor = start
    while cursor <= end:
        local = cursor.astimezone(tz)
        lane = by_minute.get(local.minute)
        if lane is not None:
            delta = abs((now - cursor).total_seconds())
            if delta <= tolerance * 60:
                candidates.append((delta, cursor, lane, local))
        cursor += timedelta(minutes=1)

    if not candidates:
        return None

    _, scheduled_utc, lane, scheduled_local = min(candidates, key=lambda item: (item[0], item[1]))
    return Slot(
        lane=lane,
        scheduled_local=scheduled_local,
        scheduled_utc=scheduled_utc,
        slot_id=scheduled_utc.strftime("%Y%m%dT%H%M%SZ"),
    )


def terminal_artifact_exists(root: Path, slot: Slot) -> bool:
    for kind in ("runs", "outputs", "failures"):
        slot_dir = root / NAMESPACE_ROOT / "lanes" / slot.lane.name / kind / slot.slot_id
        if slot_dir.is_dir() and any(path.is_file() for path in slot_dir.glob("*.json")):
            return True
    return False
