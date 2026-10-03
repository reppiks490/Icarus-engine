from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping

from icarus_engine.interrepo_bridge import build_peer_packet


DEFAULT_OUTPUT = Path("automation_intelligence/interrepo/latest.json")
CANONICAL_ACCEPTANCE_SCHEMA = "icarus-engine-federation-acceptance-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_packet_source_identity(
    packet: dict,
    *,
    expected_head: str,
) -> None:
    """Fail closed unless the packet is bound to the exact source HEAD and zero authority."""
    head = str(expected_head or "").strip().lower()
    if len(head) != 40 or any(ch not in "0123456789abcdef" for ch in head):
        raise ValueError("expected_head must be an exact 40-character Git SHA")
    if str(packet.get("source_commit") or "").lower() != head:
        raise ValueError("peer packet source_commit does not match export HEAD")
    for key in ("execution_authorized", "production_decision_authorized", "peer_write_authorized"):
        if packet.get(key) is not False:
            raise ValueError(f"peer packet authority invariant failed: {key}")
    claimed = str(packet.get("packet_id") or "").lower()
    unsigned = dict(packet)
    unsigned.pop("packet_id", None)
    computed = __import__("hashlib").sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    if claimed != computed:
        raise ValueError("peer packet_id does not match canonical packet content")


def _git_show_bytes(root: Path, commit: str, path: str) -> bytes | None:
    rel = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise ValueError("packet input path is invalid")
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{rel}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _require_path_matches_commit(root: Path, commit: str, path: str) -> bytes | None:
    rel = str(path or "").strip().replace("\\", "/").lstrip("/")
    committed = _git_show_bytes(root, commit, rel)
    current_path = root / rel
    current_exists = current_path.is_file()
    if current_exists:
        current = current_path.read_bytes()
        if committed is None:
            raise ValueError(f"packet input is uncommitted at source revision: {rel}")
        if current != committed:
            raise ValueError(f"packet input drift from source revision: {rel}")
        return current
    if committed is not None:
        raise ValueError(f"packet input missing from working tree but present at source revision: {rel}")
    return None


