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


def finalization_repairable(finalization: dict) -> bool:
    run_id = finalization.get("RUN_ID")
    status = finalization.get("RUN_STATUS")
    if not run_id or status not in {"FINALIZATION_VERIFIED", "RUN_PERSISTED"}:
        return False
    if finalization.get("schema_version") == "scheduler-finalization-v5.7":
        return canonical_receipt_valid(finalization, run_id)
    return finalization.get("execution_authorized") is not True


def heartbeat_mirror_valid(
    heartbeat: dict,
    expected_run_id: str,
    expected_commit_sha: str,
    expected_blob_sha: str,
) -> bool:
    return (
        heartbeat.get("RUN_ID") == expected_run_id
        and heartbeat.get("RUN_STATUS") == "RUN_PERSISTED"
        and heartbeat.get("finalization_commit_sha") == expected_commit_sha
        and heartbeat.get("finalization_state_blob_sha") == expected_blob_sha
        and heartbeat.get("execution_authorized") is False
    )


def finalization_can_repair(
    startup_run_id: str | None,
    final_run_id: str | None,
    heartbeat_run_id: str | None,
) -> bool:
    if not final_run_id:
        return False

    # Heartbeat monotonicity is absolute: never repair from an older finalization.
    if heartbeat_run_id and heartbeat_run_id != final_run_id:
        hb_ordering = compare_run_ids(heartbeat_run_id, final_run_id)
        if hb_ordering == 1:
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
    receipt_first_stale_minutes: int,
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

    if finalization_repairable(finalization):
        if finalization_can_repair(startup_run_id, final_run_id, heartbeat_run_id):
            rel_finalization = str(finalization_path.relative_to(repo_root))
            commit_sha, blob_sha = finalization_identity(repo_root, rel_finalization)
            if not heartbeat_mirror_valid(
                heartbeat,
                final_run_id,
                commit_sha,
                blob_sha,
            ):
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

    # Legacy cleanup only. V5.7 workers never create STARTED.
    if startup_run_id and startup.get("RUN_STATUS") == "STARTED":
        started = parse_run_time(startup_run_id)
        if started is not None:
            age_minutes = (now - started).total_seconds() / 60
            startup_schema = startup.get("schema_version")
            effective_stale_minutes = (
                receipt_first_stale_minutes
                if startup_schema == "scheduler-startup-v5.6"
                else stale_minutes
            )
            if age_minutes >= effective_stale_minutes:
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
                            "reason": f"NO_SAME_RUN_FINALIZATION_GT_{effective_stale_minutes}M",
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
                            "reason": f"WATCHDOG_STALE_STARTUP_NO_SAME_RUN_FINALIZATION_GT_{effective_stale_minutes}M",
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


