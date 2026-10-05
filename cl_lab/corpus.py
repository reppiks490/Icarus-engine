"""Validation-only intake for local Databento corpus exports.

Raw licensed rows are never committed by CL. This module only verifies the
canonical ICARUS corpus manifest/files on the operator machine and returns a
compact provenance inventory for research/UI evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

SCHEMA = "icarus-databento-corpus-v1"
ENV = "ICARUS_DATABENTO_CORPUS"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()



def identity(snapshot: dict) -> dict:
    """Return stable corpus identity for run fingerprinting.

    Retrieval timestamps and diagnostic error text are intentionally excluded:
    re-reading the same verified bytes must not manufacture a new logical CL run.
    Content hash, coverage, representation and verification state remain binding.
    """
    if not isinstance(snapshot, dict):
        return {}
    stable = {
        key: snapshot.get(key)
        for key in (
            "status",
            "schema_version",
            "provider",
            "dataset",
            "roll_rule",
            "minutes",
            "timestamp_semantics",
            "start",
            "end_exclusive",
            "verified_assets",
            "blocked_assets",
        )
        if key in snapshot
    }
    assets = {}
    raw_assets = snapshot.get("assets")
    if isinstance(raw_assets, dict):
        for token, row in sorted(raw_assets.items()):
            if not isinstance(row, dict):
                continue
            assets[str(token)] = {
                key: row.get(key)
                for key in (
                    "status",
                    "source_status",
                    "rows",
                    "first",
                    "last",
                    "sha256",
                    "databento_symbol",
                    "provider_ticker",
                    "tv_symbol",
                )
                if key in row
            }
    stable["assets"] = assets
    return stable


def inspect(path: str | os.PathLike | None = None) -> dict:
    root_text = str(path or os.environ.get(ENV) or "").strip()
    if not root_text:
        return {
            "status": "UNAVAILABLE",
            "reason": f"{ENV} is not configured",
            "schema_version": SCHEMA,
            "assets": {},
        }
    root = Path(root_text).expanduser()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return {
            "status": "UNAVAILABLE",
            "reason": f"missing {manifest_path}",
            "schema_version": SCHEMA,
            "assets": {},
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as ex:
        return {
            "status": "BLOCKED",
            "reason": f"manifest parse failed: {type(ex).__name__}: {ex}"[:500],
            "schema_version": SCHEMA,
            "assets": {},
        }
    if manifest.get("schema_version") != SCHEMA:
        return {
            "status": "BLOCKED",
            "reason": f"unexpected corpus schema {manifest.get('schema_version')!r}",
            "schema_version": SCHEMA,
            "assets": {},
        }

    compact = {}
    for token, row in sorted((manifest.get("assets") or {}).items()):
        item = {
            "source_status": row.get("status"),
            "rows": row.get("rows"),
            "first": row.get("first"),
            "last": row.get("last"),
            "sha256": row.get("sha256"),
            "databento_symbol": row.get("databento_symbol"),
            "provider_ticker": row.get("provider_ticker"),
            "tv_symbol": row.get("tv_symbol"),
        }
        if row.get("status") != "OK":
            item.update(status="SOURCE_BLOCKED", error=row.get("error"))
            compact[token] = item
            continue
        name = str(row.get("file") or "")
        if not name or Path(name).name != name:
            item.update(status="BLOCKED", error="unsafe or missing corpus filename")
            compact[token] = item
            continue
        file_path = root / name
        if not file_path.is_file():
            item.update(status="BLOCKED", error=f"missing {name}")
            compact[token] = item
            continue
        digest = _sha256(file_path)
        if digest != row.get("sha256"):
            item.update(status="BLOCKED", error="sha256 mismatch")
            compact[token] = item
            continue
        try:
            with file_path.open("r", encoding="utf-8") as fh:
                header = fh.readline().strip()
                count = sum(1 for line in fh if line.strip())
        except Exception as ex:
            item.update(status="BLOCKED", error=f"read failed: {type(ex).__name__}: {ex}"[:500])
            compact[token] = item
            continue
        if header != "ts,open,high,low,close,volume":
            item.update(status="BLOCKED", error="unexpected CSV schema")
        elif count != int(row.get("rows") or -1):
            item.update(status="BLOCKED", error=f"row count mismatch manifest={row.get('rows')} file={count}")
        else:
            item.update(status="VERIFIED", file=name)
        compact[token] = item

    verified = sum(1 for row in compact.values() if row.get("status") == "VERIFIED")
    blocked = sum(1 for row in compact.values() if row.get("status") in {"BLOCKED", "SOURCE_BLOCKED"})
    status = "VERIFIED" if compact and blocked == 0 else "PARTIAL" if verified else "BLOCKED"
    return {
        "status": status,
        "schema_version": SCHEMA,
        "provider": manifest.get("provider"),
        "dataset": manifest.get("dataset"),
        "roll_rule": manifest.get("roll_rule"),
        "minutes": manifest.get("minutes"),
        "timestamp_semantics": manifest.get("timestamp_semantics"),
        "start": manifest.get("start"),
        "end_exclusive": manifest.get("end_exclusive"),
        "generated_at": manifest.get("generated_at"),
        "verified_assets": verified,
        "blocked_assets": blocked,
        "assets": compact,
        "execution_authorized": False,
        "production_decision_authorized": False,
    }
