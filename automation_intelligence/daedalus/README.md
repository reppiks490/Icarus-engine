# DAEDALUS PRIME operational state

This namespace stores scheduled DAEDALUS PRIME automation state on the development branch.

Persistence invariant:
- heartbeat.json: mutable in-progress marker only
- history/<RUN_ID>.json: immutable authoritative completed run artifact
- latest.json: newest fully persisted completed run only
- audit/fault/release/provenance/quarantine artifacts are additive and evidence-backed
- stable IDs, replay/idempotency, no fabricated history
- execution_authorized=false

RUN_ID format: daedalus-<UTC_YYYYMMDDTHHMMSSZ>
