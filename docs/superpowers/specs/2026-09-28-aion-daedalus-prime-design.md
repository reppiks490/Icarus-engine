# AION PRIME + DAEDALUS PRIME — Agent Fabric Apex Design

**Status:** proposed design, implementation not yet started  
**Branch:** `feature/agent-fabric-apex-v1`  
**Repository:** `reppiks490/Icarus-engine`  
**Date:** 2026-09-28  
**Execution authority:** disabled by design until explicit promotion gates are passed

## 1. Purpose

This design introduces two complementary, adversarial, multi-capability AI agents:

- **AION PRIME** — autonomous quantitative research, hypothesis generation, strategy intelligence, model evaluation, and adaptive experiment design.
- **DAEDALUS PRIME** — autonomous systems engineering, verification, reliability, provenance, temporal-integrity auditing, fault injection, recovery, and controlled software evolution.

They replace the *top-level* roles currently occupied by Fundamental Catalyst and Alt-Data Crypto in the five-loop architecture, while preserving their useful domains as specialist sensor/adaptor capabilities that can be consumed by the new fabric. OMEGA, Macro, and Flow remain first-class top-level engines.

The objective is not to claim or manufacture profitability. The objective is to increase the probability that any claimed edge is **real, durable, friction-aware, out-of-sample, regime-aware, and independently reproducible**.

## 2. Non-negotiable constraints inherited from the repository

The design is constrained by current repository evidence:

1. `docs/RESEARCH_LOG.md` records multiple false positives and mechanism failures. Negative results must remain durable and queryable so failed ideas are not rediscovered.
2. `HANDOFF.md` explicitly states that `icarus/` loses money on real data across tested spans and that live feeds were unavailable in the original cloud container. Therefore no agent may infer deployment readiness from synthetic or unreachable-feed evidence.
3. The held-out split beginning **2025-10-01** is treated as protected evaluation data. AION may not repeatedly tune against it.
4. `automation_intelligence/README.md` defines the clean 1:1 persistence invariant:
   - mutable `heartbeat.json`,
   - immutable `history/<RUN_ID>.json`,
   - verified `latest.json`,
   - re-fetch and identity verification,
   - no fabricated history,
   - stale-SHA reconciliation,
   - older runs never overwrite newer completed runs.
5. `execution_authorized=false` remains the default. Neither AION nor DAEDALUS can grant itself trading authority.
6. `README.md` on `main` currently contains unresolved conflict markers; this design does not modify it. All work remains isolated on `feature/agent-fabric-apex-v1` until reviewed.

## 3. Design alternatives considered

### Approach A — two monolithic autonomous agents
Each agent owns a large internal decision loop and direct access to all tools.

**Pros:** fast to prototype.  
**Cons:** difficult to test, reason about, replay, quarantine, or attribute failures. High risk of hidden coupling and self-certification.

### Approach B — many narrow micro-agents
Split every capability into a separate agent.

**Pros:** strong modularity.  
**Cons:** excessive orchestration overhead, brittle handoffs, duplicated context, higher persistence complexity, and harder global reasoning.

### Approach C — two governed agent platforms with typed internal services **(selected)**
AION and DAEDALUS remain the only two new top-level agents, but each is internally modular. Modules communicate through typed contracts and immutable evidence objects. OMEGA remains the external fusion/control plane.

**Why selected:** preserves strong top-level reasoning while keeping every important capability independently testable, replayable, and replaceable.

---

# 4. AION PRIME

## 4.1 Mission

AION answers:

> What appears to work, why might it work, under which regimes, what evidence would falsify it, and what experiment has the highest information value next?

It is not a parameter optimizer. It is an **autonomous quantitative scientist**.

## 4.2 Core capability graph

### A. Hypothesis Foundry
Generates candidate mechanisms from:
- price/returns,
- liquidity sweeps,
- order flow,
- volatility,
- cross-asset state,
- macro,
- rates,
- DXY,
- futures basis/term structure where available,
- fundamentals,
- on-chain/crypto,
- alternative data,
- session structure,
- microstructure,
- existing failure history.

Each hypothesis must declare:
- mechanism,
- expected sign,
- affected instruments,
- expected regime,
- invalidation condition,
- required data,
- confounders,
- look-ahead risks,
- execution sensitivity.

### B. Regime Intelligence Engine
Maintains probabilistic regime state across:
- volatility,
- trend/reversion,
- liquidity,
- correlation,
- macro/rates,
- session,
- event-risk,
- cross-asset stress,
- market-quality,
- structural-break/change-point state.

