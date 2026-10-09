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


def test_brain_federation_declares_historical_research_context_sources():
    contract = json.loads(
        (ROOT / "automation_intelligence" / "mcp_interface" / "icarus_consumer_contract.json")
        .read_text(encoding="utf-8")
    )
    historical = contract["historical_context"]
    assert historical["mode"] == "RESEARCH_CONTEXT_ONLY"
    assert historical["direct_candidate_evidence"] is False
    assert historical["automatic_candidate_creation"] is False
    assert historical["automatic_model_promotion"] is False
    assert historical["execution_authorized"] is False
    assert historical["production_decision_authorized"] is False

    sources = historical["sources"]
    assert {row["id"] for row in sources} == {
        "robustness_guardian",
        "alpha_synthesis",
        "apex_council",
        "flow_microstructure",
        "provider_collection",
    }
    assert len({row["path"] for row in sources}) == len(sources)
    assert all((ROOT / row["path"]).is_file() for row in sources)
    assert all(row["candidate_evidence_eligible"] is False for row in sources)
    assert all(row["research_context_eligible"] is True for row in sources)
    assert all(row["execution_authorized"] is False for row in sources)
    assert {
        row["evidence_status"] for row in sources
    } == {
        "HISTORICAL_RESEARCH_EVIDENCE",
        "HISTORICAL_COLLECTION_EVIDENCE",
    }
    collection_only = {row["id"] for row in sources if row["collection_only"] is True}
    assert collection_only == {"flow_microstructure", "provider_collection"}
    provider = next(row for row in sources if row["id"] == "provider_collection")
    assert provider["path"] == "automation_intelligence/provider_collection_v1/research_context.json"
    assert "providers" in provider["summary_fields"]
    assert "summary" in provider["summary_fields"]
    assert provider["raw_payloads_eligible"] is False
    for row in sources:
        if row["id"] not in collection_only:
            assert row["evidence_status"] == "HISTORICAL_RESEARCH_EVIDENCE"


def test_historical_context_contract_cannot_bypass_foundry_or_evaluator():
    contract = json.loads(
        (ROOT / "automation_intelligence" / "mcp_interface" / "icarus_consumer_contract.json")
        .read_text(encoding="utf-8")
    )
    historical = contract["historical_context"]
    truth = historical["truth_contract"]
    assert truth["foreign_repository_state_is_context_not_native_truth"] is True
    assert truth["historical_context_never_bypasses_foundry"] is True
    assert truth["historical_context_never_bypasses_evaluator"] is True
    assert truth["historical_context_never_grants_shadow_qualification"] is True
    assert truth["historical_context_never_grants_execution_authority"] is True


def test_brain_federation_peer_packet_has_bounded_freshness():
    contract = json.loads(
        (ROOT / "automation_intelligence" / "mcp_interface" / "icarus_consumer_contract.json")
        .read_text(encoding="utf-8")
    )
    peer = contract["peer_packet"]
    assert peer["freshness_required"] is True
    assert peer["max_age_seconds"] == 1800
    assert peer["max_future_skew_seconds"] == 300
    assert peer["max_age_seconds"] > peer["max_future_skew_seconds"] > 0
    assert peer["semantics"]["stale_packet_is_current_state"] is False
    assert peer["required_for_event_ingest"] is False
    assert peer["authority"] == "OBSERVE"
