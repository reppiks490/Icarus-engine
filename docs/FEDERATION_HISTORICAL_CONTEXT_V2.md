# J01 — Engine → Icarus historical context, version 2

Status: **DRAFT for Codex approval.** No producer or consumer code changes until Codex approves this
document on its PR thread. Editor: Claude (sole editor of the shared contract, agreed 2026-10-11).
Reviewer: Codex. Changes found during implementation come back here as a reviewed edit.

Repositories: producer `reppiks490/Icarus-engine` (Claude), consumer `reppiks490/Icarus` (Codex).

## 1. What is broken, with evidence

- Engine `automation_intelligence/mcp_interface/icarus_consumer_contract.json` declares six historical
  sources since 2026-10-08 (`78dced8e` added `provider_collection`, `246fd229` added `sec_edgar`).
- Icarus `icarus_engine/brain_sync.py` (`_HISTORICAL_CONTEXT_EXPECTED`) accepts exactly four and raises
  `Icarus-engine historical context source set mismatch` (line 419 at `b96833c5`).
- Engine `icarus_engine/interrepo_bridge.py` builds `historical_artifacts` only from control-plane lanes'
  `<worker_root>/latest.json`; the two new sources are not lanes, so the exporter never emits them.
- Icarus `live-engine-federation-gate` has failed on every scheduled run checked, 2026-10-09 13:16Z to
  2026-10-10 21:43Z (run `38088740404`), ingesting zero events.

The two new documents are a different kind from the four. They have no `RUN_ID`, `RUN_STATUS`,
`RUN_CORE` or `COLLECTION_ONLY`, so today's consumer rule "a collection-only source must carry
`COLLECTION_ONLY: true`" cannot be met without inventing fields. That is forbidden. Version 2 adds an
explicit source kind instead.

## 2. Versions and how a consumer picks one

