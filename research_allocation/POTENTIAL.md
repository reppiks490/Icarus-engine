# Atlas potential: decision-aware experimental design

2026-10-11. Design investigation, not a deployed capability or market result.

## Correction to the initial assessment

The first Atlas pass searched Engine and the account search index and did not find a general planner. A deeper direct tree inspection of Icarus found both prior design AND working components. Index search for information_gain returned no matches despite the file existing. Search absence was not adequate evidence of capability absence.

Reuse these existing components; do not create another scientific governor, theory library or generic capability graph:

| Existing component | Verified scope from code |
|---|---|
| Omnivision v2 spec, sections 12 and 15 | Already proposes information-based budgets and counterfactual failure mining |
| apex/information_gain.py | Ranks supplied observation, experiment and compute estimates |
| apex/kernel.py::propose_experiment | Calls rank_experiments with literal H1/H2, then records proposal |
| apex/self_model.py::CapabilityGraph | Resolves prerequisite availability and detects cycles |
| apex/theory.py::TheoryLibrary | Stores source-pinned theories, transitions and temporal views |
| omnivision/hypotheses.py | Creates hypotheses from latent gaps and source contradictions |
| omnivision/novelty.py | Screens aligned feature pairs for Pearson redundancy |
| Engine cl_lab/explore.py::sample | Deterministic unseen-configuration sampling; historical explored IDs exclude repeats |

Pinned Icarus revision: 0bf06e98c9fbda627116578f8686a178e6837d68.
Canonical source links:
- https://github.com/reppiks490/Icarus/blob/0bf06e98c9fbda627116578f8686a178e6837d68/icarus_engine/apex/information_gain.py
- https://github.com/reppiks490/Icarus/blob/0bf06e98c9fbda627116578f8686a178e6837d68/icarus_engine/apex/kernel.py
- https://github.com/reppiks490/Icarus/blob/0bf06e98c9fbda627116578f8686a178e6837d68/icarus_engine/apex/self_model.py
- https://github.com/reppiks490/Icarus/blob/0bf06e98c9fbda627116578f8686a178e6837d68/icarus_engine/apex/theory.py
- https://github.com/reppiks490/Icarus/blob/0bf06e98c9fbda627116578f8686a178e6837d68/docs/superpowers/specs/2026-09-24-omnivision-epistemic-control-plane-v2-design.md

## Concrete gap, reproduced

potential_probes.json records synthetic metadata probes of the unchanged selected function bodies from the pinned information_gain.py. No runtime server or market trial was executed.

1. rank_experiments uses the number of hypotheses, not their content, and a caller-supplied discrimination scalar. With at least two hypotheses its hypothesis-count multiplier is always 1.
2. rank_observations accepts uncertainty_state but does not read it.
3. Missing acquisition costs default to zero.
4. Missing compute cost defaults to zero, producing about 1e9 for unit opportunity/uncertainty/impact/urgency inputs.

These are limits of the inspected ranking functions, not proof that the whole system loses money or lacks all upstream safeguards. The existing focused tests confirm deterministic ordering under supplied estimates; they do not establish empirical estimate calibration.

The opportunity is the missing derivation and validation of decision value, rather than another score-combining function.

## Proposed capability: select experiments by possible decision change

Each proposed experiment should identify:
- the actual decision and available actions, including defer/do nothing;
- competing mechanisms with immutable versions;
- their predictions for observable outcomes;
- evidence supporting those predictions and priors;
- which outcomes would change the chosen action;
- observation timing, eligibility, source, costs and failure outcomes;
- ownership, preregistration, trial accounting and unseen evaluation requirements.

For an explicitly specified finite model, calculate:
baseline = max over actions of sum over hypotheses p(h) U(action,h).
after = sum over outcomes y of max over actions of sum over hypotheses p(h) p(y|h,experiment) U(action,h).
net decision value = after - baseline - experiment cost.

This is an exact expectation under the supplied model, NOT proof that the model describes markets. Likelihoods, utility units and costs must be justified. Unknown models yield INSUFFICIENT_MODEL, not a made-up probability or zero cost. Acquisition failure is a possible outcome, not discarded data. Deferred action has an explicit utility.

