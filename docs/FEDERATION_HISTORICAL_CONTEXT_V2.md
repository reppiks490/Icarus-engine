# J01 — Engine → Icarus historical context, version 2

Status: **DRAFT, revision 2, for Codex approval.**

- Revision 2 applies Codex's review of 2026-10-11 (PR #136 comment 6110008926) and records its
  section 11 decisions.
- No producer or consumer code changes until Codex approves this document on its PR thread.
- Editor: Claude, sole editor of the shared contract (agreed 2026-10-11). Reviewer: Codex.
- Changes found during implementation come back here as a reviewed edit.

Repositories: producer `reppiks490/Icarus-engine` (Claude), consumer `reppiks490/Icarus` (Codex).

## 1. What is broken, and how the consumer actually works

**Breakage, with evidence:**

- Engine `automation_intelligence/mcp_interface/icarus_consumer_contract.json` has declared six
  historical sources since 2026-10-08: `78dced8e` added `provider_collection` and `246fd229` added
  `sec_edgar`.
- Icarus `icarus_engine/brain_sync.py` (`_HISTORICAL_CONTEXT_EXPECTED`) accepts exactly four and raises
  `Icarus-engine historical context source set mismatch` (line 419 at `b96833c5`).
- Engine `icarus_engine/interrepo_bridge.py` builds `historical_artifacts` only from control-plane lanes'
  `<worker_root>/latest.json`. The two new sources are not lanes, so the exporter never emits them.
- Icarus `live-engine-federation-gate` failed on every scheduled run checked, 2026-10-09 13:16Z to
  2026-10-10 21:43Z (run `38088740404`), ingesting zero events.

The two new documents are a different kind from the four. They have no `RUN_*` fields and no
`COLLECTION_ONLY`, so today's rule "a collection-only source must carry `COLLECTION_ONLY: true`" cannot
be met without inventing fields. That is forbidden, so version 2 adds an explicit source kind instead.

**The consumer at `b96833c5` has two independent paths.** This document constrains both and changes the
structure of neither.

- **Live ingest** (`brain_sync.py` around line 1462; it runs before packet validation, around line 1601):
  - each declared source document is fetched from Engine `main`, validated and journaled **on its own**;
  - a failing source makes the cycle `degraded`, and rows already journaled for other sources stay;
  - rows are deduplicated by the document's Git blob SHA (`processed_historical_blob_shas`).
- **Packet witness verification** (around line 2026):
  - each artifact in the peer packet is checked against its document at the packet's `source_commit`;
  - this path verifies and records a receipt. It does **not** ingest.

## 2. Versions and how a consumer picks one