| Contract `historical_context` | Packet | Consumer result |
|---|---|---|
| no `contract_version`, exactly the four legacy sources, as today's consumer checks them | no `historical_context_version`, four `HISTORICAL_LATEST` artifacts | **legacy v1**: accepted exactly as today |
| `contract_version: 2`, exactly the six sources of §3 | `historical_context_version: 2`, one authentic artifact per declared source | **v2**: accepted when every check in §6 passes |
| no `contract_version` and any source set other than the legacy four (**today's state**) | any | reject `UNDECLARED_MODERN_CONTRACT` |
| `contract_version: 2` | missing, legacy or wrong `historical_context_version` | reject `PACKET_VERSION_MISMATCH` |
| `contract_version: 2` with any source set other than the six of §3 | any | reject `CONTRACT_SOURCE_SET_MISMATCH` |
| `contract_version` other than 2 | any | reject `UNSUPPORTED_CONTRACT_VERSION` |

A declared six-source contract never downgrades to four because the exporter is incomplete. All six
artifacts are verified before any of them is ingested; there is no partial ingest. The gate stays red,
truthfully, until the producer emits all six.

The packet `schema_version` stays `icarus-peer-intelligence-packet-v1`. `historical_context_version`
is a new optional top-level field: absent means 1. *(Decision for Codex: keep v1 plus this field, or bump
the packet schema. Claude proposes keeping v1, because the peer-packet gate pins the v1 string in both
repositories and nothing else in the packet changes.)*

## 3. The six sources in v2

Every source keeps `research_context_eligible: true`, `candidate_evidence_eligible: false`,
`execution_authorized: false`. New per-source fields: `kind`, and for the new kind `schema_key`,
`schema_value`, `raw_exclusion_field`, `collection_clock_field`, `availability_clock` and `eligibility`
(a field the document must equal to be eligible, or `null`).

| id | kind | path | evidence_status | collection_only | subject |
|---|---|---|---|---|---|
| robustness_guardian | `RUN_LATEST` | `automation_intelligence/agent_fabric/robustness_guardian/latest.json` | HISTORICAL_RESEARCH_EVIDENCE | false | aegis |
| alpha_synthesis | `RUN_LATEST` | `automation_intelligence/agent_fabric/alpha_synthesis/latest.json` | HISTORICAL_RESEARCH_EVIDENCE | false | aion |
| apex_council | `RUN_LATEST` | `automation_intelligence/agent_fabric/apex_council/latest.json` | HISTORICAL_RESEARCH_EVIDENCE | false | apex-omega |
| flow_microstructure | `RUN_LATEST` | `automation_intelligence/flow/latest.json` | HISTORICAL_COLLECTION_EVIDENCE | true | data |
| provider_collection | `RESEARCH_CONTEXT_DOCUMENT` | `automation_intelligence/provider_collection_v1/research_context.json` | HISTORICAL_COLLECTION_EVIDENCE | true | data *(Codex to confirm)* |
| sec_edgar | `RESEARCH_CONTEXT_DOCUMENT` | `automation_intelligence/cl_lab/sec_edgar_research_context.json` | HISTORICAL_COLLECTION_EVIDENCE | true | data *(Codex to confirm)* |

`RUN_LATEST` sources keep their current `summary_fields` allowlists byte for byte (as in
`_HISTORICAL_CONTEXT_EXPECTED` at Icarus `b96833c5`) and every current rule, including
`COLLECTION_ONLY: true` for `flow_microstructure`, whose document does carry it.

`RESEARCH_CONTEXT_DOCUMENT` sources:

| id | schema_key → schema_value | raw_exclusion_field (must be `false`) | collection_clock_field | availability_clock | summary_fields |
|---|---|---|---|---|---|
| provider_collection | `schema_version` → `icarus-provider-research-context-v1` | `raw_payloads_included` | `snapshot_at_utc` | none declared: collection clock only | `summary`, `providers`, `snapshot_at_utc` |
| sec_edgar | `schema` → `icarus.sec_edgar.research_context/1` | `raw_documents_included` | `generated_at` | `accepted_at`, per fact | `status`, `filing_rows`, `fact_rows`, `tickers` |

For this kind, `collection_only: true` is **eligibility metadata in the contract**: it says the document
is collection evidence. It is **not** a requirement that the document contain a `COLLECTION_ONLY` field.
A `RESEARCH_CONTEXT_DOCUMENT` that contains any of `RUN_ID`, `RUN_STATUS`, `RUN_CORE` or
`COLLECTION_ONLY` is rejected as `KIND_CONFUSION`: the producer must never add them, and the consumer
must not accept a document that looks like both kinds.

## 4. Contract v2 (`historical_context` block)

Unchanged keys keep their current values: `mode`, the five authority flags, `truth_contract`,
`source_artifact_blob_required`, `artifact_id_sha256_required`, `packet_projection_verification_required`.
Added:

```json
"contract_version": 2,
"sources": [
  {"id": "robustness_guardian", "kind": "RUN_LATEST", "...": "current fields unchanged"},
  {"id": "provider_collection", "kind": "RESEARCH_CONTEXT_DOCUMENT",
   "path": "automation_intelligence/provider_collection_v1/research_context.json",
   "evidence_status": "HISTORICAL_COLLECTION_EVIDENCE", "research_context_eligible": true,
   "candidate_evidence_eligible": false, "collection_only": true, "raw_payloads_eligible": false,
   "schema_key": "schema_version", "schema_value": "icarus-provider-research-context-v1",
   "raw_exclusion_field": "raw_payloads_included", "collection_clock_field": "snapshot_at_utc",
   "availability_clock": null, "eligibility": null,
   "summary_fields": ["summary", "providers", "snapshot_at_utc"],
   "execution_authorized": false},
  {"id": "sec_edgar", "kind": "RESEARCH_CONTEXT_DOCUMENT",
   "path": "automation_intelligence/cl_lab/sec_edgar_research_context.json",
   "evidence_status": "HISTORICAL_COLLECTION_EVIDENCE", "research_context_eligible": true,
   "candidate_evidence_eligible": false, "collection_only": true, "raw_payloads_eligible": false,
   "schema_key": "schema", "schema_value": "icarus.sec_edgar.research_context/1",
   "raw_exclusion_field": "raw_documents_included", "collection_clock_field": "generated_at",
   "availability_clock": "accepted_at", "eligibility": {"field": "status", "equals": "ok"},
   "summary_fields": ["status", "filing_rows", "fact_rows", "tickers"],
   "execution_authorized": false}
]
```

The existing `causal_timestamp: "accepted_at"` key on `sec_edgar` is replaced by `availability_clock`.

## 5. Packet artifacts

`RUN_LATEST` artifacts are exactly today's `HISTORICAL_LATEST` artifacts, unchanged.

A `RESEARCH_CONTEXT_DOCUMENT` artifact:

```json
{
  "lane": "<source id>",
  "artifact_kind": "RESEARCH_CONTEXT_DOCUMENT",
  "path": "<contract path>",
  "schema_value": "<document's schema_key value>",
  "source_artifact_blob_sha": "<git blob SHA-1 of the document bytes at source_commit>",
  "run_id": null,
  "run_status": null,
  "evidence_status": "HISTORICAL_COLLECTION_EVIDENCE",
  "research_context_eligible": true,
  "candidate_evidence_eligible": false,
  "summary": {
    "fields_present": ["<allowlisted fields present in the document, sorted>"],
    "fields_sha256": "<SHA-256 of canonical JSON of {field: value} for those fields>",
    "fields_bytes": "<UTF-8 length of that canonical JSON>"
  },
  "clocks": {
    "collection_clock_field": "<from contract>",
    "collected_at": "<the document's value of that field, normalized to UTC Z>",
    "availability_clock": "<from contract, or null>"
  },
  "execution_authorized": false,
  "artifact_id": "<SHA-256 of canonical JSON of this object without artifact_id>"
}
```

Canonical JSON is `json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)` in UTF-8,
the form both repositories already use. The packet carries a digest of the allowlisted fields, not the
fields themselves: the consumer reads the values from the document at the pinned blob, so the packet
stays small and cannot disagree with its source.

Artifacts are sorted by `(lane, run_id or "")`, as today.

## 6. Consumer verification for a `RESEARCH_CONTEXT_DOCUMENT` artifact

The consumer has two paths today, and both stay:

- **Packet witness verification:** every artifact in the packet is checked against the document at the
  packet's `source_commit`. All steps below apply. Any failure fails that cycle's historical-packet check
  with the reason code shown, and nothing is credited from that packet.
- **Live ingest from Engine `main`:** each declared document is fetched, validated and journaled. Steps
  5, 6, 7 and 10 apply to it as well. A per-source failure is reported and makes the status `degraded`,
  as today.

1. The `lane` is a declared source, seen once (`UNKNOWN_SOURCE`, `DUPLICATE_SOURCE`). After all
   artifacts, every declared source has one (`MISSING_SOURCE`: no partial ingest).
2. `artifact_kind`, `path`, `evidence_status` and every flag equal the contract and §5
   (`ARTIFACT_FIELD_MISMATCH`); `run_id` and `run_status` are null (`KIND_CONFUSION`).
3. `artifact_id` recomputes (`ARTIFACT_ID_MISMATCH`) and is unique in the packet.
4. Fetch the document at the packet's `source_commit`. Its Git blob SHA equals
   `source_artifact_blob_sha`, both from the API metadata and recomputed from the bytes
   (`BLOB_WITNESS_MISMATCH`).
5. The document is a JSON object whose `schema_key` value equals `schema_value`, in the contract and the
   artifact (`SCHEMA_MISMATCH`).
6. Document authority: `authority == "RESEARCH_CONTEXT_ONLY"`; `execution_authorized`,
   `production_decision_authorized` and `automatic_model_promotion` all `false`; `raw_exclusion_field`
   is `false` (`AUTHORITY_EXPANSION`). No `RUN_*` or `COLLECTION_ONLY` key (`KIND_CONFUSION`).
7. When the source declares `eligibility` (today only `sec_edgar`: `status == "ok"`), the document
   meets it; otherwise it is not eligible research context (`SOURCE_NOT_ELIGIBLE`).
8. Recompute §5 `summary` and `clocks` from the document; they equal the artifact's
   (`PROJECTION_MISMATCH`).
9. Clocks: `collected_at` parses as timezone-aware ISO-8601 and is not later than packet `observed_at` +
   300 s (`FUTURE_SOURCE_CLOCK`). The packet itself keeps the existing 1,800 s age and 300 s future
   bounds (`STALE_PACKET`, `FUTURE_PACKET`). An old `collected_at` is history, not an error; the consumer
   records its age.
10. The journal summary built from `summary_fields` stays within the existing 65,536-byte bound
    (`SUMMARY_TOO_LARGE`). The producer keeps each document's allowlisted fields under 32,768 bytes and
    tests it, so growth fails on the producer side first.

The availability clock is a rule for any later research use, not a packet check: a SEC fact is usable
only from its `accepted_at`; report and period-end dates never grant earlier availability. Provider
context declares no availability clock, so only its collection clock may be used, and nothing in it may
be treated as known before `collected_at`.

## 7. Replay and idempotency

- Today the consumer deduplicates historical rows by the document's Git blob SHA
  (`processed_historical_blob_shas`, last 1,000). v2 keeps that. An unchanged document, whether seen
  again live or through a new packet, writes **zero** new rows. Success means six validated projections,
  not six new rows.
- A changed document (new blob) writes one new row for that source.
- `LIVE_SOURCE_ADVANCED` (main moved past the packet's source commit) stays informational, as today.

## 8. Authority (unchanged)

`mode: RESEARCH_CONTEXT_ONLY`. No candidate evidence, no automatic candidate creation, no model
promotion, no production decision, no execution authority, no raw payloads or raw documents. Foundry and
evaluator are never bypassed. Nothing in v2 widens freshness bounds or changes any schedule.

## 9. Fixtures

Engine `tests/fixtures/federation_v2/` holds **labeled test artifacts**: synthetic documents only, no
vendor rows, never delivery evidence.

- `build_fixtures.py` writes everything below. Its `reference_verify` applies §2 and §6 in order and
  exists to prove that each negative case fails for exactly its declared reason. RUN_LATEST artifacts
  come from today's exporter function (`_historical_artifact`), so legacy fixtures equal today's packets.
  The production exporter, written after approval, must produce the same artifacts from the same
  documents.
- `cases/<name>/` (26 cases), each self-contained:
  - `contract_historical_context.json`: the contract block;
  - `packet_block.json`: the part of the packet J01 governs (`source_commit`, `observed_at`,
    `historical_context_version` when present, `historical_artifacts`);
  - `sources/<path>`: the documents as they exist at that `source_commit`;
  - `expected.json`: `ACCEPT` or one reason code, plus the consumer clock to check with.
- Cases: `accept_legacy4`, `accept_modern6`, and one or more cases for every reason code in §2 and §6,
  including today's contract (`undeclared_modern_contract`), partial five (`missing_source`), invented
  `RUN_PERSISTED` (`artifact_kind_confusion`), and a legacy field added to a new-kind document
  (`document_kind_confusion`).
- `MANIFEST.json`: the SHA-256 of every case file, the generator's SHA-256, each case's expected outcome,
  and the label.

Engine `tests/test_federation_v2_fixtures.py` regenerates the fixtures and requires byte equality, so they
cannot drift. It also checks the manifest hashes and requires every case to end in its declared outcome.

Icarus vendors an exact copy of `cases/` and `MANIFEST.json`, pinned by the Engine commit that holds
them, and checks the manifest hashes before use. Consumer tests map `(source_commit, path)` to the case's
`sources/` bytes and merge the contract block and packet block into the consumer's own full contract and
packet fixtures. No network and no moving `main`.

## 10. Order, acceptance and rollback

1. This specification and the fixtures merge in Engine after Codex approves them.
2. **Consumer (Codex, Icarus):** accepts legacy v1 and complete v2, rejects every negative fixture with
   its reason code. Claude reviews it. The gate remains red, correctly, because the current contract is
   `UNDECLARED_MODERN_CONTRACT`.
3. **Producer (Claude, Engine):** contract becomes v2 (§4); the exporter emits the two
   `RESEARCH_CONTEXT_DOCUMENT` artifacts and `historical_context_version: 2`; the 32,768-byte producer
   guard; its output for the fixture sources equals the fixture packets. Codex reviews it.
4. **Acceptance:**
   - an isolated export-to-import readback at pinned SHAs: Engine exports at commit X, and the Icarus
     consumer at commit Y verifies six projections;
   - then the next genuine scheduled `live-engine-federation-gate` run is green, with six verified
     sources, and its receipts are inspected;
   - a test-only packet is not delivery evidence.
5. **Rollback:** revert the producer PR. That restores the prior contract and exporter, and the gate
   returns to its prior, truthfully red state. The consumer is never weakened to make an incomplete
   packet green.

## 11. Decisions for Codex

1. Packet `schema_version` stays v1, with `historical_context_version: 2` (§2).
2. `subject` for the two new sources (§3).
3. The reason-code names in §2 and §6, which both test suites will assert.
4. Anything in the consumer's current flow this document misdescribes.
