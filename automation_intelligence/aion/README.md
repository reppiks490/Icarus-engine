# AION PRIME operational state

This namespace stores scheduled AION PRIME automation state on the development branch.

Persistence invariant:
- heartbeat.json: mutable in-progress marker only
- history/<RUN_ID>.json: immutable authoritative completed run artifact
- latest.json: newest fully persisted completed run only
- stable IDs, provenance, replay/idempotency, no fabricated history
- execution_authorized=false

RUN_ID format: aion-<UTC_YYYYMMDDTHHMMSSZ>
