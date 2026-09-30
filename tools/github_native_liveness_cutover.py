from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from tools.automation_durability_watchdog import (
    iter_v3_expected_slots,
    load_v3_watchdog_config,
    scan_v3_receipts,
)

NS = "automation_intelligence/omega_stack_native_v3"
CONTROL_PATH = Path(NS) / "control_plane.json"
ACCEPTANCE_PATH = Path(NS) / "cutover" / "acceptance.json"
LANES = ("omega", "macro", "flow", "aion", "daedalus")


def _utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"required cutover file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed cutover JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"cutover JSON must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def evaluate_cutover(
    root: Path,
    now_utc: datetime,
    *,
    required_consecutive: int = 2,
) -> dict[str, object]:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    if required_consecutive < 1:
        raise ValueError("required_consecutive must be positive")

    config = load_v3_watchdog_config(root)
    if config.inference_backend != "deterministic_liveness":
        return {
            "ready": False,
            "reason": "BACKEND_NOT_DETERMINISTIC_LIVENESS",
            "required_consecutive": required_consecutive,
            "consecutive_valid_by_lane": {lane: 0 for lane in LANES},
            "evidence_receipts": {lane: [] for lane in LANES},
        }

    slots = iter_v3_expected_slots(config, now_utc, horizon_hours=48)
    by_lane: dict[str, list] = {lane: [] for lane in LANES}
    for slot in slots:
        by_lane[slot.lane.name].append(slot)

    counts: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    for lane in LANES:
        count = 0
        refs: list[str] = []
        for slot in sorted(by_lane[lane], key=lambda item: item.scheduled_utc, reverse=True):
            match, _ = scan_v3_receipts(root, slot, config)
            if match is None:
                break
            count += 1
            refs.append(match.path)
            if count >= required_consecutive:
                break
        counts[lane] = count
        evidence[lane] = refs

    ready = all(counts[lane] >= required_consecutive for lane in LANES)
    return {
        "ready": ready,
        "reason": "READY" if ready else "INSUFFICIENT_CONSECUTIVE_RECEIPTS",
        "required_consecutive": required_consecutive,
        "consecutive_valid_by_lane": counts,
        "evidence_receipts": evidence,
    }


def promote_if_ready(
    root: Path,
    now_utc: datetime,
    *,
    required_consecutive: int = 2,
) -> dict[str, object]:
    control_path = root / CONTROL_PATH
    acceptance_path = root / ACCEPTANCE_PATH
    control = _load_json(control_path)

    if control.get("execution_authorized") is not False:
        raise ValueError("execution_authorized must remain false")
    if control.get("mode") == "AUTHORITATIVE":
        return {
            "promoted": False,
            "reason": "ALREADY_AUTHORITATIVE",
            "mode": "AUTHORITATIVE",
        }
    if control.get("inference_backend") != "deterministic_liveness":
        return {
            "promoted": False,
            "reason": "BACKEND_NOT_DETERMINISTIC_LIVENESS",
            "mode": control.get("mode"),
        }

    evaluation = evaluate_cutover(
        root,
        now_utc,
        required_consecutive=required_consecutive,
    )
    if not evaluation["ready"]:
        return {
            "promoted": False,
            "reason": evaluation["reason"],
            "mode": control.get("mode"),
            **evaluation,
        }

    promoted_at = _utc_z(now_utc)
    control["mode"] = "AUTHORITATIVE"
    control["authoritative_scope"] = "LIVENESS_PERSISTENCE_ONLY"
    control["substantive_ai_inference"] = False
    control["promoted_at_utc"] = promoted_at
    control["promotion_requirement"] = (
        f"{required_consecutive}_CONSECUTIVE_VALID_GITHUB_NATIVE_LIVENESS_RECEIPTS_PER_LANE"
    )
    control["promotion_evidence_receipts"] = evaluation["evidence_receipts"]
    control["execution_authorized"] = False

    acceptance = _load_json(acceptance_path)
    acceptance["phase"] = "ZERO_COST_AUTHORITATIVE_LIVENESS"
    acceptance["authoritative_execution_source"] = "GITHUB_NATIVE_LIVENESS"
    acceptance["authoritative_scope"] = "LIVENESS_PERSISTENCE_ONLY"
    acceptance["inference_backend"] = "deterministic_liveness"
    acceptance["zero_cost"] = True
    acceptance["execution_authorized"] = False
    acceptance["promoted_at_utc"] = promoted_at
    acceptance["promotion_requirement"] = control["promotion_requirement"]
    acceptance["promotion_evidence_receipts"] = evaluation["evidence_receipts"]
    acceptance["consecutive_valid_by_lane"] = evaluation["consecutive_valid_by_lane"]
    acceptance["next_cutover_step"] = (
        "NONE_FOR_LIVENESS_PERSISTENCE; SUBSTANTIVE_AI_REQUIRES_A_SEPARATE_EXPLICIT_BACKEND"
    )

    _write_json(control_path, control)
    _write_json(acceptance_path, acceptance)
    return {
        "promoted": True,
        "reason": "PROMOTED",
        "mode": "AUTHORITATIVE",
        **evaluation,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Promote zero-cost v3 liveness after consecutive receipt proof."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--now-utc")
    parser.add_argument("--required-consecutive", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        if args.now_utc:
            now = datetime.fromisoformat(args.now_utc.replace("Z", "+00:00"))
            if now.tzinfo is None:
                raise ValueError("now_utc must be timezone-aware")
            now = now.astimezone(timezone.utc)
        else:
            now = datetime.now(timezone.utc)
        result = promote_if_ready(
            args.root,
            now,
            required_consecutive=args.required_consecutive,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
