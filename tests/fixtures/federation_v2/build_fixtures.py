"""J01 fixtures for docs/FEDERATION_HISTORICAL_CONTEXT_V2.md: labeled test artifacts, synthetic data only.

Writes one directory per case under ``cases/``:

- ``contract_historical_context.json``: the contract's ``historical_context`` block;
- ``packet_block.json`` (packet cases only): the part of a peer packet J01 governs (``source_commit``,
  ``observed_at``, ``historical_context_version`` when present, ``historical_artifacts``);
- ``sources/<path>``: the source documents as they would exist at ``source_commit``;
- ``expected.json``: for packet cases ``ACCEPT`` or one reason code and the consumer clock; for live-ingest
  cases one outcome per source and the live clock.

``reference_verify`` (packet acceptance) and ``reference_live_verify`` (live ingest) apply specification §6
in its frozen order. They exist to prove every negative case fails for exactly its declared reason; the
Icarus consumer is Codex's own implementation.

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


def expected_entry(source_id: str, version: int) -> dict:
    """The frozen contract entry for one source under contract version 1 (legacy) or 2."""
    if source_id in _LEGACY_SOURCES:
        entry = {"id": source_id, **copy.deepcopy(_LEGACY_SOURCES[source_id])}
        if version == 2:
            entry["kind"] = "RUN_LATEST"
    else:
        entry = {"id": source_id, "kind": "RESEARCH_CONTEXT_DOCUMENT", **copy.deepcopy(_DOCUMENT_SOURCES[source_id])}
    entry.update({"research_context_eligible": True, "candidate_evidence_eligible": False,
                  "execution_authorized": False})
    return entry


def _clock(value):
    """Timezone-aware ISO-8601 normalized to UTC 'Z', or None when missing, naive or malformed."""
    try:
        return _time(value)
    except (TypeError, ValueError):
        return None


def document_projection(entry: dict, doc: dict) -> dict:
    """The §5 summary and clocks of a RESEARCH_CONTEXT_DOCUMENT. An invalid clock is carried as given."""
    fields = {f: doc[f] for f in entry["summary_fields"] if f in doc}
    encoded = canonical(fields)
    raw_clock = doc.get(entry["collection_clock_field"])
    return {
        "summary": {"fields_present": sorted(fields), "fields_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                    "fields_bytes": len(encoded.encode("utf-8"))},
        "clocks": {"collection_clock_field": entry["collection_clock_field"],
                   "collected_at": _clock(raw_clock) or raw_clock,
                   "availability_clock": entry["availability_clock"]},
    }


DOC_ARTIFACT_FIELDS = frozenset({
    "lane", "artifact_kind", "path", "schema_value", "source_artifact_blob_sha", "run_id", "run_status",
    "evidence_status", "research_context_eligible", "candidate_evidence_eligible", "summary", "clocks",
    "execution_authorized", "artifact_id"})


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
        raw = raws[by_id[sid]["path"]]
        if sid in _LEGACY_SOURCES:
            artifacts.append(legacy_artifact(sid, raw))
        else:
            artifacts.append(document_artifact(expected_entry(sid, 2), json.loads(raw), raw))
    artifacts.sort(key=lambda a: (a["lane"], str(a.get("run_id") or "")))
    block = {"source_commit": SOURCE_COMMIT, "observed_at": observed_at, "historical_artifacts": artifacts}
    if version is not None:
        block["historical_context_version"] = version
    return block


# ---------------------------------------------------------------------------- reference check (spec §6 order)

class Reject(Exception):
    pass


WIDENING = {"candidate_evidence_eligible": True, "execution_authorized": True, "raw_payloads_eligible": True}


def check_contract(contract: dict) -> int:
    """C1-C4 of §6: the contract's version, source set, frozen head and frozen source entries."""
    if "contract_version" in contract:
        version = contract["contract_version"]
        if type(version) is not int or version != 2:  # True is not 1 and 2.0 is not 2
            raise Reject("UNSUPPORTED_CONTRACT_VERSION")
    else:
        version = 1
    sources = contract.get("sources")
    if not isinstance(sources, list) or not all(isinstance(s, dict) for s in sources):
        raise Reject("CONTRACT_SOURCE_SET_MISMATCH")
    ids = sorted(str(s.get("id")) for s in sources)
    if version == 1 and ids != sorted(LEGACY_IDS):
        raise Reject("UNDECLARED_MODERN_CONTRACT")
    if version == 2 and ids != sorted(MODERN_IDS):
        raise Reject("CONTRACT_SOURCE_SET_MISMATCH")
    if any(contract.get(k) != v for k, v in _BLOCK_HEAD.items()):
        raise Reject("AUTHORITY_EXPANSION")
    for source in sources:
        want = expected_entry(source["id"], version)
        if source != want:
            if any(source.get(k) == v for k, v in WIDENING.items()):
                raise Reject("AUTHORITY_EXPANSION")
            raise Reject("CONTRACT_SOURCE_SET_MISMATCH")
    return version


