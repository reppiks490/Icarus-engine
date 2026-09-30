import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
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


def parse_run_time(run_id: str | None):
    if not run_id:
        return None
    match = RUN_TS_RE.search(run_id)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def git(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()


def finalization_identity(repo_root: Path, relpath: str) -> tuple[str, str]:
    commit_sha = git(repo_root, "log", "-1", "--format=%H", "--", relpath)
    blob_sha = git(repo_root, "hash-object", relpath)
    return commit_sha, blob_sha


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

    # Recover a missed heartbeat only when there is no newer in-progress run.
    if final_run_id and final_status in {"FINALIZATION_VERIFIED", "RUN_PERSISTED"}:
        safe_to_close = (not startup_run_id) or (startup_run_id == final_run_id)
        if safe_to_close:
            if heartbeat_run_id != final_run_id or heartbeat_status != "RUN_PERSISTED":
                rel_finalization = str(finalization_path.relative_to(repo_root))
                commit_sha, blob_sha = finalization_identity(repo_root, rel_finalization)
                write_json(
                    heartbeat_path,
                    {
                        "schema_version": "scheduler-heartbeat-watchdog-v1",
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
                        "schema_version": "scheduler-startup-v5.4-ready",
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

    # A bounded run that has had no finalization for 30+ minutes is stranded.
    if startup_run_id and startup.get("RUN_STATUS") == "STARTED":
        started = parse_run_time(startup_run_id)
        if started is not None:
            age_minutes = (now - started).total_seconds() / 60
            if age_minutes >= stale_minutes:
                incident_path = root / "watchdog_incidents.jsonl"
                append_incident(
                    incident_path,
                    {
                        "schema_version": "restored-five-watchdog-incident-v1",
                        "record_type": "STRANDED_STARTUP_RECOVERED",
                        "lane": lane,
                        "scheduler_id": scheduler_id,
                        "RUN_ID": startup_run_id,
                        "observed_at_utc": now.isoformat().replace("+00:00", "Z"),
                        "reason": f"NO_FINALIZATION_GT_{stale_minutes}M",
                        "execution_authorized": False,
                    },
                )
                changed.append(str(incident_path.relative_to(repo_root)))
                write_json(
                    heartbeat_path,
                    {
                        "schema_version": "scheduler-heartbeat-watchdog-v1",
                        "RUN_ID": startup_run_id,
                        "RUN_STATUS": "PARTIAL_PERSISTENCE",
                        "scheduler_id": scheduler_id,
                        "reason": f"WATCHDOG_STALE_STARTUP_NO_FINALIZATION_GT_{stale_minutes}M",
                        "execution_authorized": False,
                    },
                )
                write_json(
                    startup_path,
                    {
                        "schema_version": "scheduler-startup-v5.4-ready",
                        "lane": lane,
                        "scheduler_id": scheduler_id,
                        "RUN_ID": None,
                        "RUN_STATUS": "EMPTY_READY",
                        "previous_partial_run_id": startup_run_id,
                        "execution_authorized": False,
                    },
                )
                changed.extend(
                    [
                        str(heartbeat_path.relative_to(repo_root)),
                        str(startup_path.relative_to(repo_root)),
                    ]
                )

    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stale-minutes", type=int, default=30)
    parser.add_argument(
        "--lane",
        action="append",
        default=[],
        help="lane|relative_root|scheduler_id",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    now = datetime.now(timezone.utc)
    changed: list[str] = []

    for spec in args.lane:
        lane, lane_root, scheduler_id = spec.split("|", 2)
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

    print(json.dumps({"changed": sorted(set(changed))}, sort_keys=True))


if __name__ == "__main__":
    main()
