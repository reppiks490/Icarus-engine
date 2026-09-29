from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Sequence
from zoneinfo import ZoneInfo

CONTROL_PLANE_ID = "omega-aion-daedalus-native-v2"
PROTOCOL = "omega-stack-persistence-v4.3-append-first"
AUTHORITATIVE_BRANCH = "automation/omega-native-v2"
NAMESPACE_ROOT = "automation_intelligence/omega_stack_native_v2"
EXPECTED_LANES = {"omega", "macro", "flow", "aion", "daedalus"}
RECONCILIATION_ROOT = PurePosixPath(NAMESPACE_ROOT) / "reconciliation"
WATCHDOG_SCHEMA = "omega-watchdog-reconciliation-v1"


def _parse_dt(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("datetime value must be a string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid datetime: {value}") from exc
    if dt.tzinfo is None:
        raise ValueError(f"datetime must be timezone-aware: {value}")
    return dt


def _utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class LaneConfig:
    name: str
    automation_id: str
    minute: int
    root: str


@dataclass(frozen=True)
class WatchdogConfig:
    control_plane_id: str
    protocol: str
    timezone: str
    authoritative_branch: str
    namespace_root: str
    identity_bound_at_utc: datetime
    jitter_seconds: int
    lanes: tuple[LaneConfig, ...]


@dataclass(frozen=True)
class ExpectedSlot:
    lane: LaneConfig
    scheduled_local: datetime
    scheduled_utc: datetime
    slot_id: str


@dataclass(frozen=True)
class ReceiptCheck:
    path: str
    valid: bool
    errors: tuple[str, ...]
    run_id: str | None


@dataclass(frozen=True)
class ReceiptMatch:
    path: str
    run_id: str
    payload: dict[str, object]


@dataclass(frozen=True)
class Artifact:
    path: Path
    payload: dict[str, object]


def load_watchdog_config(root: Path) -> WatchdogConfig:
    path = root / NAMESPACE_ROOT / "control_plane.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"authoritative control plane missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"authoritative control plane malformed: {path}") from exc

    if payload.get("control_plane_id") != CONTROL_PLANE_ID:
        raise ValueError("control_plane_id mismatch")
    if payload.get("persistence_protocol_version") != PROTOCOL:
        raise ValueError("persistence protocol mismatch")
    if payload.get("operational_state_branch") != AUTHORITATIVE_BRANCH:
        raise ValueError("authoritative branch mismatch")
    if payload.get("namespace_root") != NAMESPACE_ROOT:
        raise ValueError("namespace root mismatch")
    if payload.get("execution_authorized") is not False:
        raise ValueError("execution_authorized must be false")

    active = payload.get("active")
    if not isinstance(active, list) or len(active) != 5 or payload.get("active_count") != 5:
        raise ValueError("active topology must contain exactly five lanes")

    lanes: list[LaneConfig] = []
    names: set[str] = set()
    minutes: set[int] = set()
    ids: dict[str, str] = {}
    for item in active:
        if not isinstance(item, dict):
            raise ValueError("active lane must be an object")
        lane_root = item.get("root")
        if not isinstance(lane_root, str):
            raise ValueError("active lane root missing")
        lane = PurePosixPath(lane_root).name
        if lane not in EXPECTED_LANES:
            raise ValueError(f"unexpected lane: {lane}")
        minute = item.get("minute")
        if not isinstance(minute, int) or not 0 <= minute <= 59:
            raise ValueError(f"invalid minute for {lane}")
        automation_id = item.get("automation_id")
        if not isinstance(automation_id, str) or not automation_id:
            raise ValueError(f"invalid automation_id for {lane}")
        if item.get("branch") != AUTHORITATIVE_BRANCH:
            raise ValueError(f"branch mismatch for {lane}")
        if lane in names or minute in minutes:
            raise ValueError("duplicate lane or minute in active topology")
        names.add(lane)
        minutes.add(minute)
        ids[lane] = automation_id
        lanes.append(LaneConfig(lane, automation_id, minute, lane_root))

    if names != EXPECTED_LANES:
        raise ValueError("active lane set mismatch")

    binding = payload.get("identity_binding") or {}
    authoritative_ids = binding.get("authoritative_ids")
    if authoritative_ids != ids:
        raise ValueError("identity binding mismatch")
    bound_raw = binding.get("bound_at_utc") or payload.get("created_at_utc")
    identity_bound = _parse_dt(bound_raw).astimezone(timezone.utc)

    jitter = (payload.get("scheduler_jitter_policy") or {}).get("tolerated_start_jitter_seconds", 360)
    if not isinstance(jitter, int) or jitter < 0:
        raise ValueError("invalid scheduler jitter")

    timezone_name = payload.get("timezone")
    if timezone_name != "America/Chicago":
        raise ValueError("timezone mismatch")
    ZoneInfo(timezone_name)

    lanes.sort(key=lambda x: x.minute)
    return WatchdogConfig(
        control_plane_id=CONTROL_PLANE_ID,
        protocol=PROTOCOL,
        timezone=timezone_name,
        authoritative_branch=AUTHORITATIVE_BRANCH,
        namespace_root=NAMESPACE_ROOT,
        identity_bound_at_utc=identity_bound,
        jitter_seconds=jitter,
        lanes=tuple(lanes),
    )