def _json_object(raw: bytes | None) -> dict:
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError):
        raise Reject("SCHEMA_MISMATCH") from None
    if not isinstance(doc, dict):
        raise Reject("SCHEMA_MISMATCH")
    return doc


def _check_document(entry: dict, doc: dict) -> str:
    """D7-D11 for a RESEARCH_CONTEXT_DOCUMENT; shared by the packet and live paths. Returns the clock."""
    if doc.get(entry["schema_key"]) != entry["schema_value"]:
        raise Reject("SCHEMA_MISMATCH")
    if (doc.get("authority") != "RESEARCH_CONTEXT_ONLY" or doc.get(entry["raw_exclusion_field"]) is not False
            or any(doc.get(k) is not False for k in ("execution_authorized", "production_decision_authorized",
                                                     "automatic_model_promotion"))):
        raise Reject("AUTHORITY_EXPANSION")
    if any(str(k).startswith("RUN_") or k == "COLLECTION_ONLY" for k in doc):
        raise Reject("KIND_CONFUSION")
    rule = entry.get("eligibility")
    if rule and doc.get(rule["field"]) != rule["equals"]:
        raise Reject("SOURCE_NOT_ELIGIBLE")
    clock = _clock(doc.get(entry["collection_clock_field"]))
    if clock is None:
        raise Reject("INVALID_SOURCE_CLOCK")
    return clock


def _check_size(entry: dict, doc: dict) -> None:
    if len(canonical({f: doc[f] for f in entry["summary_fields"] if f in doc}).encode("utf-8")) > SUMMARY_BOUND:
        raise Reject("SUMMARY_TOO_LARGE")


def _check_run_latest_document(entry: dict, doc: dict) -> None:
    """Today's production guards for a RUN_LATEST document (live and packet paths)."""
    core = doc.get("RUN_CORE") if isinstance(doc.get("RUN_CORE"), dict) else {}
    if (doc.get("execution_authorized") is not False or core.get("execution_authorized") not in (None, False)
            or doc.get("trading_execution_authorized") is True or core.get("trading_execution_authorized") is True):
        raise Reject("AUTHORITY_EXPANSION")
    if entry["collection_only"] and doc.get("COLLECTION_ONLY") is not True:
        raise Reject("SOURCE_NOT_ELIGIBLE")


def _same_id(art: dict) -> bool:
    return art.get("artifact_id") == _sha256({k: v for k, v in art.items() if k != "artifact_id"})


def _check_document_artifact(entry: dict, art: dict, sources: dict[str, bytes], observed_at: str) -> None:
    if set(art) != DOC_ARTIFACT_FIELDS:                                                     # D1
        raise Reject("ARTIFACT_FIELD_MISMATCH")
    if (art["artifact_kind"] != "RESEARCH_CONTEXT_DOCUMENT" or art["path"] != entry["path"]  # D2
            or art["evidence_status"] != entry["evidence_status"] or art["research_context_eligible"] is not True):
        raise Reject("ARTIFACT_FIELD_MISMATCH")
    if art["candidate_evidence_eligible"] is not False or art["execution_authorized"] is not False:  # D3
        raise Reject("AUTHORITY_EXPANSION")
    if art["run_id"] is not None or art["run_status"] is not None:                          # D4
        raise Reject("KIND_CONFUSION")
    if not _same_id(art):                                                                   # D5
        raise Reject("ARTIFACT_ID_MISMATCH")
    raw = sources.get(entry["path"])
    if raw is None or _git_blob_sha(raw) != art["source_artifact_blob_sha"]:               # D6
        raise Reject("BLOB_WITNESS_MISMATCH")
    doc = _json_object(raw)                                                                 # D7
    if art["schema_value"] != entry["schema_value"]:
        raise Reject("SCHEMA_MISMATCH")
    clock = _check_document(entry, doc)                                                     # D7-D11
    proj = document_projection(entry, doc)
    if proj["summary"] != art["summary"] or proj["clocks"] != art["clocks"]:               # D12
        raise Reject("PROJECTION_MISMATCH")
    if (_dt(clock) - _dt(observed_at)).total_seconds() > MAX_FUTURE_S:                      # D13
        raise Reject("FUTURE_SOURCE_CLOCK")
    _check_size(entry, doc)                                                                 # D14


