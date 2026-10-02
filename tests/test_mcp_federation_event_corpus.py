from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVENT_ROOT = ROOT / "automation_intelligence" / "mcp_interface" / "events"


def _git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def test_federated_agent_event_corpus_matches_declared_contract():
    producer = json.loads(
        (ROOT / "automation_intelligence" / "mcp_interface" / "contract.json")
        .read_text(encoding="utf-8")
    )
    consumer = json.loads(
        (ROOT / "automation_intelligence" / "mcp_interface" / "icarus_consumer_contract.json")
        .read_text(encoding="utf-8")
    )

    accepted_sources = set(consumer["accepted_sources"])
    accepted_categories = set(consumer["accepted_categories"])
    required_fields = set(producer["required_fields"])
    legacy = set(consumer["event_validation"]["legacy_relaxed_blob_shas"])
    seen_legacy: set[str] = set()

    for path in sorted(EVENT_ROOT.glob("*.json")):
        raw = path.read_bytes()
        blob_sha = _git_blob_sha(raw)
        event = json.loads(raw)
        source = str(event.get("source") or "").strip().upper()
        if source not in accepted_sources:
            continue

        schema = event.get("schema_version", event.get("schema"))
        assert schema == consumer["event_schema"], path.name
        assert event.get("execution_authorized") is False, path.name
        assert str(event.get("category") or "").strip().upper() in accepted_categories, path.name

        missing = sorted(required_fields.difference(event))
        if missing:
            assert blob_sha in legacy, (
                f"{path.name} omits required producer fields {missing} without an exact "
                "legacy Git-blob exception"
            )
            seen_legacy.add(blob_sha)

    assert seen_legacy == legacy, (
        "legacy federation blob exceptions must correspond exactly to currently "
        "present nonconforming accepted-source events"
    )
