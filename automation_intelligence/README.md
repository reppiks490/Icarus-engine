# Automation Intelligence

This repository contains durable state for **multiple automation portfolios**. No single scheduler record in the shared global manifest should be assumed to describe every ChatGPT account or automation controller.

## Scheduler isolation

Each active automation portfolio must own a unique writable namespace and a namespaced control-plane record.

### OMEGA / AION / DAEDALUS five-loop stack

Authoritative scheduler mirror for this stack:

`automation_intelligence/omega_stack/control_plane.json`

Writable roots:

- `automation_intelligence/omega_stack/omega/`
- `automation_intelligence/omega_stack/macro/`
- `automation_intelligence/omega_stack/flow/`
- `automation_intelligence/omega_stack/aion/`
- `automation_intelligence/omega_stack/daedalus/`

The legacy `automation_intelligence/omega/`, `macro/`, and `flow/` paths remain historical inputs only for this stack. Other automation portfolios may still use separate legacy or agent-fabric namespaces; they must not write under `omega_stack/`.

The shared `automation_intelligence/manifest.json` is **multi-writer contextual metadata**, not universal scheduler truth. Scheduler-specific loops must not overwrite unrelated topology fields there. Prefer namespaced control-plane files.

## Clean 1:1 persistence invariant

For every logical engine run:

1. `heartbeat.json` is the only mutable in-progress marker.
2. `latest.json` always represents the newest fully persisted completed run and must never be an IN_PROGRESS heartbeat.
3. `history/<RUN_ID>.json` is immutable authoritative completed state.
4. Finalize in order: write heartbeat -> produce final payload -> write immutable history -> re-fetch/verify -> replace latest with the exact same payload -> re-fetch/verify -> mark heartbeat finalized/idle.
5. `RUN_PERSISTED` requires actual write/readback evidence.
6. Stale heartbeats are stranded/recovery evidence, not completed runs.
7. Stale-SHA conflicts require re-fetch/reconcile; an older run must never overwrite newer completed state.
8. Initialization placeholders are not completed runs.
9. No scheduler may silently rewrite another scheduler's namespace or use a shared manifest field as cross-account authority.
10. `execution_authorized=false` remains the default safety invariant for research/automation state.

## Branch ownership for the OMEGA stack

- OMEGA, Macro, Flow operational state: `main`
- AION + DAEDALUS operational/development state: `feature/aion-daedalus-prime-v2`
- Previous agent branch `feature/agent-fabric-apex-v1`: retained as read-only historical development evidence; do not continue new agent work there.

AION/DAEDALUS must compare their development branch to current `main` before code changes. If a target file is stale/diverged, they must use a fresh branch from current main when safely supported or emit an implementation-ready work product instead of overwriting current code.
