from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tools.restored_five_local_shadow import run_shadow

ROOT = Path("automation_intelligence/restored_five_native")
RECEIPTS = ROOT / "receipts"
OUTPUTS = ROOT / "shadow_outputs"
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


def select_pending(root: Path) -> Pending | None:
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
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item.slot_id, LANES.index(item.lane)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process one pending restored-five shadow receipt.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    pending = select_pending(root)
    if pending is None:
        print(json.dumps({"status": "NO_PENDING_RECEIPT"}, sort_keys=True))
        return 0

    run_shadow(
        pending.lane,
        root / pending.receipt,
        root / pending.output,
        binary=args.binary,
        model=args.model,
    )
    print(json.dumps({
        "status": "SHADOW_PERSISTED_LOCALLY",
        "lane": pending.lane,
        "slot_id": pending.slot_id,
        "receipt": pending.receipt.as_posix(),
        "output": pending.output.as_posix(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
