# Atlas: advisory research decision value

Atlas is a separate third worker. Original ChatGPT/Codex and Claude retain their
tasks; ownership and delivered messages are on `coordination/board/atlas.md`.
Both peers accepted this isolated explicit-model scope. This draft changes no
collector, strategy, runtime, UI, scheduler, credentials or spending policy.

The useful question is not "how much information can we collect?" but "which
observation could change a named decision, at what cost, under which assumptions?"
Icarus already has APEX information ranking, CapabilityGraph and TheoryLibrary.
This module supplies a bounded derivation/verification layer, **not** another
governor or a claim of worldwide novelty. See [POTENTIAL.md](POTENTIAL.md) for the
pinned investigation and correction of the initial search-based assessment.

## Implemented

| Component | Behavior | Boundary |
|---|---|---|
| `planner.py` | Minimal alternative prerequisite bundles, shared conditional unblock impact, owner routing | Metadata structure, not economic value or authenticated evidence |
| `contracts.py` / `decision.py` | Explicit finite priors, actions, utilities and outcome likelihoods; posterior action policies; expected decision value and perfect-information bound | Model-conditioned arithmetic, not market likelihood estimation |
| `robust.py` | Declared scenario/cost-range sensitivity, conservative dominance, incomplete-comparison withholding | Supplied scenarios, not statistical confidence intervals |
| `bundles.py` | Joint observations checked against component marginals; complementary/redundant information | Never manufactures independence or adds single-source scores |
| `sequential.py` | Two-observation stop/continue policies and fixed-policy cost range | Explicit joint model and fixed acquisition costs; no research execution |
| `journal.py` | Prospective local recommendation/outcome records, frozen hashes, expiry, predictive scores and unresolved cases | Not the scientific trial ledger, external timestamp attestation or proof of benefit |
| `handoff.py` / `cli.py` | Hashed owner-review package and offline command-line entry points | No APEX/Omnivision adapter, automatic dispatch or integration certification |

Every new evaluator/CLI/journal/handoff output keeps `execution_authorized=false`
and `production_decision_authorized=false`. The original prerequisite-only
prototype remains intact; its output is advisory and execution-false.

Missing required predictive/decision inputs yield `INSUFFICIENT_MODEL` (CLI exits
2). Malformed, nonfinite or unsupported inputs yield `ERROR`, not inferred
probabilities. An explicitly unknown cost remains `UNKNOWN_COST`; it never becomes
zero. Cost intervals must share the declared utility unit, with any conversion
supplied explicitly by the owner. Availability and provenance claims are inputs,
not independently authenticated. Numeric results are finite-model expectations
subject to floating-point rounding, not ICARUS performance estimates.

## Run from the repository root

No dependency beyond Python's standard library is required for these commands.

```sh
python -m research_allocation validate research_allocation/examples/two_state.json
python -m research_allocation evaluate research_allocation/examples/two_state.json
python -m research_allocation compare research_allocation/examples/scenarios.json
python -m research_allocation bundle research_allocation/examples/complementary.json research_allocation/examples/joint.json
python -m research_allocation sequential research_allocation/examples/sequential.json research_allocation/examples/sequential_joint.json first
python -m research_allocation.planner research_allocation/snapshot.json --as-of 2026-10-11T15:42:00Z
```

CLI JSON is printed to stdout; errors are JSON on stderr with a nonzero exit.
Inputs are bounded to four million text characters; finite model/evaluation
budgets and strict schemas reject duplicate keys, boolean numbers and NaN/Inf.
Synthetic examples are labeled synthetic. The original `snapshot.json` is a
manually curated, incomplete historical view of Engine `bb736a89`, **not** the
current live project state or a verified result. Do not silently update it to
erase the provenance of earlier recommendations.

The journal takes an explicit database path. Use a location outside the git
tree; never commit the database/WAL or market/vendor payloads. `register` is the
only command that creates a journal. `report`, `export` and `verify-journal` do
not create a missing database. Export is reviewable JSON text; externally anchor
its head hash if independent timing/integrity matters. A user able to rewrite
the whole local hash chain can rewrite history; this is not tamper-proof storage.

An observation must be after local registration, not future-dated, within the
frozen validity window and in the frozen outcome vocabulary. Actual costs and
overruns remain recorded. Zero-probability observations are model contradictions,
not dropped cases or infinite numbers in JSON. Unresolved/expired recommendations
remain in reports. Brier/log-loss scores assess prediction calibration only;
`decision_benefit_proven` remains false. No counterfactual realized benefit is
inferred from a completed record.
The registered model is an independent snapshot matching its prediction/hash.
New timestamps are sampled under the SQLite write lock, not before waiting for
it. They are local-clock records, not independent durable-time attestations.

## Scientific and integration boundaries

Claude's `cl_lab/trial_ledger.py` / research JSONL ledger remains the single
scientific trial count. Atlas's journal is **not** another experiment registry,
trial count, claims referee or acceptance ledger. Before a recommendation selects
which real hypothesis is tested, its selection and tests need the existing
pre-registration and global-ledger identity, cited by the owner in the supplied
provenance. Atlas does not verify that ledger, launch the trial or certify
compliance. Failure/timeout/unavailable outcomes must be represented explicitly
in a predictive model; the evaluator does not invent them.

No real decision is ready merely because a synthetic model parses. Owner review
must substantiate priors/likelihoods/utilities, evidence identity and availability
clocks, lawful source access, feasibility, uncertainty and costs. Missing source
evidence remains unknown. Runtime adapters require Codex's bounded contract and
path agreement first; none is implemented or approved here. M02 independent
evidence/leakage review remains separate from planning scores.

Still unimplemented: validated real decision packages; APEX/CapabilityGraph/
TheoryLibrary adapters; automatic hypothesis generation/failure-scope learning;
prospective equal-budget comparison against fixed baselines; and demonstrated
improvement in research cost, decision resolution or market outcomes. The module
does not buy data, read market corpora, retest dead strategies or change schedules.

## Verification and handoff

```sh
python -m unittest discover -s research_allocation -p 'test_*.py' -v
python -m pytest tests/test_research_allocation.py -q
```

The existing CI collects `tests/test_research_allocation.py`, a new import-only
TestCase shim suggested by Claude in PR141 review comment6112774338. No workflow
change is needed. The module's original 69 synthetic cases passed through that
shim. Further failing-first regressions established insufficient-model and
authority-flag handling, rare/zero joint-marginal rejection, normalized sequential
arithmetic, final-value cancellation guards, write-lock timestamp ordering,
frozen model consistency and oversized-number error JSON. **84 cases now pass,
with 22 subtests**, including 250 finite models and 200 correlated joint policies
checked against independent Decimal expectation oracles. These are software
tests, not scientific market trials. Scale-aware numeric tolerance is explicit;
the module does not promise arbitrary precision or empirical optimality.

Full repository regression, independent review and exact-head CI are recorded in
[VERIFICATION.md](VERIFICATION.md). A green old prototype PR is not proof of this
larger implementation. Keep [draft PR141](https://github.com/reppiks490/Icarus-engine/pull/141)
under review; no merge, deployment or real research launch is implied.

Knowledge delta is confined to this namespace, the collection shim, Atlas's own
board and immutable peer messages. Shared state, routers, other boards and
scientific policy are not rewritten. Design/contracts/limits: [DESIGN.md](DESIGN.md).

