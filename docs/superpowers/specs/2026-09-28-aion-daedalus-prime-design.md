# AION PRIME + DAEDALUS PRIME — Agent Fabric Apex Design

Status: active development contract on feature/agent-fabric-apex-v1.

## AION PRIME
Autonomous quantitative-science and strategy-intelligence agent. Core responsibilities: hypothesis generation, probabilistic regime intelligence, experiment design, immutable trial accounting, multiple-testing control, alpha lineage, redundancy analysis, causal/confounder checks, falsification, execution-cost/impact modeling, cross-period/cross-market transfer, model tournaments, uncertainty calibration, protected-holdout governance, and durable failure memory.

AION promotion state: IDEA -> SPECIFIED -> TESTED -> FALSIFIED|CANDIDATE -> REPLICATED -> SHADOW -> ELIGIBLE_FOR_REVIEW. AION never self-certifies and never grants LIVE authority.

## DAEDALUS PRIME
Autonomous engineering, assurance, provenance, recovery, and adversarial-verification agent. Core responsibilities: repository intelligence, temporal/data integrity auditing, independent oracles, property/metamorphic/mutation tests, fault injection, persistence/replay verification, provenance witnessing, contract/schema validation, root-cause analysis, safe evolution, quarantine, recovery, and release qualification.

DAEDALUS release states: REJECT, RESEARCH_ONLY, SHADOW_ONLY, PAPER_ELIGIBLE, REVIEW_ELIGIBLE. LIVE is outside its authority.

## Shared scientific constraints
- execution_authorized=false
- protected holdout beginning 2025-10-01 must not be repeatedly tuned against
- negative research and failed trials are durable knowledge
- historical PnL alone is never sufficient evidence
- gross edge and net edge are stored separately
- realistic commission, spread, slippage, latency, fill uncertainty, capacity/impact, session, roll, and timestamp semantics must be stress-tested when applicable
- DSR/PBO/FDR or documented alternative multiple-testing control when applicable
- use time-respecting validation, purging/embargo, walk-forward/CSCV when justified, parameter-neighborhood tests, regime stratification, and null/placebo/permutation checks
- AION cannot close DAEDALUS BLOCKING objections without evidence
- DAEDALUS cannot silently rewrite AION hypotheses

## Adversarial handoff
AION candidate -> immutable evidence package -> DAEDALUS independent reconstruction -> adversarial tests/faults -> disagreement object if unresolved -> OMEGA receives both claim and objection.

## Persistence
Both agents use the repository clean 1:1 invariant:
heartbeat.json -> immutable history/<RUN_ID>.json -> verified latest.json -> owned state pointers -> re-fetch identity verification. Never overwrite newer state with older state; stale-SHA conflicts require re-fetch/reconcile; never fabricate missing history.

## Top-level active architecture
OMEGA Fusion Core + Macro Shock Sentinel + Flow Velocity Engine + AION PRIME + DAEDALUS PRIME.
Legacy Fundamental Catalyst and Alt-Data Crypto histories remain preserved as sensor/adaptor knowledge, not deleted.

## Branch policy
Development occurs on feature/agent-fabric-apex-v1 until explicitly promoted. Do not merge to main automatically.