def iter_expected_slots(
    config: WatchdogConfig,
    now_utc: datetime,
    horizon_hours: int = 48,
) -> list[ExpectedSlot]:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    now = now_utc.astimezone(timezone.utc)
    start = max(now - timedelta(hours=horizon_hours), config.identity_bound_at_utc)
    cursor = start.replace(second=0, microsecond=0)
    if cursor < start:
        cursor += timedelta(minutes=1)
    tz = ZoneInfo(config.timezone)
    by_minute = {lane.minute: lane for lane in config.lanes}
    slots: list[ExpectedSlot] = []
    while cursor <= now:
        local = cursor.astimezone(tz)
        lane = by_minute.get(local.minute)
        if lane is not None:
            slots.append(
                ExpectedSlot(
                    lane=lane,
                    scheduled_local=local,
                    scheduled_utc=cursor,
                    slot_id=cursor.strftime("%Y%m%dT%H%M%SZ"),
                )
            )
        cursor += timedelta(minutes=1)
    return slots


def _validate_receipt(payload: object, slot: ExpectedSlot, config: WatchdogConfig) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ("payload must be an object",)
    errors: list[str] = []
    expected = {
        "engine": slot.lane.name,
        "automation_id": slot.lane.automation_id,
        "CONTROL_PLANE_ID": config.control_plane_id,
        "persistence_protocol_version": config.protocol,
        "RUN_STATUS": "RUN_PERSISTED",
        "FINALIZATION_STATUS": "LIVENESS_VERIFIED",
        "verification_method": "GITHUB_CREATE_FILE_RESPONSE",
        "run_origin": "NATURAL_SCHEDULE",
        "execution_authorized": False,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            label = "protocol" if key == "persistence_protocol_version" else key
            errors.append(f"{label} mismatch")

    run_id = payload.get("RUN_ID")
    if not isinstance(run_id, str) or not run_id.startswith(f"{slot.lane.name}-"):
        errors.append("RUN_ID mismatch")

    try:
        scheduled = _parse_dt(payload.get("scheduled_for"))
        if scheduled.astimezone(timezone.utc) != slot.scheduled_utc:
            errors.append("scheduled_for mismatch")
    except (ValueError, TypeError):
        errors.append("scheduled_for invalid")

    try:
        started = _parse_dt(payload.get("started_at_utc")).astimezone(timezone.utc)
        delta = abs((started - slot.scheduled_utc).total_seconds())
        if delta > config.jitter_seconds:
            errors.append(f"started_at_utc exceeds jitter ({int(delta)}s > {config.jitter_seconds}s)")
    except (ValueError, TypeError):
        errors.append("started_at_utc invalid")
    return tuple(errors)


def scan_lane_receipts(
    root: Path,
    slot: ExpectedSlot,
    config: WatchdogConfig,
) -> tuple[ReceiptMatch | None, tuple[ReceiptCheck, ...]]:
    run_dir = root / slot.lane.root / "runs"
    checks: list[ReceiptCheck] = []
    if not run_dir.exists():
        return None, ()
    for path in sorted(run_dir.glob("*.json")):
        relative = path.relative_to(root).as_posix()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(ReceiptCheck(relative, False, (f"malformed JSON: {exc}",), None))
            continue
        errors = _validate_receipt(payload, slot, config)
        run_id = payload.get("RUN_ID") if isinstance(payload, dict) and isinstance(payload.get("RUN_ID"), str) else None
        check = ReceiptCheck(relative, not errors, errors, run_id)
        checks.append(check)
        if not errors and run_id is not None:
            return ReceiptMatch(relative, run_id, payload), tuple(checks)
    return None, tuple(checks)


def _artifact_paths(slot: ExpectedSlot) -> tuple[Path, Path, Path]:
    base = Path(NAMESPACE_ROOT) / "reconciliation"
    name = f"{slot.slot_id}.json"
    return (
        base / "missed" / slot.lane.name / name,
        base / "backlog" / slot.lane.name / name,
        base / "late_arrival" / slot.lane.name / name,
    )


def _evidence(checks: tuple[ReceiptCheck, ...]) -> list[dict[str, object]]:
    return [
        {
            "path": c.path,
            "valid": c.valid,
            "run_id": c.run_id,
            "errors": list(c.errors),
        }
        for c in checks
    ]


def plan_reconciliation(
    root: Path,
    config: WatchdogConfig,
    now_utc: datetime,
    grace_minutes: int = 12,
    horizon_hours: int = 48,
) -> list[Artifact]:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    if grace_minutes < 0:
        raise ValueError("grace_minutes must be non-negative")
    now = now_utc.astimezone(timezone.utc)
    artifacts: list[Artifact] = []
    for slot in iter_expected_slots(config, now, horizon_hours=horizon_hours):
        if now < slot.scheduled_utc + timedelta(minutes=grace_minutes):
            continue
        incident_path, backlog_path, late_path = _artifact_paths(slot)
        incident_abs = root / incident_path
        backlog_abs = root / backlog_path
        late_abs = root / late_path
        match, checks = scan_lane_receipts(root, slot, config)

        if match is not None:
            if incident_abs.exists() and not late_abs.exists():
                artifacts.append(
                    Artifact(
                        late_path,
                        {
                            "schema_version": WATCHDOG_SCHEMA,
                            "classification": "LATE_NATURAL_RECEIPT_AFTER_INCIDENT",
                            "lane": slot.lane.name,
                            "slot_utc": _utc_z(slot.scheduled_utc),
                            "slot_local": slot.scheduled_local.isoformat(),
                            "incident_ref": incident_path.as_posix(),
                            "natural_receipt_ref": match.path,
                            "natural_run_id": match.run_id,
                            "observed_at_utc": _utc_z(now),
                            "fallback_origin": "GITHUB_WATCHDOG",
                            "execution_authorized": False,
                        },
                    )
                )
            continue

        if not incident_abs.exists():
            artifacts.append(
                Artifact(
                    incident_path,
                    {
                        "schema_version": WATCHDOG_SCHEMA,
                        "kind": "CHATGPT_NATURAL_RECEIPT_MISSING",
                        "lane": slot.lane.name,
                        "expected_automation_id": slot.lane.automation_id,
                        "control_plane_id": config.control_plane_id,
                        "protocol_expected": config.protocol,
                        "slot_local": slot.scheduled_local.isoformat(),
                        "slot_utc": _utc_z(slot.scheduled_utc),
                        "adjudicated_at_utc": _utc_z(now),
                        "grace_minutes": grace_minutes,
                        "jitter_seconds": config.jitter_seconds,
                        "evidence_checked": _evidence(checks),
                        "natural_receipt_found": False,
                        "fallback_origin": "GITHUB_WATCHDOG",
                        "scheduler_evidence_status": "UNKNOWN",
                        "execution_authorized": False,
                    },
                )
            )
        if not backlog_abs.exists():
            artifacts.append(
                Artifact(
                    backlog_path,
                    {
                        "schema_version": WATCHDOG_SCHEMA,
                        "kind": "RECOVERY_BACKLOG_ITEM",
                        "status": "RECOVERY_PENDING_AI",
                        "lane": slot.lane.name,
                        "expected_automation_id": slot.lane.automation_id,
                        "control_plane_id": config.control_plane_id,
                        "protocol_expected": config.protocol,
                        "slot_local": slot.scheduled_local.isoformat(),
                        "slot_utc": _utc_z(slot.scheduled_utc),
                        "incident_ref": incident_path.as_posix(),
                        "created_at_utc": _utc_z(now),
                        "fallback_origin": "GITHUB_WATCHDOG",
                        "execution_authorized": False,
                    },
                )
            )
    artifacts.sort(key=lambda a: a.path.as_posix())
    return artifacts


def _safe_reconciliation_path(path: Path) -> PurePosixPath:
    if path.is_absolute():
        raise ValueError("artifact path must remain inside reconciliation namespace")
    pure = PurePosixPath(path.as_posix())
    if ".." in pure.parts:
        raise ValueError("artifact path must remain inside reconciliation namespace")
    root_parts = RECONCILIATION_ROOT.parts
    if pure.parts[: len(root_parts)] != root_parts:
        raise ValueError("artifact path must remain inside reconciliation namespace")
    return pure


def _serialize(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_artifacts(root: Path, artifacts: list[Artifact]) -> list[Path]:
    written: list[Path] = []
    for artifact in artifacts:
        safe = _safe_reconciliation_path(artifact.path)
        if artifact.payload.get("run_origin") == "NATURAL_SCHEDULE":
            raise ValueError("watchdog reconciliation cannot use NATURAL_SCHEDULE origin")
        target = root.joinpath(*safe.parts)
        content = _serialize(artifact.payload)
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing != content:
                raise ValueError(f"immutable reconciliation artifact differs: {safe.as_posix()}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(target)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile ICARUS automation natural-run liveness")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--now-utc")
    parser.add_argument("--grace-minutes", type=int, default=12)
    parser.add_argument("--horizon-hours", type=int, default=48)
    args = parser.parse_args(argv)
    try:
        now = _parse_dt(args.now_utc).astimezone(timezone.utc) if args.now_utc else datetime.now(timezone.utc)
        config = load_watchdog_config(args.root)
        artifacts = plan_reconciliation(
            args.root,
            config,
            now,
            grace_minutes=args.grace_minutes,
            horizon_hours=args.horizon_hours,
        )
        written = write_artifacts(args.root, artifacts)
        counts = {"missed": 0, "backlog": 0, "late_arrival": 0}
        for path in written:
            parts = path.relative_to(args.root).parts
            if "missed" in parts:
                counts["missed"] += 1
            elif "backlog" in parts:
                counts["backlog"] += 1
            elif "late_arrival" in parts:
                counts["late_arrival"] += 1
        print(json.dumps({"status": "ok", "counts": counts, "written": [p.relative_to(args.root).as_posix() for p in written]}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
