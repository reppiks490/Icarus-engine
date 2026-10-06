# External Data Fabric Expansion — Implementation Plan

**Date:** 2026-10-06
**Scope:** `reppiks490/Icarus-engine` provider/data-plane implementation + `reppiks490/Icarus` secret-bearing orchestration
**Authority:** research/data only; no broker or production-execution authority

## Architecture

- `Icarus-engine` owns provider adapters, endpoint catalog/probing, normalization, point-in-time semantics, storage contracts, feature packets, manifests, and tests.
- canonical `Icarus` owns scheduled/manual GitHub Actions that inject repository secrets and execute the engine collectors at a pinned engine revision.
- Bronze/raw data remains outside normal git history (Actions cache/artifacts or approved external storage).
- Silver normalized data is partitioned Parquet when `pyarrow` is available, with deterministic gzipped JSONL fallback for portability.
- Gold output is compact, auditable JSON feature/coverage packets suitable for federation into canonical ICARUS.
- Every provider run writes an entitlement/coverage manifest; inaccessible endpoints are explicitly recorded instead of silently omitted.
- SEC EDGAR remains dormant until `SEC_USER_AGENT` is configured. No other provider depends on it.

## Point-in-time record contract

Every normalized observation must expose these fields, allowing null only where the source genuinely has no such timestamp/identity:

`provider`, `dataset`, `endpoint`, `entity`, `event_time`, `publication_time`, `availability_time`, `retrieval_time`, `revision`, `latency_class`, `quality_state`, `source_record_id`, `raw_content_hash`, `license_class`, `payload`.

Rules:

1. `availability_time` is the earliest time ICARUS could legally/causally have observed the record; descriptive report periods never substitute for it.
2. Raw content is hashed before normalization.
3. Secrets are never written to manifests, errors, cache paths, query logs, or git.
4. A provider failure is isolated; other providers continue and the manifest records the failure.
5. Backfills checkpoint after pages/dates so reruns resume rather than restart.

## Task 1 — Core contracts and storage

**Engine files**
- `cl_lab/data_fabric/__init__.py`
- `cl_lab/data_fabric/contracts.py`
- `cl_lab/data_fabric/storage.py`
- `tests_cl/test_data_fabric_contracts.py`

**TDD sequence**
1. Add failing tests for required observation fields, UTC normalization, raw hash stability, secret redaction, deterministic record IDs, partition selection, and atomic manifest writes.
2. Run only `tests_cl/test_data_fabric_contracts.py`; confirm failure because modules do not exist.
3. Implement minimal stdlib-first contracts/storage.
4. Run tests to green.
5. Refactor without changing behavior.

**Storage behavior**
- `write_bronze`: gzip exact bytes/JSON with SHA-256 metadata.
- `write_silver`: Parquet if `pyarrow` is installed; otherwise deterministic `.jsonl.gz`.
- `write_manifest`: atomic JSON replacement.
- never place raw/licensed rows under committed `automation_intelligence/` paths.

## Task 2 — Intrinio catalog + entitlement probe

**Engine files**
- `cl_lab/providers/__init__.py`
- `cl_lab/providers/intrinio.py`
- `tests_cl/test_intrinio_provider.py`

**Source of truth**
- Official Intrinio Python SDK repository/README, which currently identifies API v2 and publishes a method/HTTP-path table.
- Runtime catalog fetch records source URL, SDK/API version when discoverable, retrieval time, and catalog SHA-256.
- Parser rejects suspiciously small/empty catalogs rather than treating them as complete.

**Probe contract**
Every catalog endpoint receives one manifest row with one of:
- `ACCESSIBLE`
- `RESTRICTED`
- `RATE_LIMITED`
- `AUTH_ERROR`
- `INVALID_PARAMETERS`
- `PROBE_UNRESOLVED`
- `SERVER_ERROR`
- `NETWORK_ERROR`

Path placeholders are resolved from a safe fixture registry (`AAPL`, `USCOMP`, representative option contract, dates, IDs discovered from earlier accessible calls). Endpoints that cannot be safely parameterized are still represented as `PROBE_UNRESOLVED`; they are never dropped.

**Backfill behavior**
- Accessible GET endpoints with recognized pagination/date parameters are paged to the configured historical floor or provider exhaustion.
- `next_page` cursors are checkpointed.
- 403/429 handling uses bounded backoff and terminates the affected lane without burning the entire trial budget.
- Per-endpoint manifest records calls, records, first/last event date where derivable, page count, schema hash, cursor/checkpoint, and access class.

**TDD sequence**
1. Tests for parsing the official SDK endpoint table, placeholder resolution, auth redaction, HTTP classification, cursor paging, checkpoint resume, and explicit unresolved rows.
2. Confirm red.
3. Implement minimal client/catalog/prober/backfiller.
4. Confirm green.

## Task 3 — Unusual Whales REST + bounded stream collector

**Engine files**
- `cl_lab/providers/unusual_whales.py`
- `tests_cl/test_unusual_whales_provider.py`