def _check_legacy_artifact(entry: dict, art: dict, sources: dict[str, bytes]) -> None:
    if art.get("artifact_kind") != "HISTORICAL_LATEST" or art.get("path") != entry["path"]:  # L1
        raise Reject("ARTIFACT_FIELD_MISMATCH")
    if art.get("candidate_evidence_eligible") is not False or art.get("execution_authorized") is not False:  # L2
        raise Reject("AUTHORITY_EXPANSION")
    if not _same_id(art):                                                                   # L3
        raise Reject("ARTIFACT_ID_MISMATCH")
    raw = sources.get(entry["path"])
    if raw is None or _git_blob_sha(raw) != art.get("source_artifact_blob_sha"):           # L4
        raise Reject("BLOB_WITNESS_MISMATCH")
    doc = _json_object(raw)                                                                 # L5
    _check_run_latest_document(entry, doc)                                                  # L6
    if art != legacy_artifact(entry["id"], raw):                                           # L7
        raise Reject("PROJECTION_MISMATCH")
    if (art.get("run_status") != "RUN_PERSISTED" or art.get("evidence_status") != entry["evidence_status"]
            or art.get("research_context_eligible") is not True):                          # L8
        raise Reject("SOURCE_NOT_ELIGIBLE")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def reference_verify(contract: dict, block: dict, sources: dict[str, bytes], consumer_now: str) -> str:
    """The packet-acceptance path: ACCEPT, or the first reason code in §6 order."""
    try:
        version = check_contract(contract)                                                  # C1-C4
        if version == 1 and "historical_context_version" in block:                          # P1
            raise Reject("PACKET_VERSION_MISMATCH")
        if version == 2 and (type(block.get("historical_context_version")) is not int
                             or block.get("historical_context_version") != 2):
            raise Reject("PACKET_VERSION_MISMATCH")
        observed = _clock(block.get("observed_at"))                                         # P2
        if observed is None:
            raise Reject("INVALID_PACKET_CLOCK")
        age = (_dt(consumer_now) - _dt(observed)).total_seconds()                           # P3
        if age > MAX_AGE_S:
            raise Reject("STALE_PACKET")
        if age < -MAX_FUTURE_S:
            raise Reject("FUTURE_PACKET")
        artifacts = block.get("historical_artifacts")
        if not isinstance(artifacts, list):
            raise Reject("ARTIFACT_FIELD_MISMATCH")
        by_id = {s["id"]: s for s in contract["sources"]}
        seen, ids = set(), set()
        for art in artifacts:                                                               # P4
            if not isinstance(art, dict):
                raise Reject("ARTIFACT_FIELD_MISMATCH")
            sid = art.get("lane")
            if sid not in by_id:
                raise Reject("UNKNOWN_SOURCE")
            if sid in seen:
                raise Reject("DUPLICATE_SOURCE")
            seen.add(sid)
            if art.get("artifact_id") in ids:
                raise Reject("ARTIFACT_ID_MISMATCH")
            ids.add(art.get("artifact_id"))
            if by_id[sid].get("kind") == "RESEARCH_CONTEXT_DOCUMENT":
                _check_document_artifact(by_id[sid], art, sources, observed)
            else:
                _check_legacy_artifact(by_id[sid], art, sources)
        if seen != set(by_id):                                                              # P5
            raise Reject("MISSING_SOURCE")
    except Reject as r:
        return str(r)
    return "ACCEPT"


