# OMEGA Stack Isolated Automation Namespace

This directory is the collision-safe operational namespace for this account's five active scheduled ChatGPT automations:

- OMEGA Fusion Core (:00)
- Macro Shock Sentinel (:12)
- Flow Velocity Engine (:24)
- AION PRIME Quant Scientist (:36)
- DAEDALUS PRIME Systems Auditor (:48)

It exists because this repository is also written by other automation stacks. No other scheduler should write inside `automation_intelligence/omega_stack/`.

## Persistence
Each lane uses:
1. `heartbeat.json` for mutable IN_PROGRESS state only.
2. `history/<RUN_ID>.json` as immutable authoritative completed state.
3. `latest.json` only as the newest fully persisted completed run.
4. History must be written and re-read before latest is advanced.
5. Stale-SHA conflicts require re-fetch/reconcile; older runs never overwrite newer runs.
6. `execution_authorized=false` is invariant.

The legacy namespaces under `automation_intelligence/omega`, `macro`, and `flow` remain read-only historical inputs for this stack after migration. The global `automation_intelligence/manifest.json` is shared multi-writer context and is not this stack's scheduler authority.
