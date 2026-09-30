import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUN_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {path}: {exc}")


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def append_incident(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")


def incident_exists(path: Path, record_type: str, run_id: str) -> bool:
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return False
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("record_type") == record_type and obj.get("RUN_ID") == run_id:
            return True
    return False


def parse_run_time(run_id: str | None):
    if not run_id:
        return None
    match = RUN_TS_RE.search(run_id)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def parse_iso_utc(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def compare_run_ids(left: str | None, right: str | None) -> int | None:
    left_time = parse_run_time(left)
    right_time = parse_run_time(right)
    if left_time is None or right_time is None:
        return None
    return (left_time > right_time) - (left_time < right_time)


def git(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()


def finalization_identity(repo_root: Path, relpath: str) -> tuple[str, str]:
    commit_sha = git(repo_root, "log", "-1", "--format=%H", "--", relpath)
    blob_sha = git(repo_root, "hash-object", relpath)
    return commit_sha, blob_sha


def finalization_can_repair(
    startup_run_id: str | None,
    final_run_id: str | None,
    heartbeat_run_id: str | None,
) -> bool:
    if not final_run_id:
        return False
    if startup_run_id:
        return startup_run_id == final_run_id
    if not heartbeat_run_id or heartbeat_run_id == final_run_id:
        return True
    ordering = compare_run_ids(final_run_id, heartbeat_run_id)
    return ordering == 1


def reconcile_lane(
    repo_root: Path,
    lane: str,
    lane_root: str,
    scheduler_id: str,
    stale_minutes: int,
    now: datetime,
) -> list[str]:
    root = repo_root / lane_root
    startup_path = root / "startup_state.json"
    finalization_path = root / "finalization_state.json"
    heartbeat_path = root / "heartbeat.json"

    startup = read_json(startup_path)
    finalization = read_json(finalization_path)
    heartbeat = read_json(heartbeat_path)

    startup_run_id = startup.get("RUN_ID")
    final_run_id = finalization.get("RUN_ID")
    heartbeat_run_id = heartbeat.get("RUN_ID")
    final_status = finalization.get("RUN_STATUS")
    heartbeat_status = heartbeat.get("RUN_STATUS")
    changed: list[str] = []

    if final_run_id and final_status in {"FINALIZATION_VERIFIED", "RUN_PERSISTED"}:
        if finalization_can_repair(startup_run_id, final_run_id, heartbeat_run_id):
            if heartbeat_run_id != final_run_id or heartbeat_status != "RUN_PERSISTED":
                rel_finalization = str(finalization_path.relative_to(repo_root))
                commit_sha, blob_sha = finalization_identity(repo_root, rel_finalization)
                write_json(
                    heartbeat_path,
                    {
                        "schema_version": "scheduler-heartbeat-watchdog-v2",
                        "RUN_ID": final_run_id,
                        "RUN_STATUS": "RUN_PERSISTED",
                        "scheduler_id": scheduler_id,
                        "finalization_commit_sha": commit_sha,
                        "finalization_state_blob_sha": blob_sha,
                        "recovered_by": "restored-five-durability-watchdog",
                        "execution_authorized": False,
                    },
                )
                changed.append(str(heartbeat_path.relative_to(repo_root)))

            if startup_run_id == final_run_id and startup.get("RUN_STATUS") == "STARTED":
                write_json(
                    startup_path,
                    {
                        "schema_version": "scheduler-startup-v5.6-ready",
                        "lane": lane,
                        "scheduler_id": scheduler_id,
                        "RUN_ID": None,
                        "RUN_STATUS": "EMPTY_READY",
                        "previous_completed_run_id": final_run_id,
                        "execution_authorized": False,
                    },
                )
                changed.append(str(startup_path.relative_to(repo_root)))
            return changed

    # Legacy V5.6-and-earlier cleanup only. V5.7 workers never create STARTED.
    if startup_run_id and startup.get("RUN_STATUS") == "STARTED":
        started = parse_run_time(startup_run_id)
        if started is not None:
            age_minutes = (now - started).total_seconds() / 60
            if age_minutes >= stale_minutes:
                incident_path = root / "watchdog_incidents.jsonl"
                if not incident_exists(incident_path, "STRANDED_STARTUP_RECOVERED", startup_run_id):
                    append_incident(
                        incident_path,
                        {
                            "schema_version": "restored-five-watchdog-incident-v2",
                            "record_type": "STRANDED_STARTUP_RECOVERED",
                            "lane": lane,
                            "scheduler_id": scheduler_id,
                            "RUN_ID": startup_run_id,
                            "observed_at_utc": now.isoformat().replace("+00:00", "Z"),
                            "reason": f"NO_SAME_RUN_FINALIZATION_GT_{stale_minutes}M",
                            "execution_authorized": False,
                        },
                    )
                    changed.append(str(incident_path.relative_to(repo_root)))

                hb_vs_start = compare_run_ids(heartbeat_run_id, startup_run_id)
                if not heartbeat_run_id or heartbeat_run_id == startup_run_id or hb_vs_start != 1:
                    write_json(
                        heartbeat_path,
                        {
                            "schema_version": "scheduler-heartbeat-watchdog-v2",
                            "RUN_ID": startup_run_id,
                            "RUN_STATUS": "PARTIAL_PERSISTENCE",
                            "scheduler_id": scheduler_id,
                            "reason": f"WATCHDOG_STALE_STARTUP_NO_SAME_RUN_FINALIZATION_GT_{stale_minutes}M",
                            "execution_authorized": False,
                        },
                    )
                    changed.append(str(heartbeat_path.relative_to(repo_root)))

                write_json(
                    startup_path,
                    {
                        "schema_version": "scheduler-startup-v5.6-ready",
                        "lane": lane,
                        "scheduler_id": scheduler_id,
                        "RUN_ID": None,
                        "RUN_STATUS": "EMPTY_READY",
                        "previous_partial_run_id": startup_run_id,
                        "execution_authorized": False,
                    },
                )
                changed.append(str(startup_path.relative_to(repo_root)))

    return changed


def expected_slot(now: datetime, minute: int, grace_minutes: int) -> datetime:
    slot = now.replace(minute=minute, second=0, microsecond=0)
    if now < slot + timedelta(minutes=grace_minutes):
        slot -= timedelta(hours=1)
    return slot


def monitor_missing_receipt(
    repo_root: Path,
    lane: str,
    lane_root: str,
    scheduler_id: str,
    minute: int,
    run_prefix: str,
    grace_minutes: int,
    monitor_after: datetime | None,
    now: datetime,
) -> list[str]:
    slot = expected_slot(now, minute, grace_minutes)
    if monitor_after is not None and slot < monitor_after:
        return []

    expected_run_id = f"{run_prefix}-{slot.strftime('%Y%m%dT%H%M%SZ')}"
    root = repo_root / lane_root
    finalization_path = root / "finalization_state.json"
    incident_path = root / "watchdog_incidents.jsonl"
    finalization = read_json(finalization_path)
    final_run_id = finalization.get("RUN_ID")

    if final_run_id == expected_run_id:
        return []

    ordering = compare_run_ids(final_run_id, expected_run_id)
    # If a newer receipt is already current, do not infer whether this historical slot existed.
    if ordering == 1:
        return []

    if incident_exists(incident_path, "MISSING_CANONICAL_RECEIPT", expected_run_id):
        return []

    append_incident(
        incident_path,
        {
            "schema_version": "restored-five-watchdog-incident-v2",
            "record_type": "MISSING_CANONICAL_RECEIPT",
            "lane": lane,
            "scheduler_id": scheduler_id,
            "RUN_ID": expected_run_id,
            "slot_utc": slot.isoformat().replace("+00:00", "Z"),
            "observed_at_utc": now.isoformat().replace("+00:00", "Z"),
            "grace_minutes": grace_minutes,
            "observed_finalization_RUN_ID": final_run_id,
            "reason": "EXPECTED_SLOT_HAS_NO_CURRENT_CANONICAL_RECEIPT_AFTER_GRACE",
            "execution_authorized": False,
        },
    )
    return [str(incident_path.relative_to(repo_root))]



def monitor_missing_evidence(
    repo_root: Path,
    lane: str,
    lane_root: str,
    scheduler_id: str,
    minute: int,
    run_prefix: str,
    evidence_grace_minutes: int,
    monitor_after: datetime | None,
    now: datetime,
) -> list[str]:
    slot = expected_slot(now, minute, evidence_grace_minutes)
    if monitor_after is not None and slot < monitor_after:
        return []

    expected_run_id = f"{run_prefix}-{slot.strftime('%Y%m%dT%H%M%SZ')}"
    root = repo_root / lane_root
    finalization = read_json(root / "finalization_state.json")
    evidence = read_json(root / "evidence_state.json")
    incident_path = root / "watchdog_incidents.jsonl"

    if finalization.get("RUN_ID") != expected_run_id or finalization.get("RUN_STATUS") != "RUN_PERSISTED":
        return []

    evidence_run_id = evidence.get("RUN_ID")
    if evidence_run_id == expected_run_id and evidence.get("EVIDENCE_STATUS") in {
        "EVIDENCE_VERIFIED",
        "NO_NEW_EVIDENCE",
        "WORK_CALL_UNAVAILABLE",
    }:
        return []

    ordering = compare_run_ids(evidence_run_id, expected_run_id)
    if ordering == 1:
        return []

    if incident_exists(incident_path, "EVIDENCE_PHASE_INCOMPLETE", expected_run_id):
        return []

    append_incident(
        incident_path,
        {
            "schema_version": "restored-five-watchdog-incident-v2",
            "record_type": "EVIDENCE_PHASE_INCOMPLETE",
            "lane": lane,
            "scheduler_id": scheduler_id,
            "RUN_ID": expected_run_id,
            "slot_utc": slot.isoformat().replace("+00:00", "Z"),
            "observed_at_utc": now.isoformat().replace("+00:00", "Z"),
            "grace_minutes": evidence_grace_minutes,
            "canonical_receipt_present": True,
            "observed_evidence_RUN_ID": evidence_run_id,
            "observed_evidence_status": evidence.get("EVIDENCE_STATUS"),
            "reason": "CANONICAL_RECEIPT_EXISTS_BUT_EVIDENCE_STATE_NOT_FINALIZED_AFTER_GRACE",
            "execution_authorized": False,
        },
    )
    return [str(incident_path.relative_to(repo_root))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stale-minutes", type=int, default=30)
    parser.add_argument("--monitor-grace-minutes", type=int, default=12)
    parser.add_argument("--evidence-grace-minutes", type=int, default=20)
    parser.add_argument("--monitor-after")
    parser.add_argument(
        "--lane",
        action="append",
        default=[],
        help="lane|relative_root|scheduler_id[|minute|run_prefix]",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    now = datetime.now(timezone.utc)
    monitor_after = parse_iso_utc(args.monitor_after)
    changed: list[str] = []

    for spec in args.lane:
        parts = spec.split("|")
        if len(parts) not in {3, 5}:
            raise SystemExit(f"invalid --lane spec: {spec}")
        lane, lane_root, scheduler_id = parts[:3]
        changed.extend(
            reconcile_lane(
                repo_root,
                lane,
                lane_root,
                scheduler_id,
                args.stale_minutes,
                now,
            )
        )
        if len(parts) == 5:
            minute = int(parts[3])
            run_prefix = parts[4]
            changed.extend(
                monitor_missing_receipt(
                    repo_root,
                    lane,
                    lane_root,
                    scheduler_id,
                    minute,
                    run_prefix,
                    args.monitor_grace_minutes,
                    monitor_after,
                    now,
                )
            )
            changed.extend(
                monitor_missing_evidence(
                    repo_root,
                    lane,
                    lane_root,
                    scheduler_id,
                    minute,
                    run_prefix,
                    args.evidence_grace_minutes,
                    monitor_after,
                    now,
                )
            )

    print(json.dumps({"changed": sorted(set(changed))}, sort_keys=True))


if __name__ == "__main__":
    main()