def verify_packet_source_inputs(
    packet: dict,
    *,
    root: Path,
    expected_head: str,
) -> None:
    """Prove every local packet input matches the exact Git revision it claims."""
    root = root.resolve()
    verify_packet_source_identity(packet, expected_head=expected_head)
    head = str(expected_head).strip().lower()
    source_repository = str(packet.get("source_repository") or "").strip()
    if source_repository != "reppiks490/Icarus-engine":
        raise ValueError("peer packet source repository identity mismatch")

    source_contracts = packet.get("source_contracts")
    if not isinstance(source_contracts, dict) or not source_contracts:
        raise ValueError("peer packet source contracts are missing")
    source_contract_blobs = packet.get("source_contract_blobs")
    if not isinstance(source_contract_blobs, dict):
        raise ValueError("peer packet source contract blob witnesses are missing")
    if set(source_contract_blobs) != set(source_contracts):
        raise ValueError("peer packet source contract blob witness keys mismatch")
    verified_paths: set[str] = set()
    for key, path in source_contracts.items():
        rel = str(path or "").strip()
        raw = _require_path_matches_commit(root, head, rel)
        if raw is None:
            raise ValueError(f"peer packet source contract missing at source revision: {rel}")
        header = f"blob {len(raw)}\0".encode("ascii")
        actual_blob = hashlib.sha1(header + raw).hexdigest()
        if source_contract_blobs.get(key) != actual_blob:
            raise ValueError(f"peer packet source contract blob witness mismatch: {key}")
        verified_paths.add(rel)

    fabric_path = str(source_contracts.get("agent_fabric") or "")
    fabric_raw = _require_path_matches_commit(root, head, fabric_path)
    if fabric_raw is None:
        raise ValueError("peer packet agent-fabric source contract is missing")
    fabric = json.loads(fabric_raw.decode("utf-8"))
    fabric_lanes = fabric.get("lanes") if isinstance(fabric, dict) else {}
    if not isinstance(fabric_lanes, dict):
        fabric_lanes = {}

    lanes = packet.get("lanes")
    if not isinstance(lanes, list):
        raise ValueError("peer packet lanes are missing")
    for lane in lanes:
        if not isinstance(lane, dict):
            raise ValueError("peer packet lane is not an object")
        if str(lane.get("worker_repository") or "") != source_repository:
            continue
        name = str(lane.get("name") or "").strip()
        worker_root = str(lane.get("worker_root") or "").strip()
        fabric_lane = fabric_lanes.get(name)
        if not isinstance(fabric_lane, dict):
            fabric_lane = {}
        heartbeat = str(
            fabric_lane.get("runtime_status_source")
            or (f"{worker_root}/heartbeat.json" if worker_root else "")
        ).strip()
        finalization = str(
            fabric_lane.get("finalization_state")
            or (f"{worker_root}/finalization_state.json" if worker_root else "")
        ).strip()
        witnesses = (
            ("heartbeat_path", "heartbeat_blob_sha", heartbeat),
            ("finalization_path", "finalization_blob_sha", finalization),
        )
        for path_key, blob_key, rel in witnesses:
            expected_path = rel or None
            if lane.get(path_key) != expected_path:
                raise ValueError(f"peer lane source path witness mismatch: {name}:{path_key}")
            raw = None
            if rel:
                raw = _require_path_matches_commit(root, head, rel)
                verified_paths.add(rel)
            claimed_blob = lane.get(blob_key)
            if raw is None:
                if claimed_blob is not None:
                    raise ValueError(f"peer lane source blob witness mismatch: {name}:{blob_key}")
            else:
                header = f"blob {len(raw)}\0".encode("ascii")
                actual_blob = hashlib.sha1(header + raw).hexdigest()
                if claimed_blob != actual_blob:
                    raise ValueError(f"peer lane source blob witness mismatch: {name}:{blob_key}")

    historical = packet.get("historical_artifacts")
    if not isinstance(historical, list):
        raise ValueError("peer packet historical artifacts are missing")
    for artifact in historical:
        if not isinstance(artifact, dict):
            raise ValueError("peer historical artifact is not an object")
        rel = str(artifact.get("path") or "").strip()
        raw = _require_path_matches_commit(root, head, rel)
        if raw is None:
            raise ValueError(f"peer historical artifact source is missing at source revision: {rel}")
        expected_blob = str(artifact.get("source_artifact_blob_sha") or "").lower()
        header = f"blob {len(raw)}\0".encode("ascii")
        actual_blob = hashlib.sha1(header + raw).hexdigest()
        if expected_blob != actual_blob:
            raise ValueError(
                f"peer historical artifact blob does not match source revision: {rel}"
            )


def _is_hex(value: Any, length: int) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == length and all(ch in "0123456789abcdef" for ch in text)


