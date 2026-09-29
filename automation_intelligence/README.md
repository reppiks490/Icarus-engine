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


## Dual-plane durability (2026-09-29)

The authoritative operational state for the current five-lane OMEGA / Macro / Flow / AION / DAEDALUS portfolio is on branch `automation/omega-native-v2` under:

`automation_intelligence/omega_stack_native_v2/`

The live ChatGPT automation registry plus that branch's `control_plane.json` are scheduler identity authority. A copy of control-plane material on `main` may be historical or stale and must not be promoted to scheduler truth merely because it is on the default branch.

Durability is now dual-plane:

- **ChatGPT AI plane** — the five hourly lanes attempt immutable v4.3 natural liveness receipts under `<lane>/runs/`. Only this plane may use `run_origin=NATURAL_SCHEDULE`.
- **GitHub watchdog plane** — `.github/workflows/automation-durability-watchdog.yml` deterministically audits expected slots and writes only under `automation_intelligence/omega_stack_native_v2/reconciliation/`. It is durability/accounting infrastructure, not an AI worker and not a substitute for missing AI reasoning.
- **Recovery plane** — missed slots are represented as append-only `missed/` + `backlog/` artifacts. Any later reconstruction is provenance-separated as `run_origin=BACKFILL_RECOVERY`; it never becomes a fabricated natural receipt.

The watchdog uses a 12-minute grace window and a 48-hour rolling reconciliation horizon, clamped to the authoritative identity-binding time. It preserves `execution_authorized=false`, never writes `runs/` or `work/`, never force-pushes, and fails closed on identity/control-plane inconsistency.

Verified deployment evidence:
- GitHub Actions run `36628003730` completed successfully.
- Reconciliation commit `f42ea0c1753632056f3b3e2c4efd3017734bc058` was authored by `github-actions[bot]`.
- That commit changed 140 files, all under the reconciliation namespace, and changed no `runs/` or `work/` path.

Origin taxonomy is strict:
- `NATURAL_SCHEDULE` — ChatGPT natural scheduled execution only.
- `GITHUB_WATCHDOG` — deterministic missing/backlog/late-arrival accounting only.
- `BACKFILL_RECOVERY` — later bounded reconstruction from actually available historical evidence only.

