# Automation Intelligence

Durable output sink for the active automation-intelligence engines and preserved legacy sensor histories.

## Active five-loop topology

The active scheduled engines are:

1. `omega` — fusion/control plane on `main`
2. `macro` — macro/policy sensor on `main`
3. `flow` — microstructure/flow sensor on `main`
4. `aion` — quantitative-science/strategy-intelligence agent on `feature/agent-fabric-apex-v1` while under development
5. `daedalus` — systems assurance/adversarial verification agent on `feature/agent-fabric-apex-v1` while under development

The historical namespaces `fundamental` and `alt_data_crypto` are preserved as legacy sensor/adaptor knowledge. They are not active top-level scheduled loops and must not be mistaken for current specialist runs.

## Clean 1:1 persistence invariant

For every logical engine run:

1. `heartbeat.json` is the only mutable in-progress marker. It may contain `IN_PROGRESS`, recovery, or stranded-run state.
2. `latest.json` always represents the most recent fully persisted run and MUST NOT be used as an in-progress heartbeat.
3. `history/<RUN_ID>.json` is immutable. A completed run has exactly one authoritative history record.
4. Finalization order is: write+verify immutable history -> replace `latest.json` with the exact finalized history payload -> safely update owned state/manifest pointers -> re-fetch and verify.
5. A run may claim `RUN_PERSISTED` only when returned GitHub commit/blob evidence exists and post-write reads prove the same RUN_ID/status. Where applicable, `latest.json` and its matching history record must have identical content/blob identity.
6. A stale heartbeat older than the expected cadence is `STRANDED_IN_PROGRESS`, not a completed run. Preserve it for recovery; never fabricate missing history.
7. Stale-SHA writes must re-fetch/reconcile and retry at most once. An older run must never overwrite a newer completed run.
8. Initialization placeholders such as AION/DAEDALUS `INITIALIZED` state are not completed runs and must never be fused as `RUN_PERSISTED`.

OMEGA additionally maintains `omega_fused_state.json` and the global `manifest.json`. Specialist updates to the global manifest must preserve unrelated entries and use fresh-SHA conflict checks.

## Branch ownership

`main` is authoritative for OMEGA, Macro, Flow, and legacy sensor history. AION/DAEDALUS development state is isolated on `feature/agent-fabric-apex-v1` until explicitly promoted. OMEGA records the branch and commit identity of any AION/DAEDALUS evidence it consumes.

Do not create competing aliases for these namespaces. Do not automatically merge the development branch to `main`.
