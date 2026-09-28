# ICARUS Agent Fabric — Scheduled Build/Persistence Topology

Canonical production code remains in `icarus_engine/agents/` on `main`.

This subtree is the durable scheduled-work control plane for the three agent build loops:
- `robustness_guardian/`
- `alpha_synthesis/`
- `apex_council/`

## Repository strategy

Do not clone production code into separate repositories. One canonical engine prevents implementation drift and competing authority. Each agent instead receives an isolated owned persistence namespace. Scheduled runs may write only their own namespace directly. Any production-code change must be developed on a run-specific feature branch and merged through a verified pull request.

## Per-run persistence contract

One scheduler invocation = one logical run with a deterministic RUN_ID. Each run must:
1. load its prior state and current `main` code;
2. write `heartbeat.json` as IN_PROGRESS only;
3. perform bounded build/research/test work;
4. persist exactly one immutable `history/<RUN_ID>.json`;
5. update `latest.json` and `state.json` only after history verification;
6. re-read GitHub objects and record commit/blob evidence;
7. mark heartbeat RUN_PERSISTED only after all authoritative files verify.

Attempted writes are not persistence proof. No run may grant live-trading authority. `execution_authorized=false` is invariant.

## Ownership

Robustness Guardian owns anti-overfit, leakage, provenance, replay, stress and fragility gates.
Alpha Synthesis owns profitability-oriented shadow research scoring after costs, uncertainty, capacity and diversification.
Apex Council owns multi-agent aggregation, veto/quorum policy, disagreement handling and cross-specialist decision traces.

Existing AION, DAEDALUS, OMEGA, FLOW, MACRO and other namespaces remain separate. These agent-fabric loops must not silently rename, absorb or overwrite them.