def git_json_history(repo_root: Path, relpath: str, max_commits: int = 500) -> list[dict]:
    try:
        output = subprocess.check_output(
            ["git", "log", f"-n{max_commits}", "--format=%H", "--", relpath],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    records: list[dict] = []
    for commit_sha in [line for line in output.splitlines() if line]:
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{commit_sha}:{relpath}"],
                cwd=repo_root,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            obj = json.loads(raw)
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def records_for_run(repo_root: Path, relpath: str, expected_run_id: str) -> list[dict]:
    records: list[dict] = []
    current = read_json(repo_root / relpath)
    if current.get("RUN_ID") == expected_run_id:
        records.append(current)
    for obj in git_json_history(repo_root, relpath):
        if obj.get("RUN_ID") == expected_run_id and obj not in records:
            records.append(obj)
    return records


def historical_record_state(
    repo_root: Path,
    relpath: str,
    expected_run_id: str,
    validator,
) -> str:
    records = records_for_run(repo_root, relpath, expected_run_id)
    if any(validator(obj, expected_run_id) for obj in records):
        return "VALID"
    return "MALFORMED" if records else "MISSING"


def eligible_slots(
    now: datetime,
    minute: int,
    grace_minutes: int,
    monitor_after: datetime | None,
    horizon_hours: int,
) -> list[datetime]:
    cutoff = now - timedelta(minutes=grace_minutes)
    latest = cutoff.replace(minute=minute, second=0, microsecond=0)
    if latest > cutoff:
        latest -= timedelta(hours=1)

    floor = now - timedelta(hours=max(1, horizon_hours))
    if monitor_after is not None and monitor_after > floor:
        floor = monitor_after

    slots: list[datetime] = []
    slot = latest
    while slot >= floor:
        slots.append(slot)
        slot -= timedelta(hours=1)
    slots.reverse()
    return slots


def expected_slot(now: datetime, minute: int, grace_minutes: int) -> datetime:
    slot = now.replace(minute=minute, second=0, microsecond=0)
    if now < slot + timedelta(minutes=grace_minutes):
        slot -= timedelta(hours=1)
    return slot


def canonical_receipt_valid(finalization: dict, expected_run_id: str) -> bool:
    return (
        finalization.get("RUN_ID") == expected_run_id
        and finalization.get("RUN_STATUS") == "RUN_PERSISTED"
        and finalization.get("schema_version") == "scheduler-finalization-v5.7"
        and finalization.get("completion_semantics") == "DURABILITY_RECEIPT_ONLY"
        and finalization.get("execution_authorized") is False
    )


def _monitor_receipt_slots(
    repo_root: Path,
    lane: str,
    lane_root: str,
    scheduler_id: str,
    run_prefix: str,
    grace_minutes: int,
    slots: list[datetime],
) -> list[str]:
    root = repo_root / lane_root
    relpath = str((root / "finalization_state.json").relative_to(repo_root))
    incident_path = root / "watchdog_incidents.jsonl"
    changed = False

    for slot in slots:
        expected_run_id = f"{run_prefix}-{slot.strftime('%Y%m%dT%H%M%SZ')}"
        state = historical_record_state(
            repo_root,
            relpath,
            expected_run_id,
            canonical_receipt_valid,
        )
        if state == "VALID":
            continue

        record_type = (
            "MALFORMED_CANONICAL_RECEIPT"
            if state == "MALFORMED"
            else "MISSING_CANONICAL_RECEIPT"
        )
        if incident_exists(incident_path, record_type, expected_run_id):
            continue

        records = records_for_run(repo_root, relpath, expected_run_id)
        observed = records[0] if records else {}
        append_incident(
            incident_path,
            {
                "schema_version": "restored-five-watchdog-incident-v4",
                "record_type": record_type,
                "lane": lane,
                "scheduler_id": scheduler_id,
                "RUN_ID": expected_run_id,
                "slot_utc": slot.isoformat().replace("+00:00", "Z"),
                "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "grace_minutes": grace_minutes,
                "observed_finalization_RUN_ID": observed.get("RUN_ID"),
                "observed_schema_version": observed.get("schema_version"),
                "observed_RUN_STATUS": observed.get("RUN_STATUS"),
                "observed_completion_semantics": observed.get("completion_semantics"),
                "observed_execution_authorized": observed.get("execution_authorized"),
                "history_reconstructed": True,
                "reason": (
                    "EXPECTED_RUN_ID_PRESENT_IN_GIT_HISTORY_BUT_CANONICAL_RECEIPT_FIELDS_INVALID"
                    if state == "MALFORMED"
                    else "EXPECTED_SLOT_HAS_NO_VALID_CANONICAL_RECEIPT_IN_GIT_HISTORY_AFTER_GRACE"
                ),
                "execution_authorized": False,
            },
        )
        changed = True

    return [str(incident_path.relative_to(repo_root))] if changed else []


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
    return _monitor_receipt_slots(
        repo_root,
        lane,
        lane_root,
        scheduler_id,
        run_prefix,
        grace_minutes,
        [slot],
    )


def monitor_receipt_horizon(
    repo_root: Path,
    lane: str,
    lane_root: str,
    scheduler_id: str,
    minute: int,
    run_prefix: str,
    grace_minutes: int,
    monitor_after: datetime | None,
    now: datetime,
    horizon_hours: int,
) -> list[str]:
    return _monitor_receipt_slots(
        repo_root,
        lane,
        lane_root,
        scheduler_id,
        run_prefix,
        grace_minutes,
        eligible_slots(now, minute, grace_minutes, monitor_after, horizon_hours),
    )

def evidence_record_valid(evidence: dict, expected_run_id: str) -> bool:
    return (
        evidence.get("RUN_ID") == expected_run_id
        and evidence.get("EVIDENCE_STATUS") in {
            "EVIDENCE_VERIFIED",
            "NO_NEW_EVIDENCE",
            "WORK_CALL_UNAVAILABLE",
        }
        and evidence.get("schema_version") == "scheduler-evidence-v5.7"
        and evidence.get("execution_authorized") is False
    )


def _monitor_evidence_slots(
    repo_root: Path,
    lane: str,
    lane_root: str,
    scheduler_id: str,
    run_prefix: str,
    evidence_grace_minutes: int,
    slots: list[datetime],
) -> list[str]:
    root = repo_root / lane_root
    final_rel = str((root / "finalization_state.json").relative_to(repo_root))
    evidence_rel = str((root / "evidence_state.json").relative_to(repo_root))
    incident_path = root / "watchdog_incidents.jsonl"
    changed = False

    for slot in slots:
        expected_run_id = f"{run_prefix}-{slot.strftime('%Y%m%dT%H%M%SZ')}"
        receipt_state = historical_record_state(
            repo_root,
            final_rel,
            expected_run_id,
            canonical_receipt_valid,
        )
        if receipt_state != "VALID":
            continue

        evidence_state = historical_record_state(
            repo_root,
            evidence_rel,
            expected_run_id,
            evidence_record_valid,
        )
        if evidence_state == "VALID":
            continue

        record_type = (
            "MALFORMED_EVIDENCE_STATE"
            if evidence_state == "MALFORMED"
            else "EVIDENCE_PHASE_INCOMPLETE"
        )
        if incident_exists(incident_path, record_type, expected_run_id):
            continue

        records = records_for_run(repo_root, evidence_rel, expected_run_id)
        observed = records[0] if records else {}
        append_incident(
            incident_path,
            {
                "schema_version": "restored-five-watchdog-incident-v4",
                "record_type": record_type,
                "lane": lane,
                "scheduler_id": scheduler_id,
                "RUN_ID": expected_run_id,
                "slot_utc": slot.isoformat().replace("+00:00", "Z"),
                "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "grace_minutes": evidence_grace_minutes,
                "canonical_receipt_present": True,
                "observed_evidence_RUN_ID": observed.get("RUN_ID"),
                "observed_evidence_status": observed.get("EVIDENCE_STATUS"),
                "observed_evidence_schema_version": observed.get("schema_version"),
                "observed_evidence_execution_authorized": observed.get("execution_authorized"),
                "history_reconstructed": True,
                "reason": (
                    "EXPECTED_RUN_ID_PRESENT_IN_GIT_HISTORY_BUT_EVIDENCE_STATE_FIELDS_INVALID"
                    if evidence_state == "MALFORMED"
                    else "CANONICAL_RECEIPT_EXISTS_BUT_NO_VALID_EVIDENCE_STATE_IN_GIT_HISTORY_AFTER_GRACE"
                ),
                "execution_authorized": False,
            },
        )
        changed = True

    return [str(incident_path.relative_to(repo_root))] if changed else []


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
    return _monitor_evidence_slots(
        repo_root,
        lane,
        lane_root,
        scheduler_id,
        run_prefix,
        evidence_grace_minutes,
        [slot],
    )


def monitor_evidence_horizon(
    repo_root: Path,
    lane: str,
    lane_root: str,
    scheduler_id: str,
    minute: int,
    run_prefix: str,
    evidence_grace_minutes: int,
    monitor_after: datetime | None,
    now: datetime,
    horizon_hours: int,
) -> list[str]:
    return _monitor_evidence_slots(
        repo_root,
        lane,
        lane_root,
        scheduler_id,
        run_prefix,
        evidence_grace_minutes,
        eligible_slots(
            now,
            minute,
            evidence_grace_minutes,
            monitor_after,
            horizon_hours,
        ),
    )

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stale-minutes", type=int, default=30)
    parser.add_argument("--receipt-first-stale-minutes", type=int, default=12)
    parser.add_argument("--monitor-grace-minutes", type=int, default=12)
    parser.add_argument("--evidence-grace-minutes", type=int, default=20)
    parser.add_argument("--monitor-after")
    parser.add_argument("--horizon-hours", type=int, default=48)
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
                args.receipt_first_stale_minutes,
                now,
            )
        )
        if len(parts) == 5:
            minute = int(parts[3])
            run_prefix = parts[4]
            changed.extend(
                monitor_receipt_horizon(
                    repo_root,
                    lane,
                    lane_root,
                    scheduler_id,
                    minute,
                    run_prefix,
                    args.monitor_grace_minutes,
                    monitor_after,
                    now,
                    args.horizon_hours,
                )
            )
            changed.extend(
                monitor_evidence_horizon(
                    repo_root,
                    lane,
                    lane_root,
                    scheduler_id,
                    minute,
                    run_prefix,
                    args.evidence_grace_minutes,
                    monitor_after,
                    now,
                    args.horizon_hours,
                )
            )

    print(json.dumps({"changed": sorted(set(changed))}, sort_keys=True))


if __name__ == "__main__":
    main()
