"""Inter-repository intelligence export for ICARUS peer systems.

The exporter turns the repository's durable operational/research state into a
small provenance-bound packet that another ICARUS repository can ingest as
foreign evidence.  It never grants execution or production-decision authority,
and it preserves the distinction between substantive worker evidence and
watchdog/durability-only receipts.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "icarus-peer-intelligence-packet-v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as ex:
        raise ValueError("peer packet values must be finite JSON") from ex


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _read_json(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise ValueError(f"required peer source file missing: {path.as_posix()}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        raise ValueError(f"invalid peer source JSON: {path.as_posix()}") from ex
    if not isinstance(value, dict):
        raise ValueError(f"peer source must be a JSON object: {path.as_posix()}")
    return value


def _commit(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("source_commit must be an exact 40-character Git SHA")
    out = value.strip().lower()
    if not _SHA40.fullmatch(out):
        raise ValueError("source_commit must be an exact 40-character Git SHA")
    return out


def _time(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("observed_at must be timezone-aware ISO-8601")
    raw = value.strip()
    probe = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(probe)
    except ValueError as ex:
        raise ValueError("observed_at must be timezone-aware ISO-8601") from ex
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware ISO-8601")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _assert_no_execution_authority(value: Mapping[str, Any], label: str) -> None:
    for key in ("execution_authorized", "trading_execution_authorized"):
        if value.get(key) is True:
            raise ValueError(f"{label} {key} must remain false")


def _lane_state(
    root: Path,
    lane: Mapping[str, Any],
    *,
    source_repository: str,
    fabric_lanes: Mapping[str, Any],
) -> dict[str, Any]:
    name = str(lane.get("name") or "").strip()
    if not name:
        raise ValueError("control-plane lane is missing name")
    worker_repository = str(lane.get("worker_repository") or source_repository).strip()
    worker_root = str(lane.get("worker_root") or "").strip()
    base = {
        "name": name,
        "title": lane.get("title"),
        "minute": lane.get("minute"),
        "scheduler_id": lane.get("scheduler_id"),
        "run_prefix": lane.get("run_prefix"),
        "worker_repository": worker_repository,
        "worker_root": worker_root or None,
        "heartbeat_path": None,
        "heartbeat_blob_sha": None,
        "finalization_path": None,
        "finalization_blob_sha": None,
        "run_id": None,
        "run_status": None,
        "finalization_commit_sha": None,
        "completion_semantics": None,
        "worker_execution_observed": None,
        "evidence_status": "UNMEASURED",
        "substantive_research_evidence": False,
        "execution_authorized": False,
    }

    # A sibling repository is named but not read here.  The packet must never
    # invent its live state merely because this control plane knows its path.
    if worker_repository != source_repository:
        base["evidence_status"] = "REMOTE_PEER_UNREAD"
        return base

    fabric = fabric_lanes.get(name)
    if not isinstance(fabric, Mapping):
        fabric = {}
    heartbeat_rel = str(
        fabric.get("runtime_status_source")
        or (f"{worker_root}/heartbeat.json" if worker_root else "")
    ).strip()
    final_rel = str(
        fabric.get("finalization_state")
        or (f"{worker_root}/finalization_state.json" if worker_root else "")
    ).strip()

    base["heartbeat_path"] = heartbeat_rel or None
    base["finalization_path"] = final_rel or None
    heartbeat = _read_json(root / heartbeat_rel, required=False) if heartbeat_rel else None
    finalization = _read_json(root / final_rel, required=False) if final_rel else None
    if heartbeat is not None:
        try:
            base["heartbeat_blob_sha"] = _git_blob_sha((root / heartbeat_rel).read_bytes())
        except OSError as ex:
            raise ValueError(f"{name} heartbeat is unreadable") from ex
    if finalization is not None:
        try:
            base["finalization_blob_sha"] = _git_blob_sha((root / final_rel).read_bytes())
        except OSError as ex:
            raise ValueError(f"{name} finalization is unreadable") from ex
    if heartbeat is not None:
        _assert_no_execution_authority(heartbeat, f"{name} heartbeat")
    if finalization is not None:
        _assert_no_execution_authority(finalization, f"{name} finalization")

    run_id = None
    run_status = None
    if heartbeat:
        run_id = heartbeat.get("RUN_ID") or heartbeat.get("run_id")
        run_status = heartbeat.get("RUN_STATUS") or heartbeat.get("status")
        base["finalization_commit_sha"] = heartbeat.get("finalization_commit_sha")
    if finalization:
        run_id = run_id or finalization.get("RUN_ID") or finalization.get("run_id")
        run_status = run_status or finalization.get("RUN_STATUS") or finalization.get("status")
        base["completion_semantics"] = finalization.get("completion_semantics")
        observed = finalization.get("worker_execution_observed")
        base["worker_execution_observed"] = observed if isinstance(observed, bool) else None

    base["run_id"] = run_id
    base["run_status"] = run_status

    if heartbeat is None and finalization is None:
        base["evidence_status"] = "UNAVAILABLE"
        return base

    receipt_origin = str((finalization or {}).get("receipt_origin") or "").lower()
    durability_only = (
        str(base.get("completion_semantics") or "").upper() == "DURABILITY_RECEIPT_ONLY"
        or base.get("worker_execution_observed") is False
        or "watchdog" in receipt_origin
    )
    if durability_only:
        base["evidence_status"] = "DURABILITY_ONLY"
        return base

    if str(run_status or "").upper() == "RUN_PERSISTED":
        if base.get("worker_execution_observed") is True:
            base["evidence_status"] = "PERSISTED_WORKER_EVIDENCE"
            base["substantive_research_evidence"] = True
        else:
            base["evidence_status"] = "PERSISTED_UNCLASSIFIED"
    else:
        base["evidence_status"] = "INCOMPLETE_OR_UNVERIFIED"
    return base



def _historical_artifact(
    root: Path,
    lane: Mapping[str, Any],
    *,
    source_repository: str,
) -> dict[str, Any] | None:
    """Extract preserved historical context without treating it as current state."""
    name = str(lane.get("name") or "").strip()
    worker_repository = str(lane.get("worker_repository") or source_repository).strip()
    worker_root = str(lane.get("worker_root") or "").strip()
    if not name or worker_repository != source_repository or not worker_root:
        return None

    rel = f"{worker_root}/latest.json"
    source_path = root / rel
    latest = _read_json(source_path, required=False)
    if latest is None:
        return None
    try:
        source_artifact_blob_sha = _git_blob_sha(source_path.read_bytes())
    except OSError as ex:
        raise ValueError(f"historical latest artifact is unreadable: {rel}") from ex
    _assert_no_execution_authority(latest, f"{name} historical latest")
    core = latest.get("RUN_CORE")
    if isinstance(core, Mapping):
        _assert_no_execution_authority(core, f"{name} historical RUN_CORE")
    else:
        core = {}

    run_id = latest.get("RUN_ID") or latest.get("run_id")
    run_status = latest.get("RUN_STATUS") or latest.get("status")
    findings = core.get("findings") if isinstance(core.get("findings"), list) else []
    built_changes = core.get("built_changes") if isinstance(core.get("built_changes"), list) else []
    next_step = core.get("NEXT") if isinstance(core.get("NEXT"), str) else None

    observations = latest.get("observations")
    if not isinstance(observations, Mapping):
        observations = {}
    data_gaps = latest.get("DATA_GAPS")
    if not isinstance(data_gaps, list):
        data_gaps = []
    source_provenance = latest.get("source_provenance")
    if not isinstance(source_provenance, list):
        source_provenance = []
    net_new_delta = latest.get("NET_NEW_DELTA")
    if not isinstance(net_new_delta, Mapping):
        net_new_delta = {}

    persisted = str(run_status or "").upper() == "RUN_PERSISTED"
    if persisted and (findings or built_changes or next_step):
        status = "HISTORICAL_RESEARCH_EVIDENCE"
        context_eligible = True
    elif persisted and (
        latest.get("COLLECTION_ONLY") is True
        or observations
        or source_provenance
        or net_new_delta
    ):
        status = "HISTORICAL_COLLECTION_EVIDENCE"
        context_eligible = True
    elif persisted:
        status = "HISTORICAL_STATE_ONLY"
        context_eligible = False
    else:
        status = "HISTORICAL_UNVERIFIED"
        context_eligible = False

    summary = {
        "findings": [str(x) for x in findings],
        "built_changes": [str(x) for x in built_changes],
        "next": next_step,
        "observation_keys": sorted(str(x) for x in observations.keys()),
        "data_gaps": [str(x) for x in data_gaps],
        "source_provenance_count": len(source_provenance),
        "net_new_delta_keys": sorted(str(x) for x in net_new_delta.keys()),
    }
    lineage = {
        "base_main_sha": core.get("base_main_sha"),
        "final_main_sha": core.get("final_main_sha"),
        "run_core_sha256": latest.get("RUN_CORE_SHA256"),
        "history_blob_sha": latest.get("history_blob_sha"),
        "ledger_blob_sha": latest.get("ledger_blob_sha"),
        "history_mode": latest.get("history_mode"),
    }
    artifact = {
        "lane": name,
        "artifact_kind": "HISTORICAL_LATEST",
        "path": rel,
        "source_artifact_blob_sha": source_artifact_blob_sha,
        "run_id": run_id,
        "run_status": run_status,
        "evidence_status": status,
        "research_context_eligible": context_eligible,
        "candidate_evidence_eligible": False,
        "summary": summary,
        "lineage": lineage,
        "execution_authorized": False,
    }
    artifact["artifact_id"] = _hash(artifact)
    return artifact


def build_peer_packet(
    base_dir: str | Path,
    *,
    source_commit: str,
    observed_at: str,
    source_repository: str = "reppiks490/Icarus-engine",
) -> dict[str, Any]:
    """Build one deterministic foreign-intelligence packet from local repo state."""
    root = Path(base_dir)
    commit = _commit(source_commit)
    at = _time(observed_at)

    control_path = Path("automation_intelligence/restored_five_native/control_plane.json")
    fabric_path = Path("automation_intelligence/agent_fabric/manifest.json")
    mcp_path = Path("automation_intelligence/mcp_interface/contract.json")

    control = _read_json(root / control_path)
    fabric = _read_json(root / fabric_path)
    mcp = _read_json(root / mcp_path)
    assert control is not None and fabric is not None and mcp is not None
    source_contract_blobs = {
        "control_plane": _git_blob_sha((root / control_path).read_bytes()),
        "agent_fabric": _git_blob_sha((root / fabric_path).read_bytes()),
        "mcp_interface": _git_blob_sha((root / mcp_path).read_bytes()),
    }

    _assert_no_execution_authority(control, "control plane")
    _assert_no_execution_authority(fabric, "agent fabric")
    _assert_no_execution_authority(mcp, "MCP interface")

    declared_repo = str(control.get("repository") or "").strip()
    if declared_repo and declared_repo != source_repository:
        raise ValueError("control-plane repository does not match peer source repository")

    raw_lanes = control.get("lanes")
    if not isinstance(raw_lanes, list):
        raise ValueError("control-plane lanes must be a list")
    fabric_lanes = fabric.get("lanes")
    if not isinstance(fabric_lanes, Mapping):
        fabric_lanes = {}

    lanes = [
        _lane_state(
            root,
            lane,
            source_repository=source_repository,
            fabric_lanes=fabric_lanes,
        )
        for lane in raw_lanes
        if isinstance(lane, Mapping)
    ]
    lanes.sort(key=lambda row: row["name"])
    historical_artifacts = []
    for lane in raw_lanes:
        if not isinstance(lane, Mapping):
            continue
        artifact = _historical_artifact(
            root,
            lane,
            source_repository=source_repository,
        )
        if artifact is not None:
            historical_artifacts.append(artifact)
    historical_artifacts.sort(key=lambda row: (row["lane"], str(row.get("run_id") or "")))

    mcp_view = {
        "schema_version": mcp.get("schema_version"),
        "event_root": mcp.get("event_root"),
        "ui_api": mcp.get("ui_api"),
        "ui_tab": mcp.get("ui_tab"),
        "source_of_truth": mcp.get("source_of_truth"),
        "trading_execution_authorized": False,
    }

    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_repository": source_repository,
        "source_commit": commit,
        "observed_at": at,
        "source_contracts": {
            "control_plane": control_path.as_posix(),
            "agent_fabric": fabric_path.as_posix(),
            "mcp_interface": mcp_path.as_posix(),
        },
        "source_contract_blobs": source_contract_blobs,
        "control_plane": {
            "schema_version": control.get("schema_version"),
            "control_plane_id": control.get("control_plane_id"),
            "timezone": control.get("timezone"),
            "grace_minutes": control.get("grace_minutes"),
            "catchup_horizon_minutes": control.get("catchup_horizon_minutes"),
        },
        "lanes": lanes,
        "historical_artifacts": historical_artifacts,
        "mcp_interface": mcp_view,
        "truth_contract": {
            "foreign_repository_state_is_evidence_not_native_truth": True,
            "durability_receipt_is_not_substantive_worker_evidence": True,
            "remote_sibling_state_is_never_inferred": True,
            "exact_source_commit_required": True,
            "execution_authority_never_transfers_between_repositories": True,
            "historical_context_never_bypasses_foundry_or_evaluator": True,
        },
        "execution_authorized": False,
        "production_decision_authorized": False,
        "peer_write_authorized": False,
    }
    packet["packet_id"] = _hash(packet)
    return packet
