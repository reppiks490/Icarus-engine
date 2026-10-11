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


@pytest.mark.parametrize("case", sorted(MANIFEST["cases"]))
def test_every_case_ends_in_its_declared_outcome(case):
    contract, block, sources, expected = BF.load_case(HERE / "cases" / case)
    assert expected["expect"] == MANIFEST["cases"][case]["expect"]
    assert BF.reference_verify(contract, block, sources, expected["consumer_now"]) == expected["expect"]


def test_both_accept_cases_and_every_reason_code_are_covered():
    expects = {c["expect"] for c in MANIFEST["cases"].values()}
    assert expects >= {
        "ACCEPT", "UNDECLARED_MODERN_CONTRACT", "UNSUPPORTED_CONTRACT_VERSION", "CONTRACT_SOURCE_SET_MISMATCH",
        "PACKET_VERSION_MISMATCH", "STALE_PACKET", "FUTURE_PACKET", "UNKNOWN_SOURCE", "DUPLICATE_SOURCE",
        "MISSING_SOURCE", "ARTIFACT_FIELD_MISMATCH", "AUTHORITY_EXPANSION", "KIND_CONFUSION",
        "ARTIFACT_ID_MISMATCH", "BLOB_WITNESS_MISMATCH", "SCHEMA_MISMATCH", "SOURCE_NOT_ELIGIBLE",
        "PROJECTION_MISMATCH", "FUTURE_SOURCE_CLOCK", "SUMMARY_TOO_LARGE"}


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
        assert art["run_id"] is None and art["run_status"] is None
        assert not any(k in json.loads(sources[art["path"]]) for k in BF.RUN_KEYS)
