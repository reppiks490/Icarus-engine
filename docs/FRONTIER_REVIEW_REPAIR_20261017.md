# FR-1 independent review repair

This repair is based on code PR #142 at `dfb18e96805faa905b687eaa4633d349a9f82eb2` and
preregistration PR #137 at `72f5bdb866d134bdef12adc06bbb22837a9f8a3c`. Both were open and
unmerged when reviewed. The inspected main tree (`a08aaf0c217f923b474216ded87ade6835d91957`)
contained neither new FR-1 module; its relevant CL dependency source blobs matched PR #142.
No empirical tape, HOLD results, canonical trial ledger, credentials or broker were used.

## Mechanical repairs

- Window identity now binds the complete causal raw-price prefix, timestamps, contract identities,
  overnight prices and prior index closes. HOLD and FORWARD identities include earlier context.
  Adding later forward sessions leaves TUNE and HOLD identities unchanged; a forward evaluation
  hashes only through its first qualifying session close.
- A detected switch anywhere in an RTH session, including its first bar, rejects the entire dataset before evaluation or ledger
  initialization. An old-contract entry cannot fill against a new-contract print. No hindsight
  session mask is introduced.
- Missing HOLD p-values count as non-rejections with p = 1 within the full reached-source Holm
  family. Invalid tests cannot shrink multiplicity for another source.
- Historical CL evaluations have distinct `(run, asset, rule)` identities. Complete retained rows
  must match each run's declared evaluation counts. Aggregate summaries cannot stand in for missing
  per-trial rows. Explorer attempts are counted once only when their run identities match; an
  overlapping unversioned explorer row is ambiguous and blocks import.
- Boos, Pulse and evaluated D1 trials bind original input fingerprints. Known historical source
  versions require original retained evidence. Duplicate attempts, malformed sources and conflicting
  identities block import before any trial is written.
- Append and snapshot use a POSIX advisory lock on `<ledger>.lock`. Appends validate the entire
  batch, retain existing bytes and atomically replace the file with those bytes plus new records.
  Moving an unchanged source into an archive does not create another trial.
- Frozen snapshots include a digest of the included historical records. Prospective historical
  additions must match that frozen digest and count under the ledger lock before append. A changed
  historical evidence set, or a legacy snapshot without this binding, blocks the run; it never
  silently re-freezes the baseline. Adding FR-1's own excluded records does not invalidate it.

The registered source IDs, grids, dates, occupancy/fill rules, costs, statistical thresholds and
qualification targets are unchanged. These changes do not authorize execution or a real experiment.

## Required historical evidence and remaining boundaries

CL summaries remain in `automation_intelligence/cl_lab/history/*.json`. The corresponding complete
candidate rows must be available as `history/<run_id>.candidates.jsonl` when they are no longer the
current `candidates_latest.jsonl`. The importer checks actual rows, asset counts and run IDs; it
does not synthesize missing rows from counts.

For an older Boos fingerprint advertised by a run summary, retain
`history/boos/<fingerprint>.json` with the original `fingerprint` and `candidate_rows` list. Historical
Pulse variants must retain their original input fingerprint in the run's Pulse evidence. Retained
D1 snapshots may be supplied in `history/depth-d1/*.json`; an evaluated D1 source must have its
original `fingerprint` or `input_fingerprint`. An integrity algorithm label such as `cl-data-3` is
not a dataset identity.

The old writer in `cl_lab/run.py` does not persist complete candidate archives and omits the Pulse
fingerprint from its per-asset history projection. `cl_lab/depth_test.py` does not emit a D1 input
fingerprint. Consequently, missing original archives or provenance are research evidence blockers
that require recovery or collector work before a real FR-1 run. This source-only repair did not
inspect the empirical artifacts and does not claim that historical recovery is complete. Missing
evidence must not be renamed a credential blocker or replaced with invented trials.

The complete-day policy proposed in PR #142 remains an open preregistration decision: observed
missing late bars can erase earlier signals on that day. Calendar-known early closes and unknown
future missing observations need an explicit pre-data policy. This repair leaves that policy
unchanged.

Locks serialize cooperating processes on one POSIX filesystem. They do not coordinate separate
GitHub runners, divergent Git checkouts or Windows writers. Workflow concurrency and canonical
ledger reconciliation remain prerequisites for real automation. No workflow or schedule is added.
Frozen snapshot creation and the whole research run still require that outer single-writer gate.
Legacy ledger identities or snapshots must be reconciled explicitly rather than assumed compatible.

## Verification

New synthetic regressions were observed failing before their respective implementation changes:
causal input identity, missing/archived historical evaluations, source versioning, ambiguous explorer
overlap, duplicate/conflicting accounting, cross-process locking, mixed-contract fills, full-family
Holm adjustment and stale snapshot rejection. All ledger files used by tests are temporary fixtures.

`python -m pytest tests_cl/test_trial_ledger.py tests_cl/test_frontier.py -ra -p no:cacheprovider`
passed all 45 focused tests in 27.57 seconds. `python -m pytest tests_cl -ra -p no:cacheprovider`
passed 210 tests with two skips in 93.59 seconds. Both skips are the existing Pulse tests requiring
the deliberately absent MNQ 20m tape; the three existing NumPy warnings originate in
`test_r2.py::test_month_end_daily_variants_trade_against_signal`. These runs used
`/workspace/Icarus/.venv/bin/python` with `PYTHONDONTWRITEBYTECODE=1`.

The default project suite was also attempted in the intentionally sparse source checkout: 1,066 passed,
64 failed and 17 subtests passed. The failures required excluded repository controls/contracts,
coordination artifacts, integration metadata or `data/mnq_20m.csv`; empirical files were not
materialized to satisfy those checks. Failing groups were watchdog repository-control tests,
cross-repo handoff contracts, GitHub-native dispatcher/job/runner/liveness tests, the federation
event corpus, restored-five scheduler contracts, agent-persistence contracts, interrepo consumer
contracts, scheduler-topology manifests and the shipped-MNQ-archive existence test.

Keep the code unmerged and do not run empirical FR-1 until preregistration review/approval/merge,
independent exact-head code review, the complete-day decision and historical evidence recovery are
resolved. Forward evidence alone can qualify a setup under the registration; this repair makes no
strategy-performance claim.

## Exact-source follow-up

Independent review at `5921bbcab19473a699cf3ff8894e7b345690c898` found one inherited boundary issue: a switch on the first RTH bar escaped the rejection guard while the pre-session context still used the old contract basis. Two added synthetic cases failed before repair. Source `54edacb05760a085062c7be4bfba1f3be4701691` blocks that boundary before evaluation or ledger/snapshot mutation, without changing signal context or registered rules. Independent re-review is CLEAR, including valid overnight switches remaining accepted. The focused selection now contains 47 passing cases. The final full CL run succeeds with 212 passed and the same two tape-dependent skips; the same three NumPy warnings remain. Its log is local verification evidence, not empirical FR-1 results.

The new `FR-1 synthetic contract` workflow tests exactly the two synthetic frontier/ledger modules. Its checkout omits `data/` and `automation_intelligence/`, asserts their absence, and receives no provider secrets. It adds no scheduler or experiment entrypoint. Changes to CL dependencies and test configuration retrigger the contract. Hosted exact-head outcomes remain pending at publication and must be recorded separately. The ordinary application workflow omits `tests_cl`; its success alone cannot establish this contract.
