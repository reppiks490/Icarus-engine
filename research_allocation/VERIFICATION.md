# Atlas advisory evaluator — verification record

Original remote prototype: `15cad18d02636c3da94238d87bc971e5fef89c0e`, draft Engine141.
Claude's scope review applied to that prototype only, not this larger code.
Both peers accepted the isolated explicit-model scope; runtime adapters remain
unapproved. The new CI collection shim was reserved in Atlas's own board and
both immutable peer inboxes before its creation, per Claude's PR review suggestion.

- Preserved implementation checkpoint: local `4280d529` adds the already-built
  finite/joint/sequential/sensitivity/CLI/journal code without changing original
  metadata snapshots or planner. The collected original **69 tests passed**,
  with 16 subtests, before further changes.
- RED `cde7f984`: missing predictive/likelihood inputs incorrectly returned generic
  ERROR; validate lacked the production authority-false field. Three failing test
  methods (five failing cases/subcases) established the required behavior.
- GREEN `ca922d08`: **72 tests passed, 19 subtests**, including the original suite.
  Required missing model components now produce INSUFFICIENT_MODEL; both flags
  remain false. No inference, collection or research execution was added.
- Numeric verification includes 250 deterministic random finite models checked
  against a Decimal oracle, analytic perfect/null information, utility invariants,
  zero/subnormal priors, malformed inputs and explicit joint marginal checks.
- Prospective synthetic tests cover registration/outcome ordering and expiry,
  replay/conflict, concurrency, reopening, local tamper detection, zero-probability
  contradictions, cost overrun and unresolved/expired inclusion.
- RED `2225d2ba`: independent review reproduced rare/zero joint marginal
  inconsistencies, raw-versus-normalized sequential arithmetic, four write-lock
  timestamp/order failures, and oversized-integer CLI error subcases.
- GREEN `f65f5e9b`: shared normalized joint with relative/zero-exact marginals,
  coherent conditional weights, fresh locked timestamps and range-first integer
  rejection. **81 tests/22 subtests passed**; the coherent rare-event positive
  control remains valid and does not justify an excessively costly follow-up.
- Verification `b3f2e7e`: an independent Decimal stopping-policy oracle over
  **200 deterministic correlated joint models** joins the existing 250-model
  single-observation oracle; **82 tests/22 subtests passed**.
- RED `f1e37e60`: continued review reproduced large-utility final-value
  cancellation and caller mutation of a model while registration waits.
- GREEN `858eead5e5e8ba433ab392a40e3c57bb74b22dcb`: final gain/cost subtraction
  order, zero/perfect-information roundoff bounds and preference tolerance;
  one independent frozen model snapshot shared by analysis and persistence.
  **84 tests/22 subtests passed**. No scientific hypothesis was tested.

Intermediate full software regressions passed: initial72-test implementation
1,202 combined tests; first corrective81-test implementation1,211 combined;
oracle82-test implementation1,212 combined. Each combined run passed39 subtests
after the corrective additions. The unchanged CL software suite passed167 tests
with three existing NumPy warnings. These earlier runs are not final-tree proof.

## Final local verification and review

Reviewed code: local `858eead5e5e8ba433ab392a40e3c57bb74b22dcb`, published
history equivalent `e99a83d8f24ab448bdf127384e607bf6e7b39cf8`, identical tree
`7068858a86b980b234b797ecefbf05422966fe07`. Later changes are documentation-only.

- `python -m pytest tests/test_research_allocation.py --import-mode=importlib -o addopts='' -q`:
  **84 passed, 22 subtests passed**.
- `python -m unittest discover -s research_allocation -p 'test_*.py' -q`:
  **84 passed**.
- `python -m pytest tests tests_engine --import-mode=importlib -o addopts='' -q`:
  **1,214 passed, 39 subtests passed**, 34.99 seconds.
- `python -m pytest tests_cl --import-mode=importlib -o addopts='' -q`:
  **167 passed**, 60.64 seconds, three existing NumPy empty-slice/division
  warnings. This is a fresh offline CL software regression, not a market trial.
- Fresh read-only independent reviewer: **CLEAR** at the reviewed code and
  documentation working diff; all four Important findings and the numeric CLI
  error were independently rechecked, no remaining Critical/Important blocker
  within scope. No reviewer source edits, external calls or research trials.

An early combined-test invocation suppressed pytest's configured import mode
and hit duplicate `test_metrics` collection names. The corrected invocation
explicitly retains `--import-mode=importlib`; no unrelated source was patched.
Published-head CI receipts are recorded against the exact remote SHA in PR141
and immutable final peer inboxes after publication, never borrowed from the
green original prototype. CI/integration acceptance is not asserted by this
local-checkpoint record.

## Durable failing-first history

These local engineering checkpoint IDs correspond to preserved published commit
objects below; each complete Git tree was checked identical during API
publication. Publication is a fast-forward from the original prototype, with
no rebase or force push. The final documentation receipt is a later commit.

| Step | Local checkpoint | Published commit |
|---|---|---|
| Initial 69-case implementation | `4280d529` | `b43ce9a212a72c82e44d3702dc7f477d7578b339` |
| Insufficient-model RED | `cde7f984` | `97e2e50ab612437242c9ee0b9c195c2f0911921a` |
| Insufficient-model GREEN | `ca922d08` | `e3e9c9bf5948affd6cfe7473729bf432d74dfbd1` |
| Contract/knowledge checkpoint | `6e4380d7` | `43d2a11b4a7584998800b67d501583fe7c48c195` |
| Rare-event/lock/numeric RED | `2225d2ba` | `4d9bc19d6452f69960832c445521f0d9a378daf1` |
| Rare-event/lock/numeric GREEN | `f65f5e9b` | `d5c61db6e1da7c2e43770e51674cf06350d0e3a9` |
| 200-model joint oracle | `b3f2e7e3` | `02b2a12fc0eec7b396752c39fe539f1076d25f47` |
| Final-value/mutation RED | `f1e37e60` | `7a3007dd647e5bf794c84c873a6d0f38c46dc13a` |
| Final-value/mutation GREEN | `858eead5` | `e99a83d8f24ab448bdf127384e607bf6e7b39cf8` |

This checkpoint is a reviewable draft, not integration acceptance. No
market trial, global trial-ledger write, provider call, data purchase, new
credential, runtime adapter, workflow change or execution activation occurred.
Database/WAL files and raw market/provider data are not part of the commit.

Inline scope/librarian pass: design, implemented features, unknowns, boundaries,
commands and verification now agree. Historical source/probe artifacts remain
pinned; shared routers and peer boards remain untouched. Further real-world
evaluation and owner integration are explicitly future work.
