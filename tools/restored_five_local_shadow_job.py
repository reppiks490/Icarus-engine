from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tools.restored_five_local_shadow import run_shadow

ROOT = Path("automation_intelligence/restored_five_native")
RECEIPTS = ROOT / "receipts"
OUTPUTS = ROOT / "shadow_outputs"
LATE_VERIFICATIONS = ROOT / "late_verifications"
RECONCILIATIONS = ROOT / "shadow_reconciliations"
LANES = (
    "robustness_guardian",
    "advanced_csv",
    "alpha_synthesis",
    "flow_microstructure",
    "apex_council",
)


@dataclass(frozen=True)
class Pending:
    lane: str
    slot_id: str
    receipt: Path
    output: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def reconcile_late_verifications(root: Path) -> list[Path]:
    created: list[Path] = []
    late_root = root / LATE_VERIFICATIONS
    if not late_root.is_dir():
        return created

    for lane in LANES:
        lane_dir = late_root / lane
        if not lane_dir.is_dir():
            continue
        for late_path in sorted(lane_dir.glob("*.json")):
            slot_id = late_path.stem
            receipt_path = root / RECEIPTS / lane / f"{slot_id}.json"
            shadow_path = root / OUTPUTS / lane / f"{slot_id}.json"
            reconciliation_path = root / RECONCILIATIONS / lane / f"{slot_id}.json"
            if reconciliation_path.exists():
                continue
            if not receipt_path.is_file() or not shadow_path.is_file():
                continue

            late = _load_object(late_path)
            receipt = _load_object(receipt_path)
            shadow = _load_object(shadow_path)

            if late.get("verification_status") != "LATE_WORKER_RECEIPT_VERIFIED":
                continue
            expected_run = receipt.get("expected_RUN_ID")
            observed_run = late.get("observed_worker_RUN_ID")
            if not isinstance(expected_run, str) or not expected_run:
                continue
            if not isinstance(observed_run, str) or not observed_run:
                continue

            payload: dict[str, object] = {
                "schema_version": "restored-five-shadow-reconciliation-v1",
                "lane": lane,
                "slot_id": slot_id,
                "expected_RUN_ID": expected_run,
                "observed_worker_RUN_ID": observed_run,
                "effective_run_id_match": observed_run == expected_run,
                "effective_worker_receipt_status": "LATE_WORKER_RECEIPT_VERIFIED",
                "original_receipt_path": str(receipt_path.relative_to(root)),
                "original_receipt_sha256": _sha256(receipt_path),
                "base_shadow_path": str(shadow_path.relative_to(root)),
                "base_shadow_sha256": _sha256(shadow_path),
                "late_verification_path": str(late_path.relative_to(root)),
                "late_verification_sha256": _sha256(late_path),
                "original_fallback_preserved": True,
                "canonical_state_mutated": False,
                "substantive_work_claimed": late.get("substantive_work_claimed") is True,
                "execution_authorized": False,
                "correction": (
                    "Base shadow output remains immutable historical evidence. "
                    "A later verified worker receipt supersedes the earlier unverified worker-status inference."
                ),
                "base_shadow_schema_version": shadow.get("schema_version"),
            }
            reconciliation_path.parent.mkdir(parents=True, exist_ok=True)
            with reconciliation_path.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, indent=2)
                handle.write("\n")
            created.append(reconciliation_path)
    return created


def select_pending_batch(root: Path, limit: int = 3) -> list[Pending]:
    if limit <= 0:
        return []
    candidates: list[Pending] = []
    receipt_root = root / RECEIPTS
    output_root = root / OUTPUTS
    for lane in LANES:
        lane_dir = receipt_root / lane
        if not lane_dir.is_dir():
            continue
        for receipt in sorted(lane_dir.glob("*.json")):
            slot_id = receipt.stem
            output = output_root / lane / f"{slot_id}.json"
            if output.exists():
                continue
            candidates.append(Pending(lane, slot_id, receipt, output))
    candidates.sort(key=lambda item: (item.slot_id, LANES.index(item.lane)))
    return candidates[:limit]


def select_pending(root: Path) -> Pending | None:
    batch = select_pending_batch(root, limit=1)
    return batch[0] if batch else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process one pending restored-five shadow receipt.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--max-items", type=int, default=3)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    reconciled = reconcile_late_verifications(root)
    pending_items = select_pending_batch(root, limit=args.max_items)
    if not pending_items:
        print(json.dumps({
            "status": "NO_PENDING_RECEIPT",
            "reconciliations_created": [str(path.relative_to(root)) for path in reconciled],
        }, sort_keys=True))
        return 0

    completed: list[dict[str, str]] = []
    for pending in pending_items:
        run_shadow(
            pending.lane,
            root / pending.receipt,
            root / pending.output,
            binary=args.binary,
            model=args.model,
        )
        completed.append({
            "lane": pending.lane,
            "slot_id": pending.slot_id,
            "receipt": pending.receipt.as_posix(),
            "output": pending.output.as_posix(),
        })
    print(json.dumps({
        "status": "SHADOW_BATCH_PERSISTED_LOCALLY",
        "completed": completed,
        "reconciliations_created": [str(path.relative_to(root)) for path in reconciled],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
