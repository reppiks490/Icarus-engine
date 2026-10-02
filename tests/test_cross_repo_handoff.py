from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cross_repo_handoff_is_revision_pinned_and_non_executing():
    handoff = json.loads((ROOT / "integration" / "ICARUS_MAIN_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["producer_repository"] == "reppiks490/Icarus-engine"
    assert handoff["target_repository"] == "reppiks490/Icarus"
    assert len(handoff["producer_revision"]) == 40
    assert len(handoff["target_revision"]) == 40
    assert handoff["authority_requested"] == "RESEARCH"
    assert handoff["authority_granted"] == "RESEARCH"
    assert all("execution" not in claim.lower() or "no " in claim.lower() for claim in handoff["claims"])


def test_readme_has_no_unresolved_merge_markers():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert "\n=======\n" not in text
    assert ">>>>>>>" not in text
    assert "reppiks490/Icarus" in text

def test_canonical_brain_consumer_contract_is_fail_closed_and_research_only():
    contract = json.loads(
        (ROOT / "automation_intelligence" / "mcp_interface" / "icarus_consumer_contract.json")
        .read_text(encoding="utf-8")
    )
    assert contract["schema_version"] == "icarus-engine-brain-federation-v1"
    assert contract["producer_repository"] == "reppiks490/Icarus-engine"
    assert contract["producer_ref"] == "main"
    assert contract["consumer_repository"] == "reppiks490/Icarus"
    assert contract["event_root"] == "automation_intelligence/mcp_interface/events"
    assert contract["event_schema"] == "icarus-mcp-event-v1"
    assert contract["producer_contract"] == "automation_intelligence/mcp_interface/contract.json"
    assert contract["producer_contract_schema"] == "icarus-mcp-interface-contract-v1"
    assert contract["execution_authorized"] is False
    assert contract["production_decision_authorized"] is False
    semantics = contract["semantics"]
    assert semantics["event_records"] == "RESEARCH_OBSERVABILITY_ONLY"
    assert semantics["durability_receipts_are_substantive_evidence"] is False
    assert semantics["remote_status_is_production_decision"] is False
    assert semantics["raw_owner_data_transfer"] is False
    assert semantics["automatic_model_promotion"] is False
    assert semantics["production_decision_authorized"] is False
    assert semantics["automatic_execution_authority"] is False

def test_brain_federation_strictly_enforces_event_contract_with_exact_legacy_exceptions():
    contract = json.loads(
        (ROOT / "automation_intelligence" / "mcp_interface" / "icarus_consumer_contract.json")
        .read_text(encoding="utf-8")
    )
    validation = contract["event_validation"]
    assert validation["required_fields_source"] == (
        "automation_intelligence/mcp_interface/contract.json#required_fields"
    )
    assert validation["strict_v1_required_fields"] is True
    legacy = validation["legacy_relaxed_blob_shas"]
    assert len(legacy) == 4
    assert len(set(legacy)) == len(legacy)
    assert all(len(value) == 40 for value in legacy)
    assert all(all(ch in "0123456789abcdef" for ch in value) for value in legacy)
    assert "No future blob inherits this exception" in validation["legacy_rule"]