No single regime classifier is authoritative. Regime confidence is an ensemble with disagreement explicitly exposed.

### C. Experiment Architect
Chooses the next experiment by expected information gain rather than raw backtest profitability.

Supports:
- ablation,
- matched controls,
- negative controls,
- positive controls,
- permutation tests,
- block bootstrap,
- purged/embargoed cross-validation,
- combinatorial purged cross-validation where feasible,
- walk-forward evaluation,
- sensitivity surfaces,
- parameter-neighborhood stability,
- regime-stratified evaluation,
- cross-market transfer,
- time-shift falsification,
- label audits.

### D. Trial Ledger / Multiple-Testing Accountant
Every experiment consumes a unique `trial_id`. Trial families are logged so the system cannot hide failed attempts.

Required outputs:
- total trials,
- effective independent trials estimate,
- selection path,
- Deflated Sharpe Ratio where applicable,
- Probability of Backtest Overfitting where applicable,
- false-discovery correction family,
- holdout touch count,
- holdout contamination risk.

The research process is evaluated, not merely the final champion.

### E. Alpha Lineage Graph
Represents:
`raw observation -> transform -> feature -> hypothesis -> experiment -> model -> strategy proposal -> validation result`

The graph records semantic similarity and statistical redundancy so the system can detect when ten "different" features are merely renamed versions of the same source signal.

### F. Feature Redundancy and Marginal-Value Engine
Measures incremental value conditional on existing features using:
- partial dependence/conditional analysis,
- permutation importance with caution,
- ablation,
- mutual-information redundancy,
- correlation clusters,
- stability across regimes,
- marginal contribution to cost-adjusted performance.

### G. Counterfactual/Falsification Engine
Attempts to break every profitable hypothesis with:
- reversed labels,
- shuffled events,
- lagged inputs,
- placebo sessions,
- alternative execution assumptions,
- tougher friction,
- adverse intrabar ordering,
- reduced fill probability,
- delayed entry,
- synthetic timestamp corruption,
- provider disagreement.

AION cannot promote a hypothesis that has not survived an explicit falsification battery.

### H. Execution-Aware Research Engine
Backtests must include:
- spread,
- commission,
- slippage,
- latency assumptions,
- participation limits,
- fill uncertainty,
- temporary impact,
- persistent/transient impact where size warrants it,
- contract rolls,
- exchange/session constraints.

Gross edge and net edge are stored separately.

### I. Regime Transfer Matrix
Measures each candidate across:
- assets,
- sessions,
- years,
- volatility states,
- macro states,
- liquidity states,
- trend/reversion states.

Promotion depends on *where* the edge works and fails, not one aggregate Sharpe.

### J. Model Tournament
Permits competing classes:
- deterministic rules,
- linear/statistical models,
- tree ensembles,
- state-space/Kalman models,
- hidden-state/regime models,
- temporal models,
- Bayesian models,
- ensembles.

All models receive identical folds, friction assumptions, and trial accounting.

### K. Experiment Memory / Anti-Rediscovery
Consumes and extends `docs/RESEARCH_LOG.md`.

Each failed hypothesis stores:
- what was tried,
- why it failed,
- evidence,
- affected code,
- reusable lesson,
- nearest-neighbor hypotheses to suppress.

### L. Capital-Utility Research Layer
AION evaluates strategies under:
- expectancy,
- Sharpe/Sortino,
- drawdown,
- tail loss,
- turnover,
- capacity,
- cost sensitivity,
- hit rate,
- payoff ratio,
- loss clustering,
- regime dependence,
- capital efficiency.

No optimization target is allowed to collapse into a single scalar.

## 4.3 AION promotion state machine

`IDEA -> SPECIFIED -> TESTED -> FALSIFIED|CANDIDATE -> REPLICATED -> SHADOW -> ELIGIBLE_FOR_REVIEW`

No AION state can become `LIVE` autonomously.

## 4.4 AION durable outputs

Proposed namespace:
`automation_intelligence/aion/`

Files:
- `heartbeat.json`
- `latest.json`
- `history/<RUN_ID>.json`
- `trial_ledger/<TRIAL_ID>.json`
- `hypotheses/<HYPOTHESIS_ID>.json`
- `lineage/<HYPOTHESIS_ID>.json`
- `rejections/<HYPOTHESIS_ID>.json`
- `promotion_queue.json`

All completed records follow the existing clean 1:1 persistence contract.

---

# 5. DAEDALUS PRIME

## 5.1 Mission

DAEDALUS answers:

> Is the system doing what it claims, can the result be independently reproduced, can it recover from failure, and is the evidence strong enough to allow integration?

