"""J01 fixtures (docs/FEDERATION_HISTORICAL_CONTEXT_V2.md) cannot drift and fail for their stated reason."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent / "fixtures" / "federation_v2"


def _builder():
    spec = importlib.util.spec_from_file_location("j01_build_fixtures", HERE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BF = _builder()
MANIFEST = json.loads((HERE / "MANIFEST.json").read_text())


def test_regenerating_reproduces_the_committed_fixtures_byte_for_byte(tmp_path):
    (tmp_path / "build_fixtures.py").write_bytes((HERE / "build_fixtures.py").read_bytes())
    fresh = BF.write(tmp_path)
    assert fresh["files"] == MANIFEST["files"]
    assert {k: v for k, v in fresh.items() if k != "generator_sha256"} == \
        {k: v for k, v in MANIFEST.items() if k != "generator_sha256"}


def test_manifest_hashes_match_the_files_and_name_the_generator():
    for rel, digest in MANIFEST["files"].items():
        assert hashlib.sha256((HERE / rel).read_bytes()).hexdigest() == digest, rel
    on_disk = {p.relative_to(HERE).as_posix() for p in (HERE / "cases").rglob("*") if p.is_file()}
    assert on_disk == set(MANIFEST["files"])
    assert MANIFEST["generator_sha256"] == hashlib.sha256((HERE / "build_fixtures.py").read_bytes()).hexdigest()
    assert MANIFEST["execution_authorized"] is False


REASON_CODES = {
    "UNDECLARED_MODERN_CONTRACT", "UNSUPPORTED_CONTRACT_VERSION", "CONTRACT_SOURCE_SET_MISMATCH",
    "PACKET_VERSION_MISMATCH", "INVALID_PACKET_CLOCK", "STALE_PACKET", "FUTURE_PACKET", "UNKNOWN_SOURCE",
    "DUPLICATE_SOURCE", "MISSING_SOURCE", "ARTIFACT_FIELD_MISMATCH", "AUTHORITY_EXPANSION", "KIND_CONFUSION",
    "ARTIFACT_ID_MISMATCH", "BLOB_WITNESS_MISMATCH", "SCHEMA_MISMATCH", "SOURCE_NOT_ELIGIBLE",
    "INVALID_SOURCE_CLOCK", "PROJECTION_MISMATCH", "FUTURE_SOURCE_CLOCK", "SUMMARY_TOO_LARGE"}


@pytest.mark.parametrize("case", sorted(MANIFEST["cases"]))
def test_every_case_ends_in_its_declared_outcome(case):
    expected = json.loads((HERE / "cases" / case / "expected.json").read_text())
    want = expected["expect"] if expected["path"] == "packet" else expected["expect_by_source"]
    assert want == MANIFEST["cases"][case]["expect"]
    assert BF.outcome(HERE / "cases" / case) == want


def test_both_paths_and_every_reason_code_are_covered():
    packet = {c["expect"] for c in MANIFEST["cases"].values() if c["path"] == "packet"}
    assert packet == REASON_CODES | {"ACCEPT"}
    live = {v for c in MANIFEST["cases"].values() if c["path"] == "live" for v in c["expect"].values()}
    assert live >= {"ACCEPT", "FUTURE_SOURCE_CLOCK", "INVALID_SOURCE_CLOCK", "SCHEMA_MISMATCH",
                    "SOURCE_NOT_ELIGIBLE", "UNDECLARED_MODERN_CONTRACT"}
    assert packet - {"ACCEPT"} <= REASON_CODES and live - {"ACCEPT"} <= REASON_CODES


def test_malformed_inputs_reject_instead_of_raising():
    contract, block, sources, expected = BF.load_case(HERE / "cases" / "accept_modern6")
    path = "automation_intelligence/cl_lab/sec_edgar_research_context.json"
    for raw in (b"", b"[]", b"null", b"\xff\xfe"):
        assert BF.reference_live_verify(contract, dict(sources, **{path: raw}), expected["consumer_now"])[
            "sec_edgar"] == "SCHEMA_MISMATCH"
    for clock in (None, "", "yesterday", 5, "2026-10-11"):
        assert BF.reference_verify(contract, dict(block, observed_at=clock), sources,
                                   expected["consumer_now"]) == "INVALID_PACKET_CLOCK"


def test_frozen_contract_comparison_is_json_type_sensitive():
    contract, block, sources, expected = BF.load_case(HERE / "cases" / "accept_modern6")
    widened_head = dict(contract, execution_authorized=0)
    assert BF.reference_verify(widened_head, block, sources, expected["consumer_now"]) == "AUTHORITY_EXPANSION"

    for field, value in (("execution_authorized", 0), ("collection_only", 1)):
        changed = json.loads(json.dumps(contract))
        changed["sources"][0][field] = value
        assert BF.reference_verify(changed, block, sources, expected["consumer_now"]) == \
            "CONTRACT_SOURCE_SET_MISMATCH"


def test_malformed_contract_and_packet_ids_reject_without_raising():
    contract, block, sources, expected = BF.load_case(HERE / "cases" / "accept_modern6")
    malformed_contract = json.loads(json.dumps(contract))
    malformed_contract["sources"][0]["id"] = []
    assert BF.reference_verify(malformed_contract, block, sources, expected["consumer_now"]) == \
        "CONTRACT_SOURCE_SET_MISMATCH"

    bad_lane = json.loads(json.dumps(block))
    bad_lane["historical_artifacts"][0]["lane"] = []
    assert BF.reference_verify(contract, bad_lane, sources, expected["consumer_now"]) == "UNKNOWN_SOURCE"

    bad_artifact_id = json.loads(json.dumps(block))
    bad_artifact_id["historical_artifacts"][0]["artifact_id"] = []
    assert BF.reference_verify(contract, bad_artifact_id, sources, expected["consumer_now"]) == \
        "ARTIFACT_ID_MISMATCH"


@pytest.mark.parametrize("clock", [
    "0001-01-01T00:00:00+23:59",
    "9999-12-31T23:59:59-23:59",
])
def test_utc_offset_overflow_clocks_reject_deterministically(clock):
    contract, block, sources, expected = BF.load_case(HERE / "cases" / "accept_modern6")
    assert BF.reference_verify(contract, dict(block, observed_at=clock), sources,
                               expected["consumer_now"]) == "INVALID_PACKET_CLOCK"

    path = "automation_intelligence/provider_collection_v1/research_context.json"
    doc = json.loads(sources[path])
    doc["snapshot_at_utc"] = clock
    live = BF.reference_live_verify(contract, dict(sources, **{path: BF._dump(doc)}), expected["consumer_now"])
    assert live["provider_collection"] == "INVALID_SOURCE_CLOCK"


@pytest.mark.parametrize("summary_value,expected_result", [
    (float("nan"), "SCHEMA_MISMATCH"),
    ("x" * 70000, "SUMMARY_TOO_LARGE"),
])
def test_live_path_preserves_finite_and_bounded_summary_guards(summary_value, expected_result):
    contract, _, sources, expected = BF.load_case(HERE / "cases" / "accept_modern6")
    path = "automation_intelligence/provider_collection_v1/research_context.json"
    doc = json.loads(sources[path])
    doc["summary"]["providers_total"] = summary_value
    live = BF.reference_live_verify(contract, dict(sources, **{path: BF._dump(doc)}), expected["consumer_now"])
    assert live["provider_collection"] == expected_result

    legacy_path = "automation_intelligence/flow/latest.json"
    legacy_doc = json.loads(sources[legacy_path])
    legacy_doc["NET_NEW_DELTA"] = {"synthetic": summary_value}
    live = BF.reference_live_verify(
        contract,
        dict(sources, **{legacy_path: BF._dump(legacy_doc)}),
        expected["consumer_now"],
    )
    assert live["flow_microstructure"] == expected_result


def test_malformed_artifact_values_reject_without_raising():
    contract, block, sources, expected = BF.load_case(HERE / "cases" / "accept_modern6")
    for artifact_kind, field in (("RESEARCH_CONTEXT_DOCUMENT", "fields_bytes"),
                                 ("HISTORICAL_LATEST", "findings")):
        malformed = json.loads(json.dumps(block))
        art = next(a for a in malformed["historical_artifacts"] if a["artifact_kind"] == artifact_kind)
        if artifact_kind == "RESEARCH_CONTEXT_DOCUMENT":
            art["summary"][field] = float("nan")
        else:
            art["summary"][field] = [float("nan")]
        assert BF.reference_verify(contract, malformed, sources, expected["consumer_now"]) == \
            "ARTIFACT_ID_MISMATCH"


def test_live_paths_reject_nonfinite_allowlisted_values():
    contract, _, sources, expected = BF.load_case(HERE / "cases" / "accept_modern6")

    provider_path = "automation_intelligence/provider_collection_v1/research_context.json"
    provider_doc = json.loads(sources[provider_path])
    provider_doc["summary"]["providers_total"] = float("nan")
    live = BF.reference_live_verify(
        contract, dict(sources, **{provider_path: BF._dump(provider_doc)}), expected["consumer_now"]
    )
    assert live["provider_collection"] == "SCHEMA_MISMATCH"

    flow_path = "automation_intelligence/flow/latest.json"
    flow_doc = json.loads(sources[flow_path])
    flow_doc["NET_NEW_DELTA"] = {"synthetic_metric": float("nan")}
    live = BF.reference_live_verify(
        contract, dict(sources, **{flow_path: BF._dump(flow_doc)}), expected["consumer_now"]
    )
    assert live["flow_microstructure"] == "SCHEMA_MISMATCH"


def test_legacy_artifacts_are_todays_exporter_output():
    contract, block, sources, _ = BF.load_case(HERE / "cases" / "accept_legacy4")
    for art in block["historical_artifacts"]:
        assert art["artifact_kind"] == "HISTORICAL_LATEST"
        assert art == BF.legacy_artifact(art["lane"], sources[art["path"]])


def test_new_kind_artifacts_never_carry_legacy_run_fields():
    _, block, sources, _ = BF.load_case(HERE / "cases" / "accept_modern6")
    docs = [a for a in block["historical_artifacts"] if a["artifact_kind"] == "RESEARCH_CONTEXT_DOCUMENT"]
    assert {a["lane"] for a in docs} == {"provider_collection", "sec_edgar"}
    for art in docs:
        assert set(art) == BF.DOC_ARTIFACT_FIELDS
        assert art["run_id"] is None and art["run_status"] is None
        doc = json.loads(sources[art["path"]])
        assert not any(k.startswith("RUN_") or k == "COLLECTION_ONLY" for k in doc)
