# Explicit-model decision value — implementation contract

This is an offline advisory calculation over owner-supplied or synthetic finite
models. It does not authenticate the assumptions or make research/trading calls.
The accepted scope and scientific boundaries are summarized in README.md.

## Decision rather than information alone

For hidden states `h`, feasible actions `a` (including explicit `defer`), prior
`p(h)`, utility `U(a,h)` and outcome likelihood `p(y|h,e)`:

```text
baseline = max_a sum_h p(h) U(a,h)
after(e) = sum_y max_a sum_h p(h) p(y|h,e) U(a,h)
gross(e) = after(e) - baseline
net(e) = gross(e) - cost(e)
```

The implementation evaluates conditional action policies and checks gross value
against zero and the perfect-information upper bound, with explicit roundoff
tolerance. Entropy reduction is reported separately: informative observations can
have no decision value if no action changes. Utility-shift/scaling invariants and
an independent Decimal oracle test this distinction. Synthetic utility is not P&L.

## Strict inputs and unknowns

`atlas.decision.v1` requires states, normalized prior, action/state utilities,
utility unit, experiments, outcome likelihoods, cost, availability and provenance.
States/actions/outcomes and total evaluation cells are bounded. Each probability
row must sum to one within roundoff tolerance; malformed distributions are never
repaired. Booleans are not numbers. Unknown cost is explicitly `null`, not zero.
Missing required inputs raise `InsufficientModelError`; unknown/invalid fields
remain schema errors. Provenance is labeled synthetic or owner-supplied and is
reported as unverified. Raw-model SHA-256 pins the full supplied assumptions.

Costs are nonnegative intervals in the common utility unit. For gross value `g`,
net range is `[g - high_cost, g - low_cost]`. It is a sensitivity range, not a
confidence interval. An unknown/unavailable alternative prevents a complete
scenario recommendation; no-acquisition has value zero relative to baseline.

## Joint and sequential observations

A joint bundle must explicitly identify component outcome tuples and conditional
joint probabilities. The code validates each marginal against the frozen single
observation model. It rejects duplicate tuples and inconsistent marginals; it
never multiplies marginals to assume independence. All upfront member costs are
charged. Complementarity is derived from the joint decision model, not source or
feature counts.

Marginal agreement uses relative `1e-10` tolerance and zero absolute tolerance:
an impossible component cannot receive even tiny joint mass, and a rare branch
cannot conceal a large relative discrepancy. Every sequential weight and its
conditioning denominator come from the same validated, normalized joint, never
the raw input rows. Conditional distributions are checked to sum to one.

For exactly two observations, the sequential evaluator compares stopping after
the first outcome with paying for the second. It reports conservative/optimistic
cost-endpoint policies separately. The conservative policy's net interval keeps
that policy fixed across costs; it does not splice optimistic outcome choices
into a purported fixed-policy result. Unavailable follow-up permits stopping;
unknown available follow-up cost withholds assessment. No observations are run.
Stop/continue and final preference use scale-aware floating-point tolerances.
Policy gain is checked/clamped to the zero/perfect-information bounds before
subtracting the first cost, so large constant utility cannot turn a tiny cost
into a positive recommendation. The reported tolerance is numerical, not
statistical uncertainty; effects below it are not certified as positive.

## Prospective advisory evidence

The local SQLite journal uses `BEGIN IMMEDIATE`, immutable content identities,
idempotent retries and a SHA-256 hash chain. Recommendations freeze the model,
prediction, chosen observation and expiry before an outcome may be appended.
Different content under the same ID is rejected. Clock reversal, retrospective
or future observations, wrong units, out-of-window results and unknown outcomes
are rejected. Impossible outcomes remain counted as model contradictions.
Registration deep-copies the supplied model before analysis and persists that
same frozen snapshot. New-event timestamps and expiry/future checks are sampled
after the write lock is acquired, immediately before append; lock/scheduler
delay cannot backdate a new record. Identical retries retain their old content
and timestamp, including after expiry. Local clocks remain untrusted externally.

Reports include prediction scores, cost overruns and unresolved/expired records.
They never establish counterfactual realized benefit, independent timestamps or
scientific trial accounting. The chain detects local modification only while its
head is trusted; a whole-chain rewrite is possible without external anchoring.
Database files stay outside git; exports are JSON text. Owner-supplied records
must not be used to bypass Claude's preregistration/global trial ledger.

## Reuse and future integration

The prerequisite prototype remains a structural inspection baseline. APEX owns
runtime information ranking; CapabilityGraph owns prerequisite availability;
TheoryLibrary owns scoped theory history; Claude owns scientific selection and
global trial accounting. Atlas changes none of them. `prepare_handoff` returns
hash-pinned analysis with `OWNER_REVIEW_REQUIRED`, unverified integration/market
evidence and both authority flags false. It is a review package, not an adapter.

Before real integration: agree a bounded contract/path reservation with Codex,
source identity/observation/availability clocks and owner-approved utility model;
pre-register a selection comparison through the existing scientific process;
then evaluate against fixed baselines under equal budgets, retaining failures and
unresolved decisions. No improvement claim is made before that prospective test.
