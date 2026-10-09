"""Aggregate provider collection receipts into a safe research-context artifact.

The artifact contains derived metrics, coverage state, and descriptive research
features only. Raw licensed provider payloads and credentials never enter it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path("automation_intelligence/provider_collection_v1")
LATEST = ROOT / "latest"
OUTPUT = ROOT / "research_context.json"


def _provider_row(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    entry = payload.get("providers", {}).get(provider)
    if not isinstance(entry, dict):
        # Owner-standby receipts intentionally do not use the normal providers
        # envelope. Preserve only the safe coordination fields.
        return {
            "status": str(payload.get("status", "UNKNOWN")),
            "run_id": payload.get("run_id"),
            "completed_at_utc": payload.get("completed_at_utc"),
            "preferred_repository": payload.get("preferred_repository"),
            "credential_present": bool(payload.get("credential_present", False)),
            "requests": 0,
            "collected_pages": 0,
            "collected_rows": 0,
            "substantive_work_performed": False,
            "research_features": [],
            "catalog": {},
        }

    catalog = payload.get("catalog") if isinstance(payload.get("catalog"), dict) else {}
    features = entry.get("research_features") if isinstance(entry.get("research_features"), list) else []
    return {
        "status": str(entry.get("status", "UNKNOWN")),
        "run_id": payload.get("run_id"),
        "completed_at_utc": payload.get("completed_at_utc"),
        "credential_present": bool(entry.get("credential_present", False)),
        "requests": int(entry.get("requests", 0) or 0),
        "collected_pages": int(entry.get("collected_pages", 0) or 0),
        "collected_rows": int(entry.get("collected_rows", 0) or 0),
        "substantive_work_performed": bool(entry.get("substantive_work_performed", False)),
        "research_features": features,
        "catalog": {
            key: catalog.get(key)
            for key in (
                "operations",
                "collected_operations",
                "asset_templates",
                "assets",
                "asset_datasets_collected",
                "pending_pages",
                "denied_operations",
                "unresolved_operations",
                "qualification",
            )
            if key in catalog
        },
    }


def build_context(repo_root: Path) -> dict[str, Any]:
    latest = repo_root / LATEST
    providers: dict[str, dict[str, Any]] = {}
    timestamps: list[str] = []

    if latest.is_dir():
        for path in sorted(latest.glob("*.json")):
            provider = path.stem
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                providers[provider] = {
                    "status": "INVALID_LATEST_RECEIPT",
                    "run_id": None,
                    "completed_at_utc": None,
                    "credential_present": False,
                    "requests": 0,
                    "collected_pages": 0,
                    "collected_rows": 0,
                    "substantive_work_performed": False,
                    "research_features": [],
                    "catalog": {},
                }
                continue
            row = _provider_row(provider, payload)
            providers[provider] = row
            if isinstance(row.get("completed_at_utc"), str):
                timestamps.append(row["completed_at_utc"])

    blocked = sum(
        1
        for row in providers.values()
        if row["status"].startswith("BLOCKED")
        or row["status"] in {"QUOTA_OR_RATE_LIMIT_PAUSED", "INVALID_LATEST_RECEIPT"}
    )
    substantive = sum(1 for row in providers.values() if row["substantive_work_performed"])
    return {
        "schema_version": "icarus-provider-research-context-v1",
        "authority": "RESEARCH_CONTEXT_ONLY",
        "snapshot_at_utc": max(timestamps) if timestamps else None,
        "source_root": str(LATEST),
        "raw_payloads_included": False,
        "execution_authorized": False,
        "production_decision_authorized": False,
        "automatic_model_promotion": False,
        "summary": {
            "providers_total": len(providers),
            "providers_substantive": substantive,
            "providers_blocked": blocked,
            "requests": sum(row["requests"] for row in providers.values()),
            "collected_pages": sum(row["collected_pages"] for row in providers.values()),
            "collected_rows": sum(row["collected_rows"] for row in providers.values()),
        },
        "providers": providers,
    }


def write_context(repo_root: Path) -> Path:
    output = repo_root / OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_context(repo_root), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    path = write_context(args.repo_root)
    print(path)


if __name__ == "__main__":
    main()