| Contract `historical_context` | Packet | Result |
|---|---|---|
| no `contract_version` key; exactly the four legacy sources, each equal to its frozen entry | no `historical_context_version` key; four `HISTORICAL_LATEST` artifacts | **legacy v1**: accepted as today |
| `contract_version` is the integer `2`; exactly the six sources of §3, each equal to its frozen entry | `historical_context_version` is the integer `2`; one authentic artifact per declared source | **v2**: accepted when every check in §6 passes |
| no `contract_version` key and any source set other than the legacy four (**today's state**) | any | `UNDECLARED_MODERN_CONTRACT` |
| `contract_version` present but not the integer `2` (including `true`, `2.0`, `"2"`, `3`) | any | `UNSUPPORTED_CONTRACT_VERSION` |
| `contract_version: 2` with a source set other than the six | any | `CONTRACT_SOURCE_SET_MISMATCH` |
| legacy contract | any `historical_context_version` key, even `1` | `PACKET_VERSION_MISMATCH` |
| `contract_version: 2` | missing, non-integer or other `historical_context_version` | `PACKET_VERSION_MISMATCH` |

Version values are compared as exact JSON integers. `true` never stands for 1, and `2.0` never stands for 2.

A declared six-source contract never downgrades to four because the exporter is incomplete.

**All-or-none applies to packet acceptance:**

- A packet is accepted only when every declared source has exactly one artifact and all of them pass §6.
- The six-source receipt records the packet's validated projections, and it is all-or-none.
- Live-ingest writes are independent of the packet, per source, as described in §1. That stays as it is.

The gate stays red, truthfully, until the producer emits all six.

**Decision (Codex, 2026-10-11):** the packet `schema_version` stays `icarus-peer-intelligence-packet-v1`,
and modern six-source packets add `historical_context_version: 2`.

## 3. The six sources in v2

Every source keeps `research_context_eligible: true`, `candidate_evidence_eligible: false` and
`execution_authorized: false`.

| id | kind | path | evidence_status | collection_only | subject |
|---|---|---|---|---|---|
| robustness_guardian | `RUN_LATEST` | `automation_intelligence/agent_fabric/robustness_guardian/latest.json` | HISTORICAL_RESEARCH_EVIDENCE | false | aegis |
| alpha_synthesis | `RUN_LATEST` | `automation_intelligence/agent_fabric/alpha_synthesis/latest.json` | HISTORICAL_RESEARCH_EVIDENCE | false | aion |
| apex_council | `RUN_LATEST` | `automation_intelligence/agent_fabric/apex_council/latest.json` | HISTORICAL_RESEARCH_EVIDENCE | false | apex-omega |
| flow_microstructure | `RUN_LATEST` | `automation_intelligence/flow/latest.json` | HISTORICAL_COLLECTION_EVIDENCE | true | data |
| provider_collection | `RESEARCH_CONTEXT_DOCUMENT` | `automation_intelligence/provider_collection_v1/research_context.json` | HISTORICAL_COLLECTION_EVIDENCE | true | data |
| sec_edgar | `RESEARCH_CONTEXT_DOCUMENT` | `automation_intelligence/cl_lab/sec_edgar_research_context.json` | HISTORICAL_COLLECTION_EVIDENCE | true | data |

**Decision (Codex):** both new sources use the existing native subject `data`. No alias is added.

`RUN_LATEST` sources keep their current `summary_fields` byte for byte, as in
`_HISTORICAL_CONTEXT_EXPECTED` at Icarus `b96833c5`. They also keep every current production guard:

- `execution_authorized` false;
- no `RUN_CORE` or trading execution authority;
- `COLLECTION_ONLY: true` on the collection source `flow_microstructure`;
- `RUN_STATUS == RUN_PERSISTED` for an eligible projection.

`RESEARCH_CONTEXT_DOCUMENT` sources:

| id | schema_key → schema_value | raw_exclusion_field (must be `false`) | collection_clock_field | availability_clock | eligibility | summary_fields |
|---|---|---|---|---|---|---|
| provider_collection | `schema_version` → `icarus-provider-research-context-v1` | `raw_payloads_included` | `snapshot_at_utc` | `null` (collection clock only) | `null` | `summary`, `providers`, `snapshot_at_utc` |
| sec_edgar | `schema` → `icarus.sec_edgar.research_context/1` | `raw_documents_included` | `generated_at` | `accepted_at`, per fact | `{"field": "status", "equals": "ok"}` | `status`, `filing_rows`, `fact_rows`, `tickers` |

For this kind, `collection_only: true` is **eligibility metadata in the contract**. It is not a field the
document must contain.

**Forbidden keys on the new kind:** a `RESEARCH_CONTEXT_DOCUMENT` that contains `COLLECTION_ONLY`, or
**any** key starting with `RUN_`, is rejected as `KIND_CONFUSION`. The producer never adds them.

## 4. Contract v2 (`historical_context` block)

**Frozen head.** These keys must equal today's values exactly:

- `mode`;
- the five authority flags;
- the six `truth_contract` invariants;
- `source_artifact_blob_required`, `artifact_id_sha256_required` and
  `packet_projection_verification_required`.

`contract_version: 2` is added. Weakening any head value is `AUTHORITY_EXPANSION`, because a weaker
verification requirement widens what is accepted.

**Frozen sources.** Each source entry must equal its frozen entry exactly:

- the four legacy entries as today, plus `"kind": "RUN_LATEST"`;
- the two new entries as below, where `causal_timestamp` is replaced by `availability_clock`.

An entry that differs in any field is `CONTRACT_SOURCE_SET_MISMATCH`. That includes removing an
`eligibility` rule. The exception is a widening flag (`candidate_evidence_eligible`,
`execution_authorized` or `raw_payloads_eligible` set to true), which is `AUTHORITY_EXPANSION`.

```json
"contract_version": 2,
"sources": [
  {"id": "robustness_guardian", "kind": "RUN_LATEST", "...": "today's fields unchanged"},
  {"id": "provider_collection", "kind": "RESEARCH_CONTEXT_DOCUMENT",
   "path": "automation_intelligence/provider_collection_v1/research_context.json",
   "evidence_status": "HISTORICAL_COLLECTION_EVIDENCE", "research_context_eligible": true,
   "candidate_evidence_eligible": false, "collection_only": true, "raw_payloads_eligible": false,
   "schema_key": "schema_version", "schema_value": "icarus-provider-research-context-v1",
   "raw_exclusion_field": "raw_payloads_included", "collection_clock_field": "snapshot_at_utc",
   "availability_clock": null, "eligibility": null,
   "summary_fields": ["summary", "providers", "snapshot_at_utc"], "execution_authorized": false},
  {"id": "sec_edgar", "kind": "RESEARCH_CONTEXT_DOCUMENT",
   "path": "automation_intelligence/cl_lab/sec_edgar_research_context.json",
   "evidence_status": "HISTORICAL_COLLECTION_EVIDENCE", "research_context_eligible": true,
   "candidate_evidence_eligible": false, "collection_only": true, "raw_payloads_eligible": false,
   "schema_key": "schema", "schema_value": "icarus.sec_edgar.research_context/1",
   "raw_exclusion_field": "raw_documents_included", "collection_clock_field": "generated_at",
   "availability_clock": "accepted_at", "eligibility": {"field": "status", "equals": "ok"},
   "summary_fields": ["status", "filing_rows", "fact_rows", "tickers"], "execution_authorized": false}
]
```

## 5. Packet artifacts

`RUN_LATEST` artifacts are exactly today's `HISTORICAL_LATEST` artifacts, unchanged.

A `RESEARCH_CONTEXT_DOCUMENT` artifact has **exactly** these fields, no more and no fewer:

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

Canonical JSON is `json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)` in UTF-8.
The packet carries a digest of the allowlisted fields, not the fields themselves: the consumer reads the
values from the document at the pinned blob. Artifacts are sorted by `(lane, run_id or "")`, as today.

## 6. Checks, in frozen order

The first failing check gives the reason code. Missing, naive and malformed values are deterministic
rejections, never exceptions. A clock is valid only as a timezone-aware ISO-8601 string.

**Contract (both paths):**

| Step | Check | Code |
|---|---|---|
| C1 | `contract_version` absent, or the integer `2` | `UNSUPPORTED_CONTRACT_VERSION` |
| C2 | source ids: exactly the legacy four (no version) | `UNDECLARED_MODERN_CONTRACT` |
| C2 | source ids: exactly the six (v2); any malformed `sources` | `CONTRACT_SOURCE_SET_MISMATCH` |
| C3 | frozen head (§4) | `AUTHORITY_EXPANSION` |
| C4 | every source equals its frozen entry (§4); a widening flag is `AUTHORITY_EXPANSION` | `CONTRACT_SOURCE_SET_MISMATCH` |

**Packet acceptance:**

| Step | Check | Code |
|---|---|---|
| P1 | packet version matches the contract (§2) | `PACKET_VERSION_MISMATCH` |
| P2 | `observed_at` is a valid clock | `INVALID_PACKET_CLOCK` |
| P3 | packet age ≤ 1,800 s and not more than 300 s in the future | `STALE_PACKET`, `FUTURE_PACKET` |
| P4 | each artifact: an object with a declared, unseen `lane` and a unique `artifact_id`, then the per-kind steps below | `ARTIFACT_FIELD_MISMATCH`, `UNKNOWN_SOURCE`, `DUPLICATE_SOURCE`, `ARTIFACT_ID_MISMATCH` |
| P5 | every declared source has an artifact | `MISSING_SOURCE` |

**Per artifact, `RESEARCH_CONTEXT_DOCUMENT`:**

| Step | Check | Code |
|---|---|---|
| D1 | exactly the §5 field set | `ARTIFACT_FIELD_MISMATCH` |
| D2 | `artifact_kind`, `path`, `evidence_status`, `research_context_eligible: true` | `ARTIFACT_FIELD_MISMATCH` |
| D3 | `candidate_evidence_eligible` and `execution_authorized` both false | `AUTHORITY_EXPANSION` |
| D4 | `run_id` and `run_status` null | `KIND_CONFUSION` |
| D5 | `artifact_id` recomputes | `ARTIFACT_ID_MISMATCH` |
| D6 | the document at `source_commit` exists, and its Git blob SHA equals `source_artifact_blob_sha` (API metadata and recomputed bytes) | `BLOB_WITNESS_MISMATCH` |
| D7 | the document parses as a JSON object; its `schema_key` value and the artifact's `schema_value` both equal the contract's | `SCHEMA_MISMATCH` |
| D8 | `authority == "RESEARCH_CONTEXT_ONLY"`; `execution_authorized`, `production_decision_authorized`, `automatic_model_promotion` and `raw_exclusion_field` all false | `AUTHORITY_EXPANSION` |
| D9 | no `RUN_*` key and no `COLLECTION_ONLY` | `KIND_CONFUSION` |
| D10 | the `eligibility` rule, when declared | `SOURCE_NOT_ELIGIBLE` |
| D11 | the collection clock is valid | `INVALID_SOURCE_CLOCK` |
| D12 | the recomputed §5 `summary` and `clocks` equal the artifact's | `PROJECTION_MISMATCH` |
| D13 | `collected_at` ≤ packet `observed_at` + 300 s | `FUTURE_SOURCE_CLOCK` |
| D14 | the canonical JSON of the allowlisted fields ≤ 65,536 bytes | `SUMMARY_TOO_LARGE` |

**Per artifact, `RUN_LATEST`:**

| Step | Check | Code |
|---|---|---|
| L1 | `artifact_kind == HISTORICAL_LATEST` and the contract path | `ARTIFACT_FIELD_MISMATCH` |
| L2 | `candidate_evidence_eligible` and `execution_authorized` both false | `AUTHORITY_EXPANSION` |
| L3 | `artifact_id` recomputes | `ARTIFACT_ID_MISMATCH` |
| L4 | blob witness, as D6 | `BLOB_WITNESS_MISMATCH` |
| L5 | the document parses as a JSON object | `SCHEMA_MISMATCH` |
| L6 | no execution or trading authority in the document or its `RUN_CORE` | `AUTHORITY_EXPANSION` |
| L6 | a collection-only source carries `COLLECTION_ONLY: true` | `SOURCE_NOT_ELIGIBLE` |
| L7 | the artifact equals today's projection of the document | `PROJECTION_MISMATCH` |
| L8 | `run_status == RUN_PERSISTED`, the contract's `evidence_status`, `research_context_eligible: true` | `SOURCE_NOT_ELIGIBLE` |

**Live ingest.** After C1–C4, each declared source gets its own outcome:

- `RESEARCH_CONTEXT_DOCUMENT`: D7–D11; then `collected_at` ≤ live sync clock + 300 s
  (`FUTURE_SOURCE_CLOCK`); then D14.
- `RUN_LATEST`: L5–L6.
- A missing document is `MISSING_SOURCE`.

An old `collected_at` is history, not an error: old sources stay eligible, and the consumer records their
age. A source that fails is not journaled. Other sources are unaffected (§1).

**Availability, for later research use:**

- A SEC fact is usable only from its `accepted_at`; report and period-end dates never grant earlier
  availability.
- Provider context declares no availability clock. Only its collection clock applies, and nothing in it
  is known before `collected_at`.

**Decision (Codex):** the 21 reason codes above are frozen, with their scalar types and this precedence:
the original nineteen plus `INVALID_SOURCE_CLOCK` and `INVALID_PACKET_CLOCK`. Malformed JSON is
`SCHEMA_MISMATCH`.

## 7. Replay, deduplication and what success means

- **Live journal rows** are deduplicated by the document's Git blob SHA. The consumer keeps the processed
  set as `sorted(processed)[-1000:]`, the lexicographically last 1,000 SHAs. That bounds memory. It is not
  a chronological LRU and not an unbounded replay guarantee.
- An unchanged document writes **zero** new rows. A changed document (new blob) writes one row for that
  source.
- **Success** for a scheduled six-source acceptance means six validated packet projections in the receipt.
  It never requires six newly inserted journal rows.
- `LIVE_SOURCE_ADVANCED` (main moved past the packet's source commit) stays informational, as today.

## 8. Authority (unchanged)

- `mode: RESEARCH_CONTEXT_ONLY`.
- Not allowed: candidate evidence, automatic candidate creation, model promotion, a production decision,
  execution authority, raw payloads or raw documents.
- Foundry and evaluator are never bypassed.
- Limits stay: packet age 1,800 s, future bound 300 s, finite bounded projections, every authority flag
  false.
- Nothing here changes a schedule.

## 9. Fixtures

Engine `tests/fixtures/federation_v2/` holds **labeled test artifacts**: synthetic documents only, no
vendor rows, never delivery evidence.

- **`build_fixtures.py`** writes everything below. Its reference checks apply §6 in its frozen order:
  `reference_verify` for packet acceptance and `reference_live_verify` for live ingest. They exist to prove
  that each negative case fails for exactly its declared reason. RUN_LATEST artifacts come from today's
  exporter function (`_historical_artifact`). The production exporter, written after approval, must produce
  the same artifacts from the same documents.
- **`cases/<name>/`** holds 51 cases: 45 packet cases and 6 live-ingest cases. Each is self-contained:
  - `contract_historical_context.json`;
  - `packet_block.json` (packet cases only);
  - `sources/<path>`;
  - `expected.json`: `"path": "packet"` with one `expect` and `consumer_now`, or `"path": "live"` with
    `expect_by_source` and `live_now`.
- **Coverage:** both accept shapes, every reason code on the packet path, and the live path's clock,
  schema, eligibility and contract rejections. The cases include today's contract, partial five, an
  invented `RUN_PERSISTED`, legacy and `RUN_*` keys on new-kind documents, weakened head and witness
  flags, a removed eligibility rule, `true` and `2.0` versions, missing and extra artifact fields, a legacy
  flow source without `COLLECTION_ONLY`, a `FAILED` run status, and malformed JSON.
- **`MANIFEST.json`:** the SHA-256 of every case file, the generator's SHA-256, each case's expected
  outcome, and the label.

Engine `tests/test_federation_v2_fixtures.py` regenerates the fixtures and requires byte equality. It
also checks the manifest, requires every case to end in its declared outcome, and checks that malformed
inputs reject instead of raising.

Icarus vendors an exact copy of `cases/` and `MANIFEST.json`, pinned by the Engine commit that holds them,
and checks the manifest hashes before use. Consumer tests:

- map `(source_commit, path)` to the case's `sources/` bytes;
- merge the contract block and the packet block into the consumer's own full fixtures;
- run live cases through the live-ingest path.

No network and no moving `main`.

## 10. Order, acceptance and rollback

1. This specification and the fixtures merge in Engine after Codex approves them.
2. **Consumer (Codex, Icarus):** legacy v1 and complete v2 pass, and every negative fixture is rejected
   with its reason code on its path. Claude reviews it. The gate remains red, correctly: the current
   contract is `UNDECLARED_MODERN_CONTRACT`.
3. **Producer (Claude, Engine):**
   - the contract becomes v2 (§4);
   - the exporter emits the two `RESEARCH_CONTEXT_DOCUMENT` artifacts and
     `historical_context_version: 2`;
   - the producer keeps each document's allowlisted fields under 32,768 bytes, and tests it;
   - its output for the fixture sources equals the fixture packets.

   Codex reviews it.
4. **Acceptance:**
   - an isolated export-to-import readback at pinned SHAs;
   - then the next genuine scheduled `live-engine-federation-gate` run with a six-source verified packet
     receipt, whose receipts are inspected.

   Zero new journal rows is valid when the documents did not change (§7). A test-only packet is not
   delivery evidence.
5. **Rollback:** revert the producer PR. That restores the prior contract and exporter and the gate's prior,
   truthfully red state. The consumer is never weakened to make an incomplete packet green.

## 11. Decisions (agreed by Codex on 2026-10-11)

1. The packet `schema_version` stays v1; modern packets add `historical_context_version: 2`; absent means
   legacy only under the legacy contract.
2. The subject of both new sources is `data`.
3. 21 frozen reason codes, with integer-only version types and the §6 precedence.
4. The consumer's real flow (live ingest before and independent of packet verification; a lexicographic
   1,000-entry blob cache) is described in §1 and §7.
