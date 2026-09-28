# Automation Intelligence

Durable output sink for the five market-intelligence engines.

## Clean 1:1 persistence invariant

For every logical engine run:

1. `heartbeat.json` is the only mutable in-progress marker. It may contain `IN_PROGRESS`, recovery, or stranded-run state.
2. `latest.json` always represents the most recent fully persisted run and MUST NOT be used as an in-progress heartbeat.
3. `history/<RUN_ID>.json` is immutable. A completed run has exactly one authoritative history record.
4. Finalization order is: write+verify immutable history -> replace `latest.json` with the exact finalized history payload -> safely update owned state/manifest pointers -> re-fetch and verify.
5. A run may claim `RUN_PERSISTED` only when returned GitHub commit/blob evidence exists and post-write reads prove the same RUN_ID/status. Where applicable, `latest.json` and its matching history record must have identical content/blob identity.
6. A stale heartbeat older than the expected cadence is `STRANDED_IN_PROGRESS`, not a completed run. Preserve it for recovery; never fabricate missing history.
7. Stale-SHA writes must re-fetch/reconcile and retry at most once. An older run must never overwrite a newer completed run.

OMEGA additionally maintains `omega_fused_state.json` and the global `manifest.json`. Specialist updates to the global manifest must preserve unrelated entries and use fresh-SHA conflict checks.

The five existing engine namespaces are `omega`, `macro`, `flow`, `fundamental`, and `alt_data_crypto`. Do not create competing aliases for these namespaces.
