# Operation-specific collection receipts — 2026-10-18

Current-main port base: Engine `b0555a56fa6c4b10a50e04461a625ec5a3d852cf`. The field format was reviewed against
Icarus `20870219a12f065915d88aaaae58946770728e9e` and its existing discovery-registry consumer. This is a bounded receipt-schema
convergence change, not provider acquisition or strategy qualification.

## Result

Each normal provider entry now has `verified_operations`, a sorted, unique list of exact operation
IDs successfully attempted in that cycle. An ID is included only after response and pagination
checks succeed and the collector recognizes rows containing a populated value. Empty lists,
empty/null-only placeholders, blank strings and nonfinite numeric-only rows do not establish
operation access. Numeric zero remains valid content. Response-supplied operation claims are
ignored; identity comes from the attempted catalog job and must match the provider namespace.
Nested objects and lists must contain a populated JSON scalar leaf within 32 levels. Empty,
null-only, blank and nonfinite-only nested structures remain unverified; zero and boolean leaves
remain meaningful. A leaf beyond that traversal limit cannot establish access.

If any page or asset attempt for an operation fails in that cycle, that operation is excluded from
the list even if an earlier page succeeded. The existing blocker remains visible. Unattempted
operations, old successful receipts, missing credentials and non-read operations grant nothing.
The cycle and latest receipts preserve the same list; it contains metadata only, never raw rows.

This is deliberately stricter than copying Icarus's initial field emission, which appended IDs for
every HTTP-success page. It prevents a provider's aggregate row count or one successful operation
from proving that a different empty or denied operation is accessible.

The existing provider-wide `substantive_work_performed` flag and collected row/page counts keep
their established aggregate semantics. Early missing-credential entries explicitly initialize the
flag to false. Consumers must not use the aggregate flag alone to qualify an operation. The
discovery registry additionally checks the exact operation ID, provider/domain/path match,
receipt provenance and freshness, blockers, policy state and existing authority restrictions.

An access receipt does not establish dataset completeness, schema quality, point-in-time research
eligibility, licensing rights, alpha, or execution authority. Unrecognized response shapes remain
unverified. No historical receipt or research result was recomputed.

## Preserved boundaries

Request budgets, request spacing, provider ownership/standby rules, credentials, queues, pagination,
retry policies, encrypted archives/checkpoints, schedules and authorization flags are unchanged.
Databento remains excluded. No provider request, purchase, secret-value read, empirical-corpus
evaluation, workflow dispatch or broker action was performed for this repair.

The current-main port also contains a manual isolated private-consumption workflow. It can run only
by dispatch from Engine `main`, checks out the fixed reviewed Icarus consumer commit above, restores
an already-encrypted archive in a credential-scoped step, then runs consumption in a read-only
Docker container with `--network=none`, no capabilities, and no secrets. Restored bars and temporary
runtime files stay in private runner mounts; only a host-sanitized metadata allowlist can be uploaded.
It uses isolated paper profiles and does not read or alter the owner's PC settings or runtime, so it
is an adapter-consumption proof path rather than a continuous runtime connection or owner-state warmup.
No workflow dispatch or private archive restore has been performed in this task, so real corpus
consumption remains unverified until an authorized operator runs it. The workflow does not collect
data, and it does not grant provider, strategy, production-decision, broker, or execution authority.
It also does not retroactively add operation evidence to old receipts; only a future authorized
collector cycle can produce it.

The workflow hardening in this worktree records `available_at_ns` immediately after a successful encrypted
archive restore. The Engine source commit timestamp is not treated as proof that a restored Actions
cache existed at that earlier time. A consumer exit of `1` is accepted only with a nonempty blocked
dataset list and is published as `PARTIAL` with its exit code; exit `0` requires no blocked datasets
and is published as `COMPLETE`. Inconsistent combinations fail sanitization. The Actions run summary
shows this status so a partially consumed corpus cannot look complete.

## Verification

The initial 11 new synthetic regression cases were observed failing on the missing field before
implementation. Five subsequent nested-empty/depth-bound regressions were also observed failing
before the recursive check; three nested-zero/boolean positive controls remain passing.
Positive fixtures verify exact/current IDs, unique sorted pagination evidence,
numeric-zero rows and persisted latest receipts. Negative fixtures cover empty/placeholder pages,
blank/nonfinite values, denied pages after earlier success, unattempted IDs, stale successes,
missing credentials, non-read jobs and public raw/error exclusion.

Using `/workspace/Icarus/.venv/bin/python` with `PYTHONDONTWRITEBYTECODE=1`, the final pure suite passed
**77 tests**, with no skips or warnings:

```bash
python -m pytest -ra -p no:cacheprovider \
  tests/test_provider_exhaustive_collection.py \
  tests/test_provider_research_context.py \
  tests/test_github_native_credentials.py \
  tests/test_ingestion_surface_contract.py \
  tests/test_supplemental_resilience.py \
  tests/test_provider_supplemental_transport.py \
  tests/test_native_provider_access.py \
  tests_engine/test_provider_archive.py
```

All collection calls in these tests use synthetic injected transports. Credential fixtures contain
dummy strings, and licensed-row examples are synthetic. The suite also verifies existing encrypted
archive/checkpoint recovery, credential boundaries, supplemental transport and aggregation
compatibility. `git diff --check` passed. The worktree intentionally excludes empirical data and
repository-generated corpus artifacts; no broad artifact-backed market tests were run.

On 2026-10-25, the updated sparse worktree's expanded cross-repository suite passed **95 tests**,
including the corpus workflow/sanitizer contracts and provider-operation regressions, with no provider
calls. Cross-repository credential imports were resolved from a companion Engine source tree during
this local verification. Hosted exact-head checks and a manual archive restore remain outstanding.
