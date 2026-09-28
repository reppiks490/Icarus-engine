# H-AION-GOV-002 — protected-holdout consumption ledger

Status: SPECIFIED / IMPLEMENTATION-READY
Run: aion-20260928T213605Z
execution_authorized=false

Mechanism: append-only content-addressed preregistration and holdout-consumption records prevent silent repeated tuning against the protected holdout and make candidate lineage reconstructable.
Expected sign: fewer false acceptances and greater replay/provenance completeness; no PnL claim.
Markets/regime: market-agnostic, first MNQ application; all regimes.
Invalidation: duplicate family consumption, mutated trial family/cost model, overlapping tune/holdout windows, malformed immutable IDs, or missing failed trials can pass.
Required data: hypothesis/version, code commit, dataset-manifest hash, UTC windows, trial-family ID/size and complete trial IDs/statuses, cost-model ID, falsification refs, ledger hash and predecessor hash.
Confounders: legacy studies without immutable manifests remain RESEARCH_ONLY.
Leakage risks: post-holdout tuning, post-split feature fitting, post-hoc family expansion, family aliases.
Execution sensitivity: governance-only.
Lineage: H-AION-GOV-001 plus AION/DAEDALUS PRIME design.
Failure modes: hash aliasing, timezone ambiguity, duplicate IDs, broken predecessor chain, missing negative trials, cost substitution, nondeterministic replay.

TDD contract:
- canonical recursively sorted compact UTF-8 JSON + SHA-256 identity;
- all serious-hypothesis fields required;
- immutable code/data identities required;
- pre-holdout selection windows must end before protected holdout 2025-10-01;
- trial_family_size must equal complete immutable trial-ID set including failed/discarded variants;
- cost model and family hash immutable after registration;
- unique consumption key = hypothesis_version + trial_family_hash + holdout_window;
- predecessor hash must match prior ledger tip;
- duplicate consumption key fails closed;
- execution_authorized remains false.

No empirical trial was run. Statistical edge gates (DSR/PBO/FDR or justified alternative, purge/embargo, bootstrap/permutation/placebo, gross/net friction stress, regime transfer, stability) remain required for future data-bearing candidates.

DAEDALUS request: challenge canonicalization, unique-key alias resistance, predecessor-chain recovery, and migration semantics. This is governance review, not alpha certification.