**REST families initially encoded from the provider's published API documentation**
- option trades / historical full tape metadata
- stock screener
- market/ETF/sector tide
- GEX levels and Greek exposure by ticker/strike/expiry
- Greek flow
- OI changes
- dark-pool trades/price levels
- FLEX contracts/history
- options chain/contract history
- IV/volatility state
- short data
- institutional/13F
- congressional and insider activity
- fundamentals, earnings and analyst context

Each family is independently entitlement-probed; inaccessible families remain visible in the manifest.

**Streaming**
- WebSocket URL and join protocol follow Unusual Whales' published build recipe.
- bounded capture only; GitHub Actions is not treated as a permanent websocket host.
- subscribe only to configured channels; wait for `status: ok` before live classification.
- reconnect with exponential backoff; rejoin channels after reconnect.
- buffer records and flush by count/time threshold.
- persist sequence/checkpoint metadata and run REST gap-fill after interruption where a REST equivalent exists.
- no per-message direct disk writes.

**TDD sequence**
1. Tests for endpoint-family completeness, HTTP classification, safe URL construction, pagination/date walking, channel join acknowledgement, reconnect/rejoin, buffer flush, checkpoint resume, and malformed-message isolation.
2. Confirm red.
3. Implement.
4. Confirm green.

## Task 4 — Provider orchestrator + compact gold packet

**Engine files**
- `cl_lab/data_fabric/orchestrator.py`
- `tools/collect_external_provider_data.py`
- `tests_cl/test_external_provider_orchestrator.py`

**Behavior**
- CLI modes: `probe`, `backfill`, `incremental`, `stream`.
- Provider selection: `intrinio`, `unusual_whales`, or `all`.
- provider failures are isolated and reflected in final status.
- output manifest contains provider catalog hashes, access coverage, temporal coverage, freshness, raw/silver byte counts, errors, and checkpoint paths.
- Gold packet contains only compact derived/coverage features and never raw licensed rows.
- process exits nonzero only for integrity failures (for example malformed/incomplete catalog), not merely because a trial does not license a product family.

## Task 5 — Canonical Icarus secret-bearing workflows

**Canonical files**
- `.github/workflows/external-provider-entitlement.yml`
- `.github/workflows/external-provider-backfill.yml`
- `.github/workflows/external-provider-incremental.yml`
- `.github/workflows/external-provider-stream-capture.yml`
- `integration/external_data_fabric/README.md`

**Workflow contract**
- run only on `workflow_dispatch`/schedule, never expose secrets to pull requests.
- check out canonical `Icarus` and a pinned `Icarus-engine` revision into a separate path.
- inject only named environment variables such as `INTRINIO_API_KEY` and `UNUSUAL_WHALES_API_TOKEN`; never echo them.
- install data-plane-only dependencies (`pytest`, `pyarrow`, `duckdb`, websocket client as required).
- restore/save provider caches with provider/schema version in cache keys.
- upload Bronze/Silver datasets as workflow artifacts with bounded retention.
- commit only compact entitlement/coverage/handoff manifests if desired; raw provider payloads never enter git.
- backfill workflow uses manual controls for provider, historical floor, maximum calls/runtime, and resume checkpoint.
- stream workflow is explicitly time-bounded and performs final checkpoint/manifest upload in `always()` cleanup.

## Task 6 — Cross-repo federation handoff

**Engine files**
- `integration/EXTERNAL_DATA_FABRIC_HANDOFF.json` generated/updated by release step.

**Canonical files**
- `tests_engine/test_external_data_fabric_handoff.py`
- optional consumer code only after the handoff contract is green.

Contract pins producer revision, schema version, compact artifact hashes, authority=`RESEARCH`, and explicit limitations. Revision drift invalidates the handoff until regenerated.

## Task 7 — Existing Quiver exports

After the API collectors are green, ingest user-provided Quiver exports through the same observation contract. Preserve the original release/disclosure timestamps for Congress/lobbying/contracts/patents and file timestamps/source metadata for WallStreetBets/fear-greed exports. Do not manufacture timestamps unavailable in the source files.

## Task 8 — Verification and review

1. Run focused engine tests for all new modules.
2. Run existing `tests_cl` relevant to feeds plus SEC fixtures without live SEC access.
3. Run provider CLI with no credentials; expected result is clean `unconfigured`/dormant status with no secret requirement.
4. Push feature branches and run workflow syntax/contract tests.
5. Trigger entitlement workflow with configured Intrinio/UW secrets; inspect manifest for 100% catalog accounting (`accessible + restricted + unresolved/error == catalog_total`).
6. Trigger bounded backfill; confirm resume from checkpoint and artifact persistence.
7. Trigger bounded UW stream capture; confirm join acknowledgements, buffered writes, final checkpoint and gap-fill behavior.
8. Invoke code review and verification-before-completion before proposing merge.

## Rollback

All implementation remains on feature branches until verified. Disabling or deleting the new canonical workflows returns the system to the pre-change state; no existing provider/feed workflow is replaced during the first rollout.

## Deferred SEC step

`cl_lab/feeds/sec_edgar.py` and its workflow remain unchanged. `SEC_USER_AGENT` will be explained and configured later at the owner's request.