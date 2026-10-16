"""Read-only repository provenance bridge for the ICARUS MCP / Automation panel.

This module deliberately performs no network I/O and no repository mutation. It
projects durable automation/MCP evidence already present in the ICARUS checkout
into a compact JSON document for the local dashboard. The central many-chat
coordination bus is mirrored into repository evidence by GitHub Actions and is
therefore consumed through the same local-only boundary.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class MCPControlPlane:
    """Build a truthful, read-only snapshot of automation and MCP evidence."""

    V3_ROOT = Path("automation_intelligence/omega_stack_native_v3")
    RESTORED_ROOT = Path("automation_intelligence/restored_five_native")
    MCP_ROOT = Path("automation_intelligence/mcp_interface")
    COORD_ROOT = Path("automation_intelligence/coordination")

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir).resolve()

    def _path(self, relative: str | Path) -> Path:
        candidate = (self.base_dir / relative).resolve()
        try:
            candidate.relative_to(self.base_dir)
        except ValueError as exc:
            raise ValueError("path escapes ICARUS base directory") from exc
        return candidate

    @staticmethod
    def _load_json(path: Path) -> Optional[Dict[str, Any]]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _json_files(root: Path) -> Iterable[Path]:
        if not root.is_dir():
            return ()
        return (p for p in root.rglob("*.json") if p.is_file())

    def _latest_json(self, root: Path) -> tuple[Optional[Path], Optional[Dict[str, Any]]]:
        files = list(self._json_files(root))
        if not files:
            return None, None
        files.sort(key=lambda p: (p.parent.name, p.name))
        for path in reversed(files):
            value = self._load_json(path)
            if value is not None:
                return path, value
        return None, None

    def _rel(self, path: Optional[Path]) -> Optional[str]:
        if path is None:
            return None
        try:
            return path.resolve().relative_to(self.base_dir).as_posix()
        except ValueError:
            return None

    @staticmethod
    def _v3_health(receipt: Optional[Dict[str, Any]]) -> str:
        if not receipt:
            return "MISSING"
        run = str(receipt.get("RUN_STATUS", "")).upper()
        final = str(receipt.get("FINALIZATION_STATUS", "")).upper()
        validation = str(receipt.get("output_validation_status", "") or "").upper()
        if run in {"RUN_PERSISTED", "PERSISTED"} and final in {"VERIFIED", "LIVENESS_VERIFIED"} and validation in {"", "VALID"}:
            return "VERIFIED"
        if run in {"RUN_PERSISTED", "PERSISTED"}:
            return "DEGRADED"
        return "FAILED"

    @staticmethod
    def _restored_health(receipt: Optional[Dict[str, Any]]) -> str:
        if not receipt:
            return "MISSING"
        slot = str(receipt.get("slot_status", "")).upper()
        worker = str(receipt.get("worker_receipt_status", "")).upper()
        if slot == "WORKER_RECEIPT_VERIFIED" and worker == "CHATGPT_CANONICAL_RECEIPT_PRESENT":
            return "VERIFIED"
        if slot == "FALLBACK_LIVENESS_ONLY":
            return "LIVENESS_ONLY"
        return "DEGRADED"

    @staticmethod
    def _coord_session(value: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(value, dict):
            return None
        sid = value.get("session_id")
        if not isinstance(sid, str) or not sid:
            return None
        targets = []
        for target in value.get("reserved_targets", []) if isinstance(value.get("reserved_targets"), list) else []:
            if isinstance(target, dict) and isinstance(target.get("repo"), str) and isinstance(target.get("path"), str):
                targets.append({"repo": target["repo"][:200], "path": target["path"][:1000]})
            if len(targets) >= 128:
                break
        return {
            "session_id": sid[:160],
            "actor": str(value.get("actor") or "")[:160],
            "model_family": str(value.get("model_family") or "")[:80],
            "goal": str(value.get("goal") or "")[:2000],
            "home_repo": str(value.get("home_repo") or "")[:240],
            "branch": str(value.get("branch") or "")[:300],
            "pr": value.get("pr") if isinstance(value.get("pr"), (str, int)) or value.get("pr") is None else None,
            "status": str(value.get("status") or "")[:80],
            "phase": str(value.get("phase") or "")[:120],
            "latest_type": str(value.get("latest_type") or "")[:80],
            "latest_summary": str(value.get("latest_summary") or "")[:3000],
            "last_event_at_utc": str(value.get("last_event_at_utc") or "")[:120],
            "dependencies": [str(x)[:500] for x in (value.get("dependencies") or [])[:128]] if isinstance(value.get("dependencies"), list) else [],
            "reserved_targets": targets,
            "stale": bool(value.get("stale", False)),
            "reclaimable": bool(value.get("reclaimable", False)),
        }

    @staticmethod
    def _coord_collision(value: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(value, dict):
            return None
        sessions = value.get("sessions")
        repo = value.get("repo")
        pairs = value.get("target_pairs", value.get("path_pairs", []))
        if not isinstance(sessions, list) or not isinstance(repo, str) or not isinstance(pairs, list):
            return None
        clean_pairs = []
        for pair in pairs[:128]:
            if isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) for x in pair):
                clean_pairs.append([pair[0][:1000], pair[1][:1000]])
        return {
            "sessions": [str(x)[:160] for x in sessions[:16]],
            "repo": repo[:240],
            "target_pairs": clean_pairs,
            "severity": str(value.get("severity") or "collision")[:80],
        }

    def _coordination(self) -> Dict[str, Any]:
        path = self._path(self.COORD_ROOT / "index.json")
        base = {
            "present": False,
            "schema_version": None,
            "generated_at_utc": None,
            "mirrored_at_utc": None,
            "source_repository": "reppiks490/icarus-owner-actions",
            "source_path": self._rel(path),
            "execution_authorized": False,
            "trading_execution_authorized": False,
            "owner_status": {},
            "counts": {"active": 0, "terminal": 0, "stale": 0, "collisions": 0},
            "active_sessions": [],
            "collisions": [],
            "error": None,
        }
        if not path.is_file():
            return base
        value = self._load_json(path)
        if not value or value.get("schema_version") != "icarus-coordination-index-v2":
            return {**base, "error": "INVALID_COORDINATION_SNAPSHOT"}
        if not isinstance(value.get("active_sessions"), list) or not isinstance(value.get("collisions"), list):
            return {**base, "error": "INVALID_COORDINATION_SNAPSHOT"}
        if not isinstance(value.get("counts"), dict) or not isinstance(value.get("owner_status"), dict):
            return {**base, "error": "INVALID_COORDINATION_SNAPSHOT"}

        sessions = []
        for raw in value["active_sessions"][:256]:
            clean = self._coord_session(raw)
            if clean is not None:
                sessions.append(clean)
        collisions = []
        for raw in value["collisions"][:256]:
            clean = self._coord_collision(raw)
            if clean is not None:
                collisions.append(clean)

        counts = value["counts"]
        safe_counts = {}
        for key in ("active", "terminal", "stale", "collisions"):
            raw = counts.get(key, 0)
            safe_counts[key] = max(0, min(int(raw), 1_000_000)) if isinstance(raw, int) and not isinstance(raw, bool) else 0
        try:
            mirrored = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except OSError:
            mirrored = None
        owner = value["owner_status"]
        claude = owner.get("claude") if isinstance(owner.get("claude"), dict) else {}
        safe_owner = {
            "claude": {
                "active": bool(claude.get("active", False)),
                "return_date": claude.get("return_date") if isinstance(claude.get("return_date"), str) or claude.get("return_date") is None else None,
                "note": str(claude.get("note") or "")[:2000],
            },
            "live_broker_arming": bool(owner.get("live_broker_arming", False)),
        }
        return {
            **base,
            "present": True,
            "schema_version": value["schema_version"],
            "generated_at_utc": value.get("generated_at_utc"),
            "mirrored_at_utc": mirrored,
            "owner_status": safe_owner,
            "counts": safe_counts,
            "active_sessions": sessions,
            "collisions": collisions,
        }

    def _v3(self) -> Dict[str, Any]:
        root = self._path(self.V3_ROOT)
        control = self._load_json(root / "control_plane.json") or {}
        acceptance = self._load_json(root / "cutover" / "acceptance.json") or {}
        lanes: List[Dict[str, Any]] = []
        for cfg in control.get("lanes", []) if isinstance(control.get("lanes"), list) else []:
            if not isinstance(cfg, dict):
                continue
            name = str(cfg.get("name", "")).strip()
            if not name:
                continue
            run_path, receipt = self._latest_json(root / "lanes" / name / "runs")
            receipt = receipt or {}
            failure_path, failure = self._latest_json(root / "lanes" / name / "failures")
            failure = failure or {}
            lanes.append({
                "name": name,
                "title": cfg.get("title"),
                "minute": cfg.get("minute"),
                "health": self._v3_health(receipt),
                "latest_slot_utc": receipt.get("slot_utc") or receipt.get("SLOT_ID"),
                "latest_slot_local": receipt.get("slot_local"),
                "run_id": receipt.get("RUN_ID"),
                "run_status": receipt.get("RUN_STATUS"),
                "finalization_status": receipt.get("FINALIZATION_STATUS"),
                "validation_status": receipt.get("output_validation_status"),
                "run_origin": receipt.get("run_origin"),
                "inference_backend": receipt.get("inference_backend"),
                "model": receipt.get("model"),
                "started_at_utc": receipt.get("started_at_utc"),
                "completed_at_utc": receipt.get("completed_at_utc"),
                "workflow_run_id": receipt.get("workflow_run_id"),
                "data_gaps": receipt.get("DATA_GAPS") if isinstance(receipt.get("DATA_GAPS"), list) else [],
                "conflicts": receipt.get("CONFLICTS") if isinstance(receipt.get("CONFLICTS"), list) else [],
                "receipt_path": self._rel(run_path),
                "latest_failure_path": self._rel(failure_path),
                "latest_failure_slot_utc": failure.get("slot_utc") or failure.get("SLOT_ID"),
                "latest_failure_status": failure.get("RUN_STATUS") or failure.get("status"),
            })

        counts: Dict[str, int] = {}
        for lane in lanes:
            counts[lane["health"]] = counts.get(lane["health"], 0) + 1
        return {
            "present": root.is_dir(),
            "control_plane_id": control.get("control_plane_id"),
            "mode": control.get("mode"),
            "authoritative_scope": control.get("authoritative_scope"),
            "inference_backend": control.get("inference_backend"),
            "substantive_ai_inference": control.get("substantive_ai_inference"),
            "credential_status": control.get("credential_status"),
            "promoted_at_utc": control.get("promoted_at_utc"),
            "execution_authorized": bool(control.get("execution_authorized", False)),
            "phase": acceptance.get("phase"),
            "zero_cost": acceptance.get("zero_cost"),
            "verified_branch_ci": acceptance.get("verified_branch_ci"),
            "persistence_hardening": acceptance.get("persistence_hardening"),
            "last_persistence_race_hardening": acceptance.get("last_persistence_race_hardening"),
            "watchdog_revalidation_requested_at_utc": acceptance.get("watchdog_revalidation_requested_at_utc"),
            "health_counts": counts,
            "lanes": lanes,
            "control_path": self._rel(root / "control_plane.json"),
            "acceptance_path": self._rel(root / "cutover" / "acceptance.json"),
        }

    def _restored_five(self) -> Dict[str, Any]:
        root = self._path(self.RESTORED_ROOT)
        control = self._load_json(root / "control_plane.json") or {}
        lanes: List[Dict[str, Any]] = []
        for cfg in control.get("lanes", []) if isinstance(control.get("lanes"), list) else []:
            if not isinstance(cfg, dict):
                continue
            name = str(cfg.get("name", "")).strip()
            if not name:
                continue
            path, receipt = self._latest_json(root / "receipts" / name)
            receipt = receipt or {}
            lanes.append({
                "name": name,
                "title": cfg.get("title"),
                "minute": cfg.get("minute"),
                "scheduler_id": cfg.get("scheduler_id"),
                "health": self._restored_health(receipt),
                "slot_utc": receipt.get("slot_utc"),
                "slot_status": receipt.get("slot_status"),
                "worker_receipt_status": receipt.get("worker_receipt_status"),
                "observed_worker_run_id": receipt.get("observed_worker_RUN_ID"),
                "observed_worker_run_status": receipt.get("observed_worker_RUN_STATUS"),
                "origin": receipt.get("origin"),
                "substantive_work_claimed": receipt.get("substantive_work_claimed"),
                "receipt_path": self._rel(path),
            })
        counts: Dict[str, int] = {}
        for lane in lanes:
            counts[lane["health"]] = counts.get(lane["health"], 0) + 1
        return {
            "present": root.is_dir(),
            "control_plane_id": control.get("control_plane_id"),
            "execution_authorized": bool(control.get("execution_authorized", False)),
            "health_counts": counts,
            "lanes": lanes,
            "control_path": self._rel(root / "control_plane.json"),
        }

    def _events(self, limit: int) -> List[Dict[str, Any]]:
        root = self._path(self.MCP_ROOT / "events")
        items: List[Dict[str, Any]] = []
        for path in self._json_files(root):
            event = self._load_json(path)
            if not event:
                continue
            items.append({
                "event_id": event.get("event_id"),
                "at_utc": event.get("at_utc"),
                "category": event.get("category"),
                "status": event.get("status"),
                "severity": event.get("severity"),
                "summary": event.get("summary"),
                "surface": event.get("surface"),
                "source": event.get("source"),
                "branch": event.get("branch"),
                "commit": event.get("commit"),
                "paths": event.get("paths") if isinstance(event.get("paths"), list) else [],
                "evidence": event.get("evidence") if isinstance(event.get("evidence"), list) else [],
                "execution_authorized": bool(event.get("execution_authorized", False)),
                "event_path": self._rel(path),
            })
        items.sort(key=lambda e: (str(e.get("at_utc") or ""), str(e.get("event_id") or "")), reverse=True)
        return items[: max(1, min(int(limit), 500))]

    def status(self, event_limit: int = 100) -> Dict[str, Any]:
        contract_path = self._path(self.MCP_ROOT / "contract.json")
        contract = self._load_json(contract_path) or {}
        v3 = self._v3()
        restored = self._restored_five()
        coordination = self._coordination()
        events = self._events(event_limit)
        material = sum(1 for e in events if str(e.get("category", "")).upper() in {"REPAIR", "AUDIT", "EVOLUTION", "INTEGRATION"})
        waiting = sum(1 for s in coordination.get("active_sessions", []) if str(s.get("phase", "")).lower() == "waiting" or str(s.get("latest_type", "")).upper() == "WAITING")
        return {
            "schema_version": "icarus-mcp-interface-v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "LOCAL_REPOSITORY_SNAPSHOT",
            "source_note": "Remote GitHub changes appear after this ICARUS checkout is synchronized or the coordination mirror commits a newer snapshot.",
            "execution_authorized": False,
            "trading_execution_authorized": False,
            "contract": {
                "present": bool(contract),
                "schema_version": contract.get("schema_version"),
                "purpose": contract.get("purpose"),
                "event_root": contract.get("event_root"),
                "required_categories": contract.get("required_categories"),
                "required_fields": contract.get("required_fields"),
                "ui_api": contract.get("ui_api"),
                "ui_tab": contract.get("ui_tab"),
                "path": self._rel(contract_path),
            },
            "summary": {
                "v3_lanes": len(v3.get("lanes", [])),
                "v3_verified": v3.get("health_counts", {}).get("VERIFIED", 0),
                "restored_lanes": len(restored.get("lanes", [])),
                "material_events_returned": material,
                "coordination_active": coordination.get("counts", {}).get("active", 0),
                "coordination_waiting": waiting,
                "coordination_stale": coordination.get("counts", {}).get("stale", 0),
                "coordination_collisions": coordination.get("counts", {}).get("collisions", 0),
            },
            "v3": v3,
            "restored_five": restored,
            "coordination": coordination,
            "events": events,
        }