DAEDALUS is not a coding assistant. It is a **verification, reliability, and controlled-evolution platform**.

## 5.2 Core capability graph

### A. Repository Intelligence Graph
Indexes:
- packages,
- modules,
- public APIs,
- test ownership,
- dependency edges,
- data schemas,
- persistence paths,
- configuration,
- runtime entry points,
- automation namespaces.

Changes must declare affected graph nodes before modification.

### B. Temporal Integrity Auditor
Specifically attacks:
- look-ahead,
- future leakage,
- bar-close/next-bar fill mistakes,
- timestamp timezone drift,
- DST/session errors,
- contract roll leakage,
- continuous-futures contamination,
- pre-window state leakage,
- label leakage,
- post-outcome feature conditioning.

### C. Data Integrity Auditor
Validates:
- source identity,
- provider timestamp semantics,
- staleness,
- missing intervals,
- duplicate events,
- symbol mapping,
- revision behavior,
- point value,
- corporate/futures adjustments,
- unit consistency.

### D. Independent Oracle Generator
Builds reference calculations independent from the implementation being tested.

This prevents:
> implementation bug + test copied from same logic = false confidence.

### E. Metamorphic and Property Test Generator
Examples:
- truncating the future cannot change the past,
- reordering independent events must not change result,
- replaying the same immutable run is idempotent,
- identical history/latest payloads must hash identically,
- increasing transaction cost cannot improve cost-adjusted PnL absent a changed path,
- disabled execution cannot submit orders,
- an older run cannot supersede a newer persisted run.

### F. Mutation Testing Engine
Introduces controlled defects to verify that tests fail when they should.

### G. Fault Injection / Chaos Engine
Injects:
- connector timeouts,
- stale SHA,
- partial writes,
- duplicated events,
- out-of-order events,
- malformed payloads,
- missing providers,
- inconsistent timestamps,
- interrupted runs,
- corrupted cache,
- unavailable live feeds.

### H. Persistence and Replay Governor
Owns certification of:
`heartbeat -> immutable history -> latest -> manifest/state -> re-fetch verification`

It does not own the specialist content. It verifies the durability process.

### I. Provenance Witness
Captures typed evidence edges:
`claim -> source -> extraction -> transform -> decision -> mutation -> verification`

No agent can self-delete its own audit trail.

### J. Cross-Agent Contract Validator
Rejects malformed AION/OMEGA/Macro/Flow messages before ingestion.

Validates:
- schema,
- units,
- timestamps,
- provenance,
- confidence,
- source independence,
- freshness,
- causal-claim labeling.

### K. Failure Attribution Engine
Distinguishes:
- data failure,
- model failure,
- assumption failure,
- orchestration failure,
- connector failure,
- persistence failure,
- code defect,
- evaluation defect.

### L. Safe Evolution Controller
Any self-proposed code change becomes:
`proposal -> isolated branch -> tests -> adversarial review -> shadow result -> human/explicit promotion`

No self-modification is promoted directly to `main`.

### M. Release Qualification Engine
Produces a machine-readable release verdict:
- `REJECT`
- `RESEARCH_ONLY`
- `SHADOW_ONLY`
- `PAPER_ELIGIBLE`
- `REVIEW_ELIGIBLE`

A `LIVE` verdict is intentionally outside DAEDALUS authority.

## 5.3 DAEDALUS durable outputs

Proposed namespace:
`automation_intelligence/daedalus/`

Files:
- `heartbeat.json`
- `latest.json`
- `history/<RUN_ID>.json`
- `audit/<AUDIT_ID>.json`
- `faults/<FAULT_ID>.json`
- `release_gates/<CANDIDATE_ID>.json`
- `provenance/<RUN_ID>.json`
- `quarantine.json`

All completed records follow the clean 1:1 persistence contract.

---

# 6. Cross-agent adversarial protocol

AION and DAEDALUS are explicitly forbidden from certifying themselves.

## 6.1 Challenge flow

1. AION proposes a candidate with evidence.
2. DAEDALUS reconstructs the experiment from lineage.
3. DAEDALUS independently verifies data windows and execution assumptions.
4. DAEDALUS runs adversarial checks.
5. AION receives only the defect/evidence package, not a "hinted" answer.
6. AION may repair the hypothesis.
7. The repaired version receives a new immutable candidate version.
8. OMEGA fuses only versions that satisfy schema and evidence gates.

## 6.2 Disagreement object

Every unresolved disagreement becomes a durable record:

```json
{
  "disagreement_id": "...",
  "candidate_id": "...",
  "aion_claim": "...",
  "daedalus_objection": "...",
  "evidence_for": [],
  "evidence_against": [],
  "severity": "LOW|MEDIUM|HIGH|BLOCKING",
  "status": "OPEN|RESOLVED|REJECTED"
}
```

OMEGA sees the disagreement itself, not only the final conclusion.

## 6.3 Anti-collusion rules

- shared source lineage does not count as independent confirmation;
- same-provider endpoints are one evidence family unless proven independent;
- self-generated labels are tagged as self-generated;
- no agent can lower another agent's severity score;
- only evidence can close a blocking objection;
- history records are immutable.

---

# 7. Integration architecture

## 7.1 Top-level five-loop target

1. `omega`
2. `macro`
3. `flow`
4. `aion`
5. `daedalus`

Fundamental and alt-data crypto become sensor domains, not discarded capabilities.

## 7.2 Sensor/adaptor placement

Proposed future package:
`icarus_intelligence/`

Subpackages:
- `contracts/`
- `aion/`
- `daedalus/`
- `sensors/fundamental/`
- `sensors/crypto/`
- `sensors/macro/`
- `sensors/flow/`
- `provenance/`
- `persistence/`
- `evaluation/`
- `governance/`

Implementation is deferred until this design is approved.

## 7.3 Existing code relationships

- `icarus/`: research/features; treated as evidence source and experimental substrate, not assumed profitable.
- `icarus_engine/`: execution-capable engine and primary runtime; integration is read/shadow-first.
- `research/`: AION writes reproducible experiment scripts/results through reviewed interfaces.
- `tests/`, `tests_engine/`: DAEDALUS extends validation here; existing causality and execution-control tests remain mandatory.
- `automation_intelligence/`: durable operational state and top-level loop outputs.
- OMEGA: consumes typed summaries from AION and DAEDALUS; does not receive unrestricted internal state mutation authority.

---

# 8. Shared typed contracts

## 8.1 Evidence object

Required fields:
- `evidence_id`
- `source_type`
- `source_uri`
- `provider_family`
- `observed_at`
- `event_time`
- `ingested_at`
- `content_hash`
- `transform_chain`
- `freshness_seconds`
- `independence_group`
- `confidence`
- `fact_claim_inference_hypothesis`

## 8.2 Experiment object

Required fields:
- `experiment_id`
- `hypothesis_id`
- `code_commit`
- `data_manifest_hash`
- `train_window`
- `validation_window`
- `holdout_window`
- `holdout_touch_count`
- `trial_family`
- `trial_number`
- `friction_model`
- `execution_model`
- `metrics`
- `pbo`
- `dsr`
- `fdr_family`
- `regime_breakdown`
- `replay_hash`

## 8.3 Candidate object

Required fields:
- `candidate_id`
- `parent_candidate_ids`
- `hypothesis_id`
- `version`
- `expected_mechanism`
- `failure_modes`
- `supported_regimes`
- `unsupported_regimes`
- `net_performance`
- `cost_sensitivity`
- `capacity_estimate`
- `aion_status`
- `daedalus_status`
- `omega_status`
- `execution_authorized=false`

---

# 9. Profitability and robustness gates

"Profitable" means **cost-adjusted and statistically defensible**, not simply positive historical PnL.

A candidate must fail closed if any required gate is unavailable.

Minimum research gates:

1. Positive net expectancy after realistic costs.
2. Positive performance on protected out-of-sample data.
3. Stability across parameter neighborhoods; no needle-point optimum.
4. Regime map identifies both supported and unsupported conditions.
5. No material causality/look-ahead defect.
6. No hidden holdout retuning.
7. Trial count and selection path recorded.
8. DSR/PBO or documented alternative multiple-testing control.
9. Permutation/placebo/null tests appropriate to the hypothesis.
10. Drawdown/tail metrics acceptable independently of Sharpe.
11. Performance not concentrated in a tiny number of trades without explicit justification.
12. Stress at elevated spread/slippage/latency.
13. Cross-period replication.
14. Mechanism explanation consistent with feature sign and behavior.
15. DAEDALUS independent replay matches within tolerance.

Promotion from research to shadow additionally requires:
- deterministic replay identity,
- clean persistence history,
- fault-injection recovery,
- stale-source handling,
- provider degradation behavior,
- quarantine behavior,
- no execution authority escalation.

---

# 10. Metrics