def reference_live_verify(contract: dict, sources: dict[str, bytes], live_now: str) -> dict[str, str]:
    """The live-ingest path: one outcome per declared source, each journaled or rejected on its own."""
    try:
        check_contract(contract)
    except Reject as r:
        return {"*": str(r)}
    out = {}
    for entry in contract["sources"]:
        try:
            raw = sources.get(entry["path"])
            if raw is None:
                raise Reject("MISSING_SOURCE")
            doc = _json_object(raw)
            if entry.get("kind") == "RESEARCH_CONTEXT_DOCUMENT":
                clock = _check_document(entry, doc)
                if (_dt(clock) - _dt(live_now)).total_seconds() > MAX_FUTURE_S:
                    raise Reject("FUTURE_SOURCE_CLOCK")
                _check_size(entry, doc)
            else:
                _check_run_latest_document(entry, doc)
            out[entry["id"]] = "ACCEPT"
        except Reject as r:
            out[entry["id"]] = str(r)
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------- cases

def _reid(art: dict) -> dict:
    art = {k: v for k, v in art.items() if k != "artifact_id"}
    art["artifact_id"] = _sha256(art)
    return art


def _case(contract, raws, block, expect, now=CONSUMER_NOW, note=""):
    return {"path": "packet", "contract": contract, "raws": raws, "block": block, "expect": expect,
            "now": now, "note": note}


def _live(contract, raws, expect_by_source, now, note=""):
    return {"path": "live", "contract": contract, "raws": raws, "block": None, "expect": expect_by_source,
            "now": now, "note": note}


