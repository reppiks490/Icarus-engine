"""J01 fixtures for docs/FEDERATION_HISTORICAL_CONTEXT_V2.md: labeled test artifacts, synthetic data only.

Writes one directory per case under ``cases/``:

- ``contract_historical_context.json``: the contract's ``historical_context`` block;
- ``packet_block.json``: the part of a peer packet J01 governs (``source_commit``, ``observed_at``,
  ``historical_context_version`` when present, ``historical_artifacts``);
- ``sources/<path>``: the source documents as they would exist at ``source_commit``;
- ``expected.json``: ``ACCEPT`` or the reason code of specification §2/§6, and the consumer's clock.

``reference_verify`` is the reference check in specification order. It exists to prove every negative
case fails for exactly its declared reason; the Icarus consumer is Codex's own implementation.

Legacy ``HISTORICAL_LATEST`` artifacts are produced by the current Engine exporter function
(``icarus_engine.interrepo_bridge._historical_artifact``), so they equal today's packets.

Run from the repository root: ``python tests/fixtures/federation_v2/build_fixtures.py``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icarus_engine.interrepo_bridge import _git_blob_sha, _historical_artifact, _time  # noqa: E402

HERE = Path(__file__).resolve().parent
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
OBSERVED_AT = "2026-10-11T06:00:00Z"
CONSUMER_NOW = "2026-10-11T06:10:00Z"
MAX_AGE_S, MAX_FUTURE_S, SUMMARY_BOUND = 1800, 300, 65536

LEGACY_IDS = ("alpha_synthesis", "apex_council", "flow_microstructure", "robustness_guardian")
MODERN_IDS = LEGACY_IDS + ("provider_collection", "sec_edgar")
RUN_KEYS = ("RUN_ID", "RUN_STATUS", "RUN_CORE", "COLLECTION_ONLY")

# The four legacy sources exactly as Engine's contract declares them (copied 2026-10-11).
_LEGACY_SOURCES = {
    "robustness_guardian": {
        "path": "automation_intelligence/agent_fabric/robustness_guardian/latest.json",
        "evidence_status": "HISTORICAL_RESEARCH_EVIDENCE", "collection_only": False,
        "summary_fields": ["RUN_CORE.findings", "RUN_CORE.built_changes", "RUN_CORE.unresolved_risks",
                           "RUN_CORE.NEXT", "RUN_CORE.test_state", "RUN_CORE.base_main_sha",
                           "RUN_CORE.final_main_sha", "RUN_CORE_SHA256", "history_blob_sha"]},
    "alpha_synthesis": {
        "path": "automation_intelligence/agent_fabric/alpha_synthesis/latest.json",
        "evidence_status": "HISTORICAL_RESEARCH_EVIDENCE", "collection_only": False,
        "summary_fields": ["RUN_CORE.evidence_dataset_identity", "RUN_CORE.findings", "RUN_CORE.built_changes",
                           "RUN_CORE.unresolved_risks", "RUN_CORE.NEXT", "RUN_CORE_SHA256",
                           "history_blob_sha", "ledger_blob_sha"]},
    "apex_council": {
        "path": "automation_intelligence/agent_fabric/apex_council/latest.json",
        "evidence_status": "HISTORICAL_RESEARCH_EVIDENCE", "collection_only": False,
        "summary_fields": ["RUN_CORE.specialist_states_consumed", "RUN_CORE.evidence_contract",
                           "RUN_CORE.decision_contract", "RUN_CORE.disagreements_collisions",
                           "RUN_CORE.built_changes", "RUN_CORE.NEXT", "RUN_CORE.base_main_sha",
                           "RUN_CORE.final_main_sha", "RUN_CORE_SHA256", "history_blob_sha", "ledger_blob_sha"]},
    "flow_microstructure": {
        "path": "automation_intelligence/flow/latest.json",
        "evidence_status": "HISTORICAL_COLLECTION_EVIDENCE", "collection_only": True,
        "summary_fields": ["NET_NEW_DELTA", "observations", "PROVIDER_CONFLICTS", "DATA_GAPS",
                           "source_provenance", "quality_notes", "history_blob_sha"]},
}
_DOCUMENT_SOURCES = {
    "provider_collection": {
        "path": "automation_intelligence/provider_collection_v1/research_context.json",
        "evidence_status": "HISTORICAL_COLLECTION_EVIDENCE", "collection_only": True,
        "raw_payloads_eligible": False, "schema_key": "schema_version",
        "schema_value": "icarus-provider-research-context-v1", "raw_exclusion_field": "raw_payloads_included",
        "collection_clock_field": "snapshot_at_utc", "availability_clock": None, "eligibility": None,
        "summary_fields": ["summary", "providers", "snapshot_at_utc"]},
    "sec_edgar": {
        "path": "automation_intelligence/cl_lab/sec_edgar_research_context.json",
        "evidence_status": "HISTORICAL_COLLECTION_EVIDENCE", "collection_only": True,
        "raw_payloads_eligible": False, "schema_key": "schema",
        "schema_value": "icarus.sec_edgar.research_context/1", "raw_exclusion_field": "raw_documents_included",
        "collection_clock_field": "generated_at", "availability_clock": "accepted_at",
        "eligibility": {"field": "status", "equals": "ok"},
        "summary_fields": ["status", "filing_rows", "fact_rows", "tickers"]},
}
_BLOCK_HEAD = {
    "mode": "RESEARCH_CONTEXT_ONLY", "direct_candidate_evidence": False, "automatic_candidate_creation": False,
    "automatic_model_promotion": False, "execution_authorized": False, "production_decision_authorized": False,
    "truth_contract": {
        "foreign_repository_state_is_context_not_native_truth": True,
        "historical_context_never_bypasses_foundry": True, "historical_context_never_bypasses_evaluator": True,
        "historical_context_never_grants_shadow_qualification": True,
        "historical_context_never_grants_execution_authority": True,
        "historical_packet_projection_is_source_derived": True},
    "source_artifact_blob_required": True, "artifact_id_sha256_required": True,
    "packet_projection_verification_required": True,
}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _dump(value) -> bytes:
    return (json.dumps(value, indent=1, sort_keys=True) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------- synthetic sources

def _run_latest(source_id: str) -> dict:
    if source_id == "flow_microstructure":
        return {"RUN_ID": "flow-synthetic-0001", "RUN_STATUS": "RUN_PERSISTED", "COLLECTION_ONLY": True,
                "observations": {"synthetic_metric": 1}, "DATA_GAPS": ["synthetic gap"],
                "NET_NEW_DELTA": {"synthetic": "delta"}, "source_provenance": [{"source": "synthetic"}],
                "PROVIDER_CONFLICTS": [], "quality_notes": ["synthetic"], "history_blob_sha": "d" * 40,
                "execution_authorized": False}
    return {"RUN_ID": f"{source_id}-synthetic-0001", "RUN_STATUS": "RUN_PERSISTED", "execution_authorized": False,
            "RUN_CORE": {"findings": [f"synthetic finding for {source_id}"], "built_changes": ["synthetic change"],
                         "NEXT": "synthetic next step", "base_main_sha": "a" * 40, "final_main_sha": "b" * 40,
                         "execution_authorized": False},
            "RUN_CORE_SHA256": "c" * 64, "history_blob_sha": "d" * 40, "ledger_blob_sha": "e" * 40}


def _provider_doc() -> dict:
    return {"schema_version": "icarus-provider-research-context-v1", "authority": "RESEARCH_CONTEXT_ONLY",
            "automatic_model_promotion": False, "execution_authorized": False,
            "production_decision_authorized": False, "raw_payloads_included": False,
            "snapshot_at_utc": "2026-10-11T05:00:00+00:00",
            "source_root": "automation_intelligence/provider_collection_v1/latest",
            "summary": {"providers_total": 2, "providers_substantive": 1, "collected_rows": 10},
            "providers": {"synthetic_a": {"status": "COLLECTED", "collected_rows": 10},
                          "synthetic_b": {"status": "BLOCKED_MISSING_CREDENTIAL", "collected_rows": 0}}}


def _sec_doc() -> dict:
    return {"schema": "icarus.sec_edgar.research_context/1", "authority": "RESEARCH_CONTEXT_ONLY",
            "automatic_model_promotion": False, "execution_authorized": False,
            "production_decision_authorized": False, "raw_documents_included": False,
            "generated_at": "2026-10-11T05:30:00+00:00", "status": "ok", "filing_rows": 2, "fact_rows": 3,
            "causality": "accepted_at is the availability timestamp; report/end dates never grant earlier availability",
            "source_manifest": "automation_intelligence/cl_lab/sec_edgar_manifest.json",
            "tickers": {"SYNTH": {"latest_facts": {"Assets|USD": {
                "accepted_at": "2026-07-31T14:01:02+00:00", "accession": "0000000000-26-000001",
                "form": "10-Q", "value": 1000}}}}}


def base_sources() -> dict[str, dict]:
    docs = {_LEGACY_SOURCES[i]["path"]: _run_latest(i) for i in LEGACY_IDS}
    docs[_DOCUMENT_SOURCES["provider_collection"]["path"]] = _provider_doc()
    docs[_DOCUMENT_SOURCES["sec_edgar"]["path"]] = _sec_doc()
    return docs


# ---------------------------------------------------------------------------- contract and projection

def contract_block(version: int | None, ids=MODERN_IDS) -> dict:
    sources = []
    for sid in ids:
        if sid in _LEGACY_SOURCES:
            entry = {"id": sid, **copy.deepcopy(_LEGACY_SOURCES[sid])}
            if version == 2:
                entry["kind"] = "RUN_LATEST"
        else:
            entry = {"id": sid, **copy.deepcopy(_DOCUMENT_SOURCES[sid])}
            if version == 2:
                entry["kind"] = "RESEARCH_CONTEXT_DOCUMENT"
            else:  # today's undeclared state: the new sources without a kind or version
                for key in ("schema_key", "schema_value", "raw_exclusion_field", "collection_clock_field",
                            "availability_clock", "eligibility"):
                    entry.pop(key)
        entry.update({"research_context_eligible": True, "candidate_evidence_eligible": False,
                      "execution_authorized": False})
        sources.append(entry)
    block = dict(copy.deepcopy(_BLOCK_HEAD), sources=sources)
    if version is not None:
        block["contract_version"] = version
    return block


def document_projection(entry: dict, doc: dict) -> dict:
    """The §5 summary and clocks of a RESEARCH_CONTEXT_DOCUMENT."""
    fields = {f: doc[f] for f in entry["summary_fields"] if f in doc}
    encoded = canonical(fields)
    return {
        "summary": {"fields_present": sorted(fields), "fields_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                    "fields_bytes": len(encoded.encode("utf-8"))},
        "clocks": {"collection_clock_field": entry["collection_clock_field"],
                   "collected_at": _time(doc.get(entry["collection_clock_field"])),
                   "availability_clock": entry["availability_clock"]},
    }


def document_artifact(entry: dict, doc: dict, raw: bytes) -> dict:
    proj = document_projection(entry, doc)
    artifact = {
        "lane": entry["id"], "artifact_kind": "RESEARCH_CONTEXT_DOCUMENT", "path": entry["path"],
        "schema_value": doc.get(entry["schema_key"]), "source_artifact_blob_sha": _git_blob_sha(raw),
        "run_id": None, "run_status": None, "evidence_status": entry["evidence_status"],
        "research_context_eligible": True, "candidate_evidence_eligible": False,
        "summary": proj["summary"], "clocks": proj["clocks"], "execution_authorized": False,
    }
    artifact["artifact_id"] = _sha256(artifact)
    return artifact


def legacy_artifact(source_id: str, raw: bytes) -> dict:
    """Today's exporter output for one RUN_LATEST source, from the document bytes."""
    path = _LEGACY_SOURCES[source_id]["path"]
    worker_root = path.rsplit("/", 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / path
        target.parent.mkdir(parents=True)
        target.write_bytes(raw)
        return _historical_artifact(Path(tmp), {"name": source_id, "worker_root": worker_root},
                                    source_repository="reppiks490/Icarus-engine")


def packet_block(contract: dict, raws: dict[str, bytes], version: int | None, observed_at=OBSERVED_AT) -> dict:
    by_id = {s["id"]: s for s in contract["sources"]}
    artifacts = []
    for sid in sorted(by_id):
        entry, raw = by_id[sid], raws[by_id[sid]["path"]]
        if sid in _LEGACY_SOURCES:
            artifacts.append(legacy_artifact(sid, raw))
        else:
            artifacts.append(document_artifact({**_DOCUMENT_SOURCES[sid], "id": sid}, json.loads(raw), raw))
    artifacts.sort(key=lambda a: (a["lane"], str(a.get("run_id") or "")))
    block = {"source_commit": SOURCE_COMMIT, "observed_at": observed_at, "historical_artifacts": artifacts}
    if version is not None:
        block["historical_context_version"] = version
    return block


# ---------------------------------------------------------------------------- reference check (spec order)

class Reject(Exception):
    pass


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(_time(value).replace("Z", "+00:00"))


def _check_document_artifact(entry: dict, art: dict, sources: dict[str, bytes], observed_at: str) -> None:
    if (art.get("artifact_kind") != "RESEARCH_CONTEXT_DOCUMENT" or art.get("path") != entry["path"]
            or art.get("evidence_status") != entry["evidence_status"]
            or art.get("research_context_eligible") is not True):
        raise Reject("ARTIFACT_FIELD_MISMATCH")
    if art.get("candidate_evidence_eligible") is not False or art.get("execution_authorized") is not False:
        raise Reject("AUTHORITY_EXPANSION")
    if art.get("run_id") is not None or art.get("run_status") is not None:
        raise Reject("KIND_CONFUSION")
    unsigned = {k: v for k, v in art.items() if k != "artifact_id"}
    if art.get("artifact_id") != _sha256(unsigned):
        raise Reject("ARTIFACT_ID_MISMATCH")
    raw = sources.get(entry["path"])
    if raw is None or _git_blob_sha(raw) != art.get("source_artifact_blob_sha"):
        raise Reject("BLOB_WITNESS_MISMATCH")
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get(entry["schema_key"]) != entry["schema_value"] \
            or art.get("schema_value") != entry["schema_value"]:
        raise Reject("SCHEMA_MISMATCH")
    if (doc.get("authority") != "RESEARCH_CONTEXT_ONLY" or doc.get(entry["raw_exclusion_field"]) is not False
            or any(doc.get(k) is not False for k in ("execution_authorized", "production_decision_authorized",
                                                     "automatic_model_promotion"))):
        raise Reject("AUTHORITY_EXPANSION")
    if any(k in doc for k in RUN_KEYS):
        raise Reject("KIND_CONFUSION")
    rule = entry.get("eligibility")
    if rule and doc.get(rule["field"]) != rule["equals"]:
        raise Reject("SOURCE_NOT_ELIGIBLE")
    proj = document_projection(entry, doc)
    if proj["summary"] != art.get("summary") or proj["clocks"] != art.get("clocks"):
        raise Reject("PROJECTION_MISMATCH")
    if (_dt(proj["clocks"]["collected_at"]) - _dt(observed_at)).total_seconds() > MAX_FUTURE_S:
        raise Reject("FUTURE_SOURCE_CLOCK")
    if len(canonical({f: doc[f] for f in entry["summary_fields"] if f in doc}).encode("utf-8")) > SUMMARY_BOUND:
        raise Reject("SUMMARY_TOO_LARGE")


def _check_legacy_artifact(entry: dict, art: dict, sources: dict[str, bytes]) -> None:
    if art.get("candidate_evidence_eligible") is not False or art.get("execution_authorized") is not False:
        raise Reject("AUTHORITY_EXPANSION")
    unsigned = {k: v for k, v in art.items() if k != "artifact_id"}
    if art.get("artifact_id") != _sha256(unsigned):
        raise Reject("ARTIFACT_ID_MISMATCH")
    raw = sources.get(entry["path"])
    if raw is None or _git_blob_sha(raw) != art.get("source_artifact_blob_sha"):
        raise Reject("BLOB_WITNESS_MISMATCH")
    if art != legacy_artifact(entry["id"], raw):
        raise Reject("PROJECTION_MISMATCH")


def reference_verify(contract: dict, block: dict, sources: dict[str, bytes], consumer_now: str) -> str:
    try:
        declared = [s.get("id") for s in contract.get("sources") or []]
        version = contract.get("contract_version")
        if version is None:
            if sorted(declared) != sorted(LEGACY_IDS):
                raise Reject("UNDECLARED_MODERN_CONTRACT")
            want_packet = 1
        elif version != 2:
            raise Reject("UNSUPPORTED_CONTRACT_VERSION")
        else:
            if sorted(declared) != sorted(MODERN_IDS):
                raise Reject("CONTRACT_SOURCE_SET_MISMATCH")
            want_packet = 2
        if block.get("historical_context_version", 1) != want_packet:
            raise Reject("PACKET_VERSION_MISMATCH")
        age = (_dt(consumer_now) - _dt(block["observed_at"])).total_seconds()
        if age > MAX_AGE_S:
            raise Reject("STALE_PACKET")
        if age < -MAX_FUTURE_S:
            raise Reject("FUTURE_PACKET")
        by_id = {s["id"]: s for s in contract["sources"]}
        seen = set()
        for art in block.get("historical_artifacts") or []:
            sid = art.get("lane")
            if sid not in by_id:
                raise Reject("UNKNOWN_SOURCE")
            if sid in seen:
                raise Reject("DUPLICATE_SOURCE")
            seen.add(sid)
            if by_id[sid].get("kind") == "RESEARCH_CONTEXT_DOCUMENT":
                _check_document_artifact(by_id[sid], art, sources, block["observed_at"])
            else:
                _check_legacy_artifact(by_id[sid], art, sources)
        if seen != set(by_id):
            raise Reject("MISSING_SOURCE")
    except Reject as r:
        return str(r)
    return "ACCEPT"


# ---------------------------------------------------------------------------- cases

def _reid(art: dict) -> dict:
    art = {k: v for k, v in art.items() if k != "artifact_id"}
    art["artifact_id"] = _sha256(art)
    return art


def _case(contract, raws, block, expect, now=CONSUMER_NOW, note=""):
    return {"contract": contract, "raws": raws, "block": block, "expect": expect, "now": now, "note": note}


def build_cases() -> dict[str, dict]:
    docs = base_sources()
    raws = {p: _dump(d) for p, d in docs.items()}
    legacy_raws = {p: r for p, r in raws.items() if p in {_LEGACY_SOURCES[i]["path"] for i in LEGACY_IDS}}
    legacy_c, modern_c = contract_block(None, LEGACY_IDS), contract_block(2)
    modern_b = packet_block(modern_c, raws, 2)
    cases = {
        "accept_legacy4": _case(legacy_c, legacy_raws, packet_block(legacy_c, legacy_raws, None), "ACCEPT",
                                note="today's working shape: four sources, no versions"),
        "accept_modern6": _case(modern_c, raws, modern_b, "ACCEPT", note="replaying it must write zero new rows"),
        "undeclared_modern_contract": _case(contract_block(None), raws, packet_block(legacy_c, legacy_raws, None),
                                            "UNDECLARED_MODERN_CONTRACT", note="the contract on Engine main today"),
        "unsupported_contract_version": _case(dict(modern_c, contract_version=3), raws, modern_b,
                                              "UNSUPPORTED_CONTRACT_VERSION"),
        "contract_source_set_mismatch": _case(contract_block(2, MODERN_IDS[:-1]), raws, modern_b,
                                              "CONTRACT_SOURCE_SET_MISMATCH"),
        "legacy_packet_under_modern_contract": _case(modern_c, raws, packet_block(legacy_c, legacy_raws, None),
                                                     "PACKET_VERSION_MISMATCH", note="never downgrade six to four"),
        "modern_packet_under_legacy_contract": _case(legacy_c, raws, modern_b, "PACKET_VERSION_MISMATCH"),
        "stale_packet": _case(modern_c, raws, modern_b, "STALE_PACKET", now="2026-10-11T06:30:01Z"),
        "future_packet": _case(modern_c, raws, modern_b, "FUTURE_PACKET", now="2026-10-11T05:54:59Z"),
    }

    def mutated_block(fn, base=modern_b):
        block = copy.deepcopy(base)
        fn(block["historical_artifacts"])
        return block

    def find(arts, sid):
        return next(a for a in arts if a["lane"] == sid)

    cases["missing_source"] = _case(modern_c, raws, mutated_block(
        lambda arts: arts.remove(find(arts, "sec_edgar"))), "MISSING_SOURCE", note="partial five")
    cases["unknown_source"] = _case(modern_c, raws, mutated_block(
        lambda arts: arts.append(_reid(dict(find(arts, "sec_edgar"), lane="mystery_source")))), "UNKNOWN_SOURCE")
    cases["duplicate_source"] = _case(modern_c, raws, mutated_block(
        lambda arts: arts.append(copy.deepcopy(find(arts, "provider_collection")))), "DUPLICATE_SOURCE")

    def swap(sid, **changes):
        def fn(arts):
            i = arts.index(find(arts, sid))
            arts[i] = _reid({**arts[i], **changes})
        return fn

    cases["artifact_field_mismatch"] = _case(modern_c, raws, mutated_block(
        swap("provider_collection", path="automation_intelligence/elsewhere.json")), "ARTIFACT_FIELD_MISMATCH")
    cases["artifact_authority_expansion"] = _case(modern_c, raws, mutated_block(
        swap("sec_edgar", candidate_evidence_eligible=True)), "AUTHORITY_EXPANSION")
    cases["artifact_kind_confusion"] = _case(modern_c, raws, mutated_block(
        swap("provider_collection", run_status="RUN_PERSISTED")), "KIND_CONFUSION",
        note="invented RUN_PERSISTED on a research-context artifact")

    def bad_id(arts):
        find(arts, "sec_edgar")["artifact_id"] = "0" * 64
    cases["artifact_id_mismatch"] = _case(modern_c, raws, mutated_block(bad_id), "ARTIFACT_ID_MISMATCH")
    cases["blob_witness_mismatch"] = _case(modern_c, raws, mutated_block(
        swap("provider_collection", source_artifact_blob_sha="f" * 40)), "BLOB_WITNESS_MISMATCH")
    cases["projection_mismatch"] = _case(modern_c, raws, mutated_block(
        swap("provider_collection", summary={**find(modern_b["historical_artifacts"], "provider_collection")["summary"],
                                             "fields_sha256": "0" * 64})), "PROJECTION_MISMATCH")
    cases["legacy_projection_mismatch"] = _case(modern_c, raws, mutated_block(
        swap("apex_council", summary={**find(modern_b["historical_artifacts"], "apex_council")["summary"],
                                      "next": "edited"})), "PROJECTION_MISMATCH")

    def doc_case(sid, edit, expect, note=""):
        path = _DOCUMENT_SOURCES[sid]["path"]
        doc = copy.deepcopy(docs[path])
        edit(doc)
        new_raws = dict(raws, **{path: _dump(doc)})
        return _case(modern_c, new_raws, packet_block(modern_c, new_raws, 2), expect, note=note)

    cases["schema_mismatch"] = doc_case("provider_collection",
                                        lambda d: d.update(schema_version="icarus-provider-research-context-v2"),
                                        "SCHEMA_MISMATCH")
    cases["document_authority_expansion"] = doc_case("sec_edgar", lambda d: d.update(execution_authorized=True),
                                                     "AUTHORITY_EXPANSION")
    cases["raw_payloads_included"] = doc_case("provider_collection", lambda d: d.update(raw_payloads_included=True),
                                              "AUTHORITY_EXPANSION")
    cases["document_kind_confusion"] = doc_case("provider_collection", lambda d: d.update(COLLECTION_ONLY=True),
                                                "KIND_CONFUSION", note="legacy field added to a new-kind document")
    cases["source_not_eligible"] = doc_case("sec_edgar", lambda d: d.update(status="error"), "SOURCE_NOT_ELIGIBLE")
    cases["future_source_clock"] = doc_case("sec_edgar", lambda d: d.update(generated_at="2026-10-11T06:05:01+00:00"),
                                            "FUTURE_SOURCE_CLOCK")
    cases["summary_too_large"] = doc_case(
        "sec_edgar",
        lambda d: d["tickers"].update({"SYNBIG": {"latest_facts": {"Note|text": {
            "accepted_at": "2026-07-31T14:01:02+00:00", "value": "x" * (SUMMARY_BOUND + 1)}}}}),
        "SUMMARY_TOO_LARGE")
    return cases


def write(out: Path = HERE) -> dict:
    cases = build_cases()
    target = Path(out) / "cases"
    if target.exists():
        shutil.rmtree(target)
    files = {}
    for name, case in sorted(cases.items()):
        d = target / name
        payloads = {
            "contract_historical_context.json": _dump(case["contract"]),
            "packet_block.json": _dump(case["block"]),
            "expected.json": _dump({"expect": case["expect"], "consumer_now": case["now"], "note": case["note"]}),
        }
        payloads.update({f"sources/{p}": raw for p, raw in case["raws"].items()})
        for rel, data in payloads.items():
            path = d / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            files[f"cases/{name}/{rel}"] = hashlib.sha256(data).hexdigest()
    generator = Path(__file__).resolve()
    manifest = {
        "schema": "icarus.j01_fixtures/1",
        "specification": "docs/FEDERATION_HISTORICAL_CONTEXT_V2.md",
        "label": "TEST ARTIFACTS ONLY: synthetic documents, no vendor rows, not delivery evidence",
        "generator": "tests/fixtures/federation_v2/build_fixtures.py",
        "generator_sha256": hashlib.sha256(generator.read_bytes()).hexdigest(),
        "source_commit": SOURCE_COMMIT, "observed_at": OBSERVED_AT,
        "cases": {n: {"expect": c["expect"], "note": c["note"]} for n, c in sorted(cases.items())},
        "files": dict(sorted(files.items())),
        "execution_authorized": False,
    }
    (Path(out) / "MANIFEST.json").write_bytes(_dump(manifest))
    return manifest


def load_case(case_dir: Path) -> tuple[dict, dict, dict[str, bytes], dict]:
    contract = json.loads((case_dir / "contract_historical_context.json").read_text())
    block = json.loads((case_dir / "packet_block.json").read_text())
    expected = json.loads((case_dir / "expected.json").read_text())
    root = case_dir / "sources"
    sources = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    return contract, block, sources, expected


if __name__ == "__main__":
    m = write()
    print(json.dumps({"cases": len(m["cases"]), "files": len(m["files"])}))