## AION metrics
- net expectancy,
- DSR,
- PBO,
- OOS Sharpe/Sortino,
- Calmar,
- max drawdown,
- tail loss / CVaR,
- turnover,
- cost elasticity,
- capacity,
- hit rate,
- payoff ratio,
- loss clustering,
- regime dispersion,
- parameter stability,
- feature redundancy,
- trial count,
- false-discovery-adjusted significance,
- holdout contamination score.

## DAEDALUS metrics
- replay success rate,
- persistence finalization success,
- recovery success,
- mutation score,
- property-test coverage,
- temporal-integrity defect count,
- provenance completeness,
- connector degradation recovery,
- stale-SHA conflict safety,
- schema conformance,
- mean time to diagnose,
- false certification rate,
- quarantine precision/recall,
- release-gate reproducibility.

---

# 11. Research and engineering references

The design is informed by:

- Bailey et al., **The Probability of Backtest Overfitting** — emphasizes that holdout testing alone does not account for the number of trials and proposes PBO/CSCV concepts.
  https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
- Bailey & López de Prado, **The Deflated Sharpe Ratio** — corrects Sharpe significance for selection bias, non-normality, and repeated trials.
  http://davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- Almgren & Chriss, **Optimal Execution of Portfolio Transactions** — execution should account for market impact and risk/cost trade-offs.
  https://www.worldscientific.com/doi/10.1142/S2382626615500094
- AWS Prescriptive Guidance, **Event Sourcing Pattern** — event history improves auditability, traceability, and replay, but idempotency must be designed explicitly.
  https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/event-sourcing-pattern.html
- AWS Lambda Durable Execution, **Idempotency** — retries and replay require idempotent business logic.
  https://docs.aws.amazon.com/lambda/latest/dg/durable-execution-idempotency.html
- NIST, **AI Risk Management Framework** and **AI Agent Standards Initiative** — lifecycle governance, testing, trustworthiness, interoperability, and risk management.
  https://www.nist.gov/itl/ai-risk-management-framework
  https://www.nist.gov/artificial-intelligence/ai-agent-standards-initiative

These are design inputs, not proof that any trading strategy is profitable.

---

# 12. Implementation sequence

No production code should be written until this spec is reviewed.

After approval:

### Phase 0 — branch hygiene and invariants
- preserve `main`,
- do not repair the conflicted README as part of this feature unless separately authorized,
- freeze current automation namespace state,
- add schema/contract tests first.

### Phase 1 — shared contracts
- evidence,
- experiments,
- candidates,
- disagreements,
- release gates,
- immutable IDs/hashes.

### Phase 2 — persistence kernel
- generic heartbeat/history/latest writer,
- stale-SHA reconcile,
- idempotent replay,
- content-identity verification.

### Phase 3 — DAEDALUS foundation first
- temporal integrity,
- property tests,
- mutation tests,
- fault injection,
- provenance,
- release gate engine.

Rationale: AION should not be allowed to generate high-volume experiments before the audit substrate exists.

### Phase 4 — AION research kernel
- trial ledger,
- hypothesis schema,
- experiment architect,
- falsification engine,
- regime layer,
- evaluation metrics.

### Phase 5 — cross-agent adversarial protocol
- challenge/replay/disagreement objects,
- independent reconstruction,
- OMEGA ingestion contract.

### Phase 6 — sensor migration
- preserve Fundamental and Alt-Data historical state,
- wrap their capabilities as sensor adapters,
- do not delete historical namespaces.

### Phase 7 — shadow operation
- no order submission,
- compare agent judgments to existing system,
- track false positives/false negatives,
- stress persistence and recovery.

### Phase 8 — eligibility review
- only evidence-backed promotion proposals,
- `execution_authorized=false` remains unless separately and explicitly changed outside this agent fabric.

---

# 13. Acceptance criteria for the implementation plan

The implementation plan must specify:
- exact files,
- exact tests,
- expected failures before implementation,
- deterministic replay fixtures,
- migration strategy for `fundamental` and `alt_data_crypto`,
- no destructive history rewrite,
- no direct main-branch mutation,
- rollback procedure,
- OMEGA compatibility,
- CI/reproducibility checks,
- explicit non-goals.

## Non-goals

- guaranteeing profitability,
- autonomous live-trading authorization,
- replacing OMEGA,
- hiding negative research,
- optimizing solely for win rate,
- tuning against the protected holdout,
- merging unresolved README conflicts as part of this work,
- deleting existing historical automation data.

## Final design principle

AION is rewarded for discovering *truth about edge*, including proving an idea does not work.

DAEDALUS is rewarded for preventing false confidence, even when that blocks a profitable-looking result.

The system only improves when those incentives remain adversarial and evidence-bound.