def _normalize_canonical_acceptance(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {
            "status": "UNAVAILABLE",
            "schema_version": CANONICAL_ACCEPTANCE_SCHEMA,
            "accepted_by_repository": "reppiks490/Icarus",
            "producer_repository": "reppiks490/Icarus-engine",
            "authority": "RESEARCH",
            "required_for_export": False,
            "execution_authorized": False,
            "production_decision_authorized": False,
            "automatic_model_promotion": False,
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("canonical ICARUS acceptance must be a JSON object")
    if payload.get("schema_version") != CANONICAL_ACCEPTANCE_SCHEMA:
        raise ValueError("unsupported canonical ICARUS acceptance schema")
    if payload.get("accepted_by_repository") != "reppiks490/Icarus":
        raise ValueError("canonical ICARUS acceptance repository identity mismatch")
    if payload.get("producer_repository") != "reppiks490/Icarus-engine":
        raise ValueError("canonical ICARUS acceptance producer identity mismatch")
    if payload.get("authority") != "RESEARCH":
        raise ValueError("canonical ICARUS acceptance authority must remain RESEARCH")
    for key in (
        "execution_authorized",
        "production_decision_authorized",
        "automatic_model_promotion",
    ):
        if payload.get(key) is not False:
            raise ValueError(f"canonical ICARUS acceptance attempts authority escalation: {key}")
    if not _is_hex(payload.get("accepted_by_icarus_commit"), 40):
        raise ValueError("canonical ICARUS acceptance validator commit is invalid")
    if not _is_hex(payload.get("peer_packet_id"), 64):
        raise ValueError("canonical ICARUS acceptance peer packet ID is invalid")
    if not _is_hex(payload.get("peer_packet_blob_sha"), 40):
        raise ValueError("canonical ICARUS acceptance peer packet blob is invalid")
    if not _is_hex(payload.get("peer_source_commit"), 40):
        raise ValueError("canonical ICARUS acceptance peer source commit is invalid")
    truth = payload.get("truth_contract")
    if not isinstance(truth, Mapping):
        raise ValueError("canonical ICARUS acceptance truth contract is missing")
    for key in (
        "foreign_peer_state_is_evidence_not_native_truth",
        "durability_only_is_not_substantive_research_evidence",
        "acceptance_is_not_execution_authority",
        "acceptance_is_not_production_decision_authority",
        "same_packet_is_idempotent",
    ):
        if truth.get(key) is not True:
            raise ValueError(f"canonical ICARUS acceptance truth invariant failed: {key}")

    return {
        "status": "VERIFIED_PRIOR_PACKET",
        "schema_version": CANONICAL_ACCEPTANCE_SCHEMA,
        "accepted_by_repository": "reppiks490/Icarus",
        "producer_repository": "reppiks490/Icarus-engine",
        "accepted_by_icarus_commit": str(payload["accepted_by_icarus_commit"]).lower(),
        "accepted_peer_packet_id": str(payload["peer_packet_id"]).lower(),
        "accepted_peer_packet_blob_sha": str(payload["peer_packet_blob_sha"]).lower(),
        "accepted_peer_source_commit": str(payload["peer_source_commit"]).lower(),
        "peer_source_commit_relation": payload.get("peer_source_commit_relation"),
        "peer_source_contract_witness_count": payload.get("peer_source_contract_witness_count"),
        "peer_lane_count": payload.get("peer_lane_count"),
        "peer_lane_witness_verified_count": payload.get("peer_lane_witness_verified_count"),
        "peer_lane_contract_binding_verified_count": payload.get(
            "peer_lane_contract_binding_verified_count"
        ),
        "authority": "RESEARCH",
        "required_for_export": False,
        "execution_authorized": False,
        "production_decision_authorized": False,
        "automatic_model_promotion": False,
    }


def _rehash_packet(packet: dict[str, Any]) -> None:
    unsigned = dict(packet)
    unsigned.pop("packet_id", None)
    packet["packet_id"] = hashlib.sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def export_packet(
    root: Path,
    *,
    source_commit: str | None = None,
    observed_at: str | None = None,
    output: Path = DEFAULT_OUTPUT,
    canonical_acceptance: Path | None = None,
) -> tuple[Path, dict]:
    root = root.resolve()
    commit = source_commit or _git_head(root)
    observed = observed_at or _utc_now()
    packet = build_peer_packet(
        root,
        source_commit=commit,
        observed_at=observed,
        source_repository="reppiks490/Icarus-engine",
    )
    acceptance_path = None
    if canonical_acceptance is not None:
        acceptance_path = (
            canonical_acceptance
            if canonical_acceptance.is_absolute()
            else root / canonical_acceptance
        )
    packet["canonical_acceptance"] = _normalize_canonical_acceptance(acceptance_path)
    _rehash_packet(packet)

    target = root / output
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(packet, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        prefix=".peer-packet-",
        delete=False,
    ) as handle:
        temp = Path(handle.name)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, target)
    return target, packet


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the revision-bound research-only ICARUS peer intelligence packet."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--source-commit")
    parser.add_argument("--observed-at")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--canonical-acceptance",
        help="Optional canonical Icarus federation acceptance JSON to embed as prior-packet acknowledgement.",
    )
    parser.add_argument(
        "--require-head-match",
        action="store_true",
        help="Require packet source_commit to equal the repository HEAD used for export.",
    )
    args = parser.parse_args()

    root = Path(args.root)
    path, packet = export_packet(
        root,
        source_commit=args.source_commit,
        observed_at=args.observed_at,
        output=Path(args.output),
        canonical_acceptance=(
            Path(args.canonical_acceptance) if args.canonical_acceptance else None
        ),
    )
    if args.require_head_match:
        head = _git_head(root.resolve())
        verify_packet_source_inputs(packet, root=root, expected_head=head)
    print(
        json.dumps(
            {
                "path": str(path),
                "packet_id": packet["packet_id"],
                "source_commit": packet["source_commit"],
                "canonical_acceptance_status": packet["canonical_acceptance"]["status"],
                "execution_authorized": packet["execution_authorized"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