A two-state synthetic example with equal priors, reward 1 for the correct action and cost 0.1 gives:
- perfect distinguishing observation: baseline 0.5, after 1.0, net +0.4;
- identical outcome distributions under both hypotheses: baseline 0.5, after 0.5, net -0.1.
These are toy utility units, not P&L, confidence estimates or ICARUS performance.

## Five deeper opportunities and concrete acceptance criteria

### 1. Mechanism discrimination
Generate an experiment proposal where rival explanations make different predictions. When they predict the same observable distribution, report NOT_IDENTIFIABLE_WITH_THIS_DESIGN. More data from the same uninformative design cannot be credited as resolving that distinction.
Acceptance: known synthetic null, separable and observationally equivalent models; order of hypothesis names changes nothing, predictive likelihoods do change value. Scientific designs remain Claude's responsibility.

### 2. Robust allocation under unknowns
Calculate value over declared plausible model/cost scenarios. Return intervals, sensitivity and incomparable choices rather than falsely precise rankings. Costs must share utility units or remain a separate resource constraint; dollars, seconds and probability points cannot simply be subtracted.
Acceptance: unknown cost never becomes zero; scaling utility and cost together preserves choice; uncertain dominance produces abstention. Sensitivity ranges are not statistical confidence intervals unless derived accordingly.

### 3. Complementary data selection
Model bundles whose members are individually insufficient: e.g. synchronized events plus observable quote state and a causal availability clock. Compare bundle value and collection feasibility, while deduplicating common upstream sources. Existing Atlas prerequisite sets can supply structure; APEX CapabilityGraph remains the capability authority.
Acceptance: a synthetic jointly-informative pair beats redundant single observations only when the stated outcome model supports it. No assumption that extra vendors equal extra independent evidence.

### 4. Scoped learning from failure
Use TheoryLibrary and immutable trial records to distinguish refuted mechanism, inadequate sample, invalid measurement, unavailable input and non-tradeable effect. A failed hypothesis must retain asset/horizon/data/estimator scope. Superseded synthetic findings must not silently become market claims.
Acceptance: a documented data defect invalidates dependent evidence; insufficient data never becomes evidence against a mechanism; an old rejection blocks exact retries and demands a material-change record for reopening.
This is a proposed read-only adapter/schema review with existing owners, not a replacement theory library or a new claims referee.

### 5. Measure whether research selection itself works
Log predicted decision value BEFORE results, then compare actual cost and decision resolution against a fixed baseline allocation policy under equal budgets. Include all selected jobs, failures and unresolved decisions. Count decisions consistently to prevent gaming by splitting tasks.
Acceptance: no claimed improvement until prospective evaluation supports it. Policy changes that affect real research require Claude's preregistration and global trial accounting. The static heuristic, random unseen sampling and dependency-only planner are baselines, not presumed inferior.

## Ownership and delivery boundaries

Atlas can develop an isolated finite-model evaluator, metadata contracts, synthetic acceptance cases and read-only adapter proposals inside research_allocation/**. Original ChatGPT owns runtime integration and architecture-experiment work (E01), Claude owns CL science and coordination tooling. Actual APEX/Omnivision edits, new scientific experiments, research policy changes, integration certification and source acquisition require their specific reservations/review. No takeover.

Proposed order:
1. Owner confirms scope and existing equivalent modules.
2. Implement finite-model evaluator + unknown/cost/unit handling with synthetic cases.
3. Agree a small real decision package using already authorized metadata; remain advisory.
4. Owners approve adapters and prospective comparison protocol.
5. Measure usefulness before any scheduling or budget change.

The original PR141 at15cad18d was a dependency-planning prototype. Its Atlas
continuation now implements the isolated finite-model evaluator, sensitivity,
explicit joint observations, two-stage stopping, offline CLI and local prospective
journal described in README.md and DESIGN.md. It still does not implement the
full real-world program: no runtime adapters, autonomous learning, validated
market likelihoods, acquisition, scientific trial launch or measured improvement
in research/trading outcomes. The original investigation/source pins are preserved.

## Investigation coverage and limits

Read the existing research log, explorer, statistics implementation, Omnivision design and hypothesis module, APEX information-gain, kernel, capability graph, epistemics, theory, reality-gap, evolution, contracts and focused information tests. This is a targeted cross-repository investigation, not an exhaustive code audit. The research log has historical synthetic entries and later real-data corrections; preserve chronology and defer to current canonical state. No dead strategy was re-tested. No active peer code was modified.