def build_cases() -> dict[str, dict]:
    docs = base_sources()
    raws = {p: _dump(d) for p, d in docs.items()}
    legacy_paths = {_LEGACY_SOURCES[i]["path"] for i in LEGACY_IDS}
    legacy_raws = {p: r for p, r in raws.items() if p in legacy_paths}
    legacy_c, modern_c = contract_block(None, LEGACY_IDS), contract_block(2)
    legacy_b, modern_b = packet_block(legacy_c, legacy_raws, None), packet_block(modern_c, raws, 2)

    def find(arts, sid):
        return next(a for a in arts if a["lane"] == sid)

    def mutated_block(fn, base=modern_b):
        block = copy.deepcopy(base)
        fn(block["historical_artifacts"])
        return block

    def swap(sid, drop=(), **changes):
        def fn(arts):
            i = arts.index(find(arts, sid))
            art = {k: v for k, v in {**arts[i], **changes}.items() if k not in drop}
            arts[i] = _reid(art)
        return fn

    def contract_with(base=modern_c, head=None, **source_changes):
        c = copy.deepcopy(base)
        c.update(head or {})
        for sid, changes in source_changes.items():
            entry = next(s for s in c["sources"] if s["id"] == sid)
            entry.update(changes)
        return c

    def edited(path, edit=None, raw=None):
        new = dict(raws)
        if raw is not None:
            new[path] = raw
        else:
            doc = copy.deepcopy(docs[path])
            edit(doc)
            new[path] = _dump(doc)
        return new

    def doc_case(sid, edit, expect, note=""):
        path = expected_entry(sid, 2)["path"]
        new_raws = edited(path, edit)
        if sid in _LEGACY_SOURCES:
            block = copy.deepcopy(modern_b)
            arts = block["historical_artifacts"]
            arts[arts.index(find(arts, sid))] = legacy_artifact(sid, new_raws[path])
        else:
            block = packet_block(modern_c, new_raws, 2)
        return _case(modern_c, new_raws, block, expect, note=note)

    pc, sec = _DOCUMENT_SOURCES["provider_collection"]["path"], _DOCUMENT_SOURCES["sec_edgar"]["path"]
    flow = _LEGACY_SOURCES["flow_microstructure"]["path"]
    cases = {
        # §2: versions and the contract
        "accept_legacy4": _case(legacy_c, legacy_raws, legacy_b, "ACCEPT",
                                note="today's working shape: four sources, no versions"),
        "accept_modern6": _case(modern_c, raws, modern_b, "ACCEPT",
                                note="replay verifies again but may write zero new journal rows"),
        "undeclared_modern_contract": _case(contract_block(None), raws, legacy_b, "UNDECLARED_MODERN_CONTRACT",
                                            note="the contract on Engine main today"),
        "unsupported_contract_version": _case(dict(modern_c, contract_version=3), raws, modern_b,
                                              "UNSUPPORTED_CONTRACT_VERSION"),
        "contract_version_bool": _case(dict(modern_c, contract_version=True), raws, modern_b,
                                       "UNSUPPORTED_CONTRACT_VERSION", note="true must not stand for a version"),
        "contract_version_float": _case(dict(modern_c, contract_version=2.0), raws, modern_b,
                                        "UNSUPPORTED_CONTRACT_VERSION", note="2.0 must not stand for 2"),
        "contract_source_set_mismatch": _case(contract_block(2, MODERN_IDS[:-1]), raws, modern_b,
                                              "CONTRACT_SOURCE_SET_MISMATCH"),
        "contract_head_authority": _case(contract_with(head={"execution_authorized": True}), raws, modern_b,
                                         "AUTHORITY_EXPANSION"),
        "contract_witness_weakened": _case(contract_with(head={"source_artifact_blob_required": False}), raws,
                                           modern_b, "AUTHORITY_EXPANSION",
                                           note="weakening a verification requirement widens what is accepted"),
        "contract_truth_invariant": _case(contract_with(head={"truth_contract": {
            **_BLOCK_HEAD["truth_contract"], "historical_context_never_bypasses_foundry": False}}), raws, modern_b,
            "AUTHORITY_EXPANSION"),
        "contract_source_widened": _case(contract_with(sec_edgar={"candidate_evidence_eligible": True}), raws,
                                         modern_b, "AUTHORITY_EXPANSION"),
        "contract_source_field_changed": _case(contract_with(provider_collection={"summary_fields": ["summary"]}),
                                               raws, modern_b, "CONTRACT_SOURCE_SET_MISMATCH"),
        "contract_eligibility_removed": _case(contract_with(sec_edgar={"eligibility": None}),
                                              edited(sec, lambda d: d.update(status="error")), modern_b,
                                              "CONTRACT_SOURCE_SET_MISMATCH",
                                              note="an SEC error document cannot pass by deleting the rule"),
        # §2: the packet
        "legacy_packet_under_modern_contract": _case(modern_c, raws, legacy_b, "PACKET_VERSION_MISMATCH",
                                                     note="never downgrade six to four"),
        "modern_packet_under_legacy_contract": _case(legacy_c, raws, modern_b, "PACKET_VERSION_MISMATCH"),
        "legacy_packet_explicit_version": _case(legacy_c, legacy_raws, dict(legacy_b, historical_context_version=1),
                                                "PACKET_VERSION_MISMATCH", note="legacy packets omit the field"),
        "packet_version_float": _case(modern_c, raws, dict(modern_b, historical_context_version=2.0),
                                      "PACKET_VERSION_MISMATCH"),
        "invalid_packet_clock": _case(modern_c, raws, dict(modern_b, observed_at="2026-10-11T06:00:00"),
                                      "INVALID_PACKET_CLOCK", note="naive timestamp"),
        "stale_packet": _case(modern_c, raws, modern_b, "STALE_PACKET", now="2026-10-11T06:30:01Z"),
        "future_packet": _case(modern_c, raws, modern_b, "FUTURE_PACKET", now="2026-10-11T05:54:59Z"),
        # §6: artifacts
        "missing_source": _case(modern_c, raws, mutated_block(
            lambda arts: arts.remove(find(arts, "sec_edgar"))), "MISSING_SOURCE", note="partial five"),
        "unknown_source": _case(modern_c, raws, mutated_block(
            lambda arts: arts.append(_reid(dict(find(arts, "sec_edgar"), lane="mystery_source")))),
            "UNKNOWN_SOURCE"),
        "duplicate_source": _case(modern_c, raws, mutated_block(
            lambda arts: arts.append(copy.deepcopy(find(arts, "provider_collection")))), "DUPLICATE_SOURCE"),
        "artifact_missing_field": _case(modern_c, raws, mutated_block(swap("provider_collection", drop=("clocks",))),
                                        "ARTIFACT_FIELD_MISMATCH"),
        "artifact_extra_field": _case(modern_c, raws, mutated_block(swap("provider_collection", note="extra")),
                                      "ARTIFACT_FIELD_MISMATCH"),
        "artifact_field_mismatch": _case(modern_c, raws, mutated_block(
            swap("provider_collection", path="automation_intelligence/elsewhere.json")), "ARTIFACT_FIELD_MISMATCH"),
        "artifact_authority_expansion": _case(modern_c, raws, mutated_block(
            swap("sec_edgar", candidate_evidence_eligible=True)), "AUTHORITY_EXPANSION"),
        "artifact_kind_confusion": _case(modern_c, raws, mutated_block(
            swap("provider_collection", run_status="RUN_PERSISTED")), "KIND_CONFUSION",
            note="invented RUN_PERSISTED on a research-context artifact"),
        "artifact_id_mismatch": _case(modern_c, raws, mutated_block(
            lambda arts: find(arts, "sec_edgar").update(artifact_id="0" * 64)), "ARTIFACT_ID_MISMATCH"),
        "blob_witness_mismatch": _case(modern_c, raws, mutated_block(
            swap("provider_collection", source_artifact_blob_sha="f" * 40)), "BLOB_WITNESS_MISMATCH"),
        "projection_mismatch": _case(modern_c, raws, mutated_block(
            swap("provider_collection", summary={**find(modern_b["historical_artifacts"], "provider_collection")
                                                 ["summary"], "fields_sha256": "0" * 64})), "PROJECTION_MISMATCH"),
        "legacy_projection_mismatch": _case(modern_c, raws, mutated_block(
            swap("apex_council", summary={**find(modern_b["historical_artifacts"], "apex_council")["summary"],
                                          "next": "edited"})), "PROJECTION_MISMATCH"),
        # §6: documents
        "schema_mismatch": doc_case("provider_collection",
                                    lambda d: d.update(schema_version="icarus-provider-research-context-v2"),
                                    "SCHEMA_MISMATCH"),
        "document_authority_expansion": doc_case("sec_edgar", lambda d: d.update(execution_authorized=True),
                                                 "AUTHORITY_EXPANSION"),
        "raw_payloads_included": doc_case("provider_collection", lambda d: d.update(raw_payloads_included=True),
                                          "AUTHORITY_EXPANSION"),
        "document_kind_confusion": doc_case("provider_collection", lambda d: d.update(COLLECTION_ONLY=True),
                                            "KIND_CONFUSION", note="legacy field added to a new-kind document"),
        "document_run_prefixed_key": doc_case("sec_edgar", lambda d: d.update(RUN_NOTE="x"), "KIND_CONFUSION",
                                              note="every RUN_* key is forbidden on the new kind"),
        "source_not_eligible": doc_case("sec_edgar", lambda d: d.update(status="error"), "SOURCE_NOT_ELIGIBLE"),
        "invalid_source_clock_missing": doc_case("sec_edgar", lambda d: d.pop("generated_at"),
                                                 "INVALID_SOURCE_CLOCK"),
        "invalid_source_clock_naive": doc_case("provider_collection",
                                               lambda d: d.update(snapshot_at_utc="2026-10-11T05:00:00"),
                                               "INVALID_SOURCE_CLOCK"),
        "future_source_clock": doc_case("sec_edgar", lambda d: d.update(generated_at="2026-10-11T06:05:01+00:00"),
                                        "FUTURE_SOURCE_CLOCK"),
        "summary_too_large": doc_case(
            "sec_edgar",
            lambda d: d["tickers"].update({"SYNBIG": {"latest_facts": {"Note|text": {
                "accepted_at": "2026-07-31T14:01:02+00:00", "value": "x" * (SUMMARY_BOUND + 1)}}}}),
            "SUMMARY_TOO_LARGE"),
        "legacy_flow_without_collection_only": doc_case("flow_microstructure", lambda d: d.pop("COLLECTION_ONLY"),
                                                        "SOURCE_NOT_ELIGIBLE"),
        "legacy_run_status_failed": doc_case("robustness_guardian", lambda d: d.update(RUN_STATUS="FAILED"),
                                             "SOURCE_NOT_ELIGIBLE"),
    }
    bad = b"{not json\n"
    bad_raws = edited(pc, raw=bad)
    cases["malformed_source_json"] = _case(modern_c, bad_raws, mutated_block(
        swap("provider_collection", source_artifact_blob_sha=_git_blob_sha(bad))), "SCHEMA_MISMATCH")

    # live-ingest path (§6, independent of any packet)
    later = "2026-10-20T00:00:00Z"
    ok = {sid: "ACCEPT" for sid in MODERN_IDS}
    cases["live_accept_old_sources"] = _live(modern_c, raws, ok, later,
                                             note="old collection clocks are history, still eligible")
    cases["live_future_source_clock"] = _live(
        modern_c, edited(sec, lambda d: d.update(generated_at="2026-10-11T06:05:01+00:00")),
        dict(ok, sec_edgar="FUTURE_SOURCE_CLOCK"), "2026-10-11T06:00:00Z")
    cases["live_invalid_source_clock"] = _live(
        modern_c, edited(pc, lambda d: d.update(snapshot_at_utc="not a time")),
        dict(ok, provider_collection="INVALID_SOURCE_CLOCK"), later)
    cases["live_malformed_document"] = _live(modern_c, bad_raws, dict(ok, provider_collection="SCHEMA_MISMATCH"),
                                             later)
    cases["live_flow_without_collection_only"] = _live(
        modern_c, edited(flow, lambda d: d.pop("COLLECTION_ONLY")),
        dict(ok, flow_microstructure="SOURCE_NOT_ELIGIBLE"), later)
    cases["live_undeclared_contract"] = _live(contract_block(None), raws, {"*": "UNDECLARED_MODERN_CONTRACT"}, later)
    return cases


