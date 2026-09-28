# AION work product — H-AION-GOV-001

Status: SPECIFIED / UNIMPLEMENTED
Run: aion-20260928T203422Z
Branch: feature/aion-daedalus-prime-v2
execution_authorized=false

## Highest-value capability
Fail-closed serious-hypothesis preregistration and protected-holdout governance before any further alpha search.

## Root evidence
The active design requires mechanism, sign, markets, regime, invalidation, required data, confounders, leakage risk, execution sensitivity, provenance, failure modes, complete trial-family accounting, and protected holdout beginning 2025-10-01.

Current `CandidateEvidence` carries aggregate metrics but does not itself encode immutable hypothesis/version/code/data-window/trial-family/cost-model/falsification identities. `research_adapter.py` binds study/dataset/baseline hashes and validates a consumed holdout, but this is insufficient as a preregistration contract and risks repeated holdout consumption if callers rerun selection.

## Preregistered governance hypothesis
ID: H-AION-GOV-001
Mechanism: forcing immutable preregistration plus a one-way holdout-consumption ledger reduces researcher degrees of freedom and prevents promotion of evidence that cannot be reconstructed independently.
Expected sign: fewer candidates accepted; higher provenance/replay completeness; no claim of higher PnL.
Markets: market-agnostic; first application MNQ research.
Regime: all.
Invalidation: verifier accepts missing identities, overlapping tune/holdout windows, post-hoc trial-family mutation, or repeated protected-holdout consumption without an explicit new study family.
Required data: hypothesis record, code commit, dataset manifest hash, UTC validation windows, trial-family ID/size, cost-model ID, falsification references, holdout ledger.
Confounders: legacy studies lacking immutable manifests; migrations must be RESEARCH_ONLY rather than silently grandfathered.
Leakage risks: tuning after reading protected holdout; deriving features/normalizers from post-split data; selecting trial family after holdout inspection.
Execution sensitivity: governance-only; no order surface.
Lineage: docs/superpowers/specs/2026-09-28-aion-daedalus-prime-design.md; docs/RESEARCH_LOG.md; icarus_engine/agents/contracts.py; icarus_engine/agents/research_adapter.py.
Expected failure modes: malformed hashes, timezone ambiguity, overlapping windows, duplicate study IDs, mutated trial count, missing negative trials, cost-model substitution, repeated holdout use.

## TDD package
Add an isolated verifier module in a future approved code-write scope. Tests must fail before implementation and cover:
1. missing mechanism/sign/market/regime/invalidation/data/confounder/leakage/execution/provenance/failure-mode fields -> fail closed;
2. malformed code/data hashes -> fail closed;
3. tune_end >= holdout_start -> fail closed;
4. protected holdout start != 2025-10-01 for MNQ governed studies -> fail closed unless explicitly historical RESEARCH_ONLY migration;
5. second consumption of the same protected holdout by the same trial family -> fail closed;
6. changing trial_family_size after registration -> fail closed;
7. cost_model_id substitution -> fail closed;
8. canonical serialization + hash is deterministic;
9. future truncation cannot change preregistered metadata;
10. execution_authorized must remain false.

## Statistical protocol for later empirical candidates
No new empirical trial was run in this cycle. For future candidate studies: predeclare trial family; time-respecting tune/validation with purge/embargo justified from label horizon; use DSR/PBO/FDR or documented alternative; block/bootstrap and permutation/placebo nulls; store gross and net edge separately; stress spread/commission/slippage/latency/capacity; report regime transfer and parameter-neighborhood stability. The protected holdout is not to be repeatedly tuned.

## Current scientific disposition
No AION candidate is advanced. Synthetic results remain machinery evidence only. Prior negative research is durable. REQUEST_TO_DAEDALUS is BLOCKED_NOT_READY until immutable candidate/version/code/data/windows/trial-family/cost/hypothesis/falsification identities exist.
