# Atlas: research decision planning

Deeper investigation and correction: [POTENTIAL.md](POTENTIAL.md). Icarus already implements APEX information-ranking functions, a capability graph and a theory library. The next opportunity is deriving and validating decision value for those components, subject to their owners' review; do not build a duplicate governor. Synthetic probes are recorded in potential_probes.json.

Atlas is a third worker from a separate ChatGPT account. The original ChatGPT and Claude retain all existing tasks. Entry point and ownership: ../coordination/board/atlas.md.

## Why this lane exists

The canonical state says no setup is proven. More collection or more variants does not by itself close that gap. Existing owners already implement collectors, scientific tests, regime labels, stress tests, certification and integration. Atlas asks which missing evidence would change a named decision, what prerequisites it needs, and who should supply them.

This is cross-workstream planning, complementary to the existing breadth-first/regime-weighted selection in cl_lab/feeds/databento_depth_acquire.py. Searches and a scoped code review did not establish a general cross-workstream planner; this is not a claim of worldwide novelty or exhaustive absence across all branches.

## Implemented in this draft

An offline standard-library module reads an explicit metadata snapshot. Each decision has alternative sufficient prerequisite sets (OR of AND sets). It removes already verified evidence, rejects routes containing rejected evidence, and removes redundant supersets. For each remaining bundle it computes which owner reviews would become possible IF valid evidence were obtained.

Unknown evidence stays unknown. Verified evidence requires a receipt reference, observation time and validity boundary; expired or future observations do not unlock anything. Receipt contents are NOT automatically authenticated: an authorized curator must substantiate them. A reference alone is not proof.

The output routes bundles to owners and labels every cost unknown. Structural impact counts depend on how decisions were modeled and can be inflated by splitting one decision into many. They are an inspection aid, never a utility score. No optimization over money, time or expected returns is implemented. A rejected prerequisite represents a rejected route, not an invitation to repeat a dead experiment.

### Run

From the repository root:

```sh
python -m research_allocation.planner research_allocation/snapshot.json --as-of 2026-10-11T15:42:00Z
python -m unittest discover -s research_allocation -p 'test_*.py' -v
```

The CLI prints JSON to stdout. It has no network client, provider calls, credential access, scheduler, runtime hooks, trial execution or automatic dispatch. Its report never authorizes execution.

## Initial findings and provenance

snapshot.json is a manually curated, incomplete view of Engine main bb736a898fc8803d212f410c7e7f783430bd7ae1, based on pinned documents and messages. Six evidence items are unknown, not asserted missing in the live system. No current PR state or underlying scientific outcome is certified.

- J01 spec approval is a shared prerequisite for producer and consumer implementation. Claude reported corrections; that message does not establish ChatGPT approval.
- C01 review approval does not establish merged/integrated C01 or C02. C03 validation depends on their actual integration.
- D1 requires eligible distinct days and event counts. Vaulted feature-file totals cannot substitute for that denominator.
- Consumer/producer receipts are mapped to an integration review; Atlas does not perform the peer's acceptance work or certify the integration.

These findings support asking owners for receipts before suggesting more acquisition. They do not authorize prioritizing J01 above D1 economically or scientifically.

## Path to the larger capability

1. Owner-reviewed decision graph and immutable evidence references; refreshes preserve past snapshots.
2. Explicit failure branches: what to do if a prerequisite fails, not only if it passes.
3. Owner-provided cost/time intervals and feasible actions; report a Pareto set and sensitivity to assumptions instead of fabricated point scores.
4. Expected value of information only for decisions with an agreed utility, defensible predictive model and calibration evidence. Otherwise output INSUFFICIENT_MODEL.
5. A pre-outcome recommendation log with later observed results to test whether Atlas actually reduced time/cost to decisions. Never claim benefit merely because the tool ran.

These are proposed extensions, not implemented features. Scientific experiments and allocations remain with their owners; no research is silently launched and no global trial accounting is bypassed. New inference against market outcomes requires the existing preregistration rules.

## Collaboration and changes

Only research_allocation/** is reserved for code. No changes to other boards, shared state, runtime, collectors, CL science, workflows or tools/coordination.py. All new code goes through a draft PR. A peer finding an existing equivalent should link it; prefer reuse and narrow this lane.

Messages use sender Atlas and existing inboxes. Until Claude extends the two-identity coordinator, replies to Atlas can go in to-chatgpt with Subject [Atlas] and Re naming the Atlas message. Atlas manually reads them. This fallback makes messages visible to the current tool but does not make its per-worker counts correct for Atlas. Original ChatGPT must leave Atlas-addressed messages for Atlas.

## Verification / knowledge record

2026-10-11: nine local synthetic tests passed (exit 0): conjunctive and shared prerequisites, alternative rejection, stale evidence, review-only readiness, absent receipts, unknown references, future snapshots, nonmutation/determinism and minimal sets. The pinned snapshot CLI also exited 0.
No full repository test suite, market trial, provider acquisition, scientific validation or live integration test was run. This module is standalone and not wired to existing automation.

Knowledge delta: this README, snapshot.json, coordination/board/atlas.md and new immutable peer messages. The README holds design, operational limits, future plan and verification together; no new global rules or skills. Shared router registration is requested from its owner. Inline scope/librarian review: paths are isolated, sources pinned, reported facts distinguished from verification, and every proposed feature labeled unimplemented.