def write(out: Path = HERE) -> dict:
    cases = build_cases()
    target = Path(out) / "cases"
    if target.exists():
        shutil.rmtree(target)
    files = {}
    for name, case in sorted(cases.items()):
        d = target / name
        expected = {"path": case["path"], "note": case["note"]}
        if case["path"] == "packet":
            expected.update(expect=case["expect"], consumer_now=case["now"])
        else:
            expected.update(expect_by_source=case["expect"], live_now=case["now"])
        payloads = {"contract_historical_context.json": _dump(case["contract"]), "expected.json": _dump(expected)}
        if case["block"] is not None:
            payloads["packet_block.json"] = _dump(case["block"])
        payloads.update({f"sources/{p}": raw for p, raw in case["raws"].items()})
        for rel, data in payloads.items():
            path = d / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            files[f"cases/{name}/{rel}"] = hashlib.sha256(data).hexdigest()
    generator = Path(__file__).resolve()
    manifest = {
        "schema": "icarus.j01_fixtures/2",
        "specification": "docs/FEDERATION_HISTORICAL_CONTEXT_V2.md",
        "label": "TEST ARTIFACTS ONLY: synthetic documents, no vendor rows, not delivery evidence",
        "generator": "tests/fixtures/federation_v2/build_fixtures.py",
        "generator_sha256": hashlib.sha256(generator.read_bytes()).hexdigest(),
        "source_commit": SOURCE_COMMIT, "observed_at": OBSERVED_AT,
        "cases": {n: {"path": c["path"], "expect": c["expect"], "note": c["note"]} for n, c in sorted(cases.items())},
        "files": dict(sorted(files.items())),
        "execution_authorized": False,
    }
    (Path(out) / "MANIFEST.json").write_bytes(_dump(manifest))
    return manifest


def load_case(case_dir: Path) -> tuple[dict, dict | None, dict[str, bytes], dict]:
    contract = json.loads((case_dir / "contract_historical_context.json").read_text())
    block_path = case_dir / "packet_block.json"
    block = json.loads(block_path.read_text()) if block_path.exists() else None
    expected = json.loads((case_dir / "expected.json").read_text())
    root = case_dir / "sources"
    sources = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    return contract, block, sources, expected


def outcome(case_dir: Path):
    """What the reference check says for one case, in the same shape as expected.json's expectation."""
    contract, block, sources, expected = load_case(case_dir)
    if expected["path"] == "live":
        return reference_live_verify(contract, sources, expected["live_now"])
    return reference_verify(contract, block, sources, expected["consumer_now"])


if __name__ == "__main__":
    m = write()
    print(json.dumps({"cases": len(m["cases"]), "files": len(m["files"])}))
