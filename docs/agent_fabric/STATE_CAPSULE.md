# Agent Fabric State Capsule

- Goal: add two specialist advisory agents plus one hierarchical multi-agent council to ICARUS with high robustness and profitability-oriented research gates.
- Branch: `feature/agent-fabric-apex-v1`.
- Ownership: `icarus_engine/agents/`, `tests_engine/test_agent_fabric.py`, and agent-fabric documentation only.
- Runtime authority: none. Shadow research eligibility only; `execution_authorized=False` is invariant.
- Implemented: immutable evidence contract; Robustness Guardian; Alpha Synthesis; ten-member Apex Council; veto/quorum/disagreement logic; deterministic audit hash.
- Validation focus: leakage/holdout contamination, point-in-time/provenance, DSR/PBO, OOS/regime stability, execution/cost/latency stress, tail risk, OOD/perturbation stability, calibration, capacity/diversification, deterministic replay.
- Focused verification: 13 tests pass locally after red/green TDD cycles; `compileall` passes; agent package uses only Python standard-library imports.
- Publication integrity: all seven code/test/doc files in commit `8e39edaa5bed4dd97c70a60fef253be1145a7f7b` were re-fetched from GitHub and their Git blob SHAs matched the exact locally tested bytes.
- Repository verification: GitHub Actions run `36466140546` completed successfully across all five jobs: CLI paths, zero-dependency core, combined pytest on Python 3.11, Python 3.12, and Python 3.13.
- Pull request: `https://github.com/reppiks490/Icarus-engine/pull/3`, mergeable after the verified run above.
- Next: build a narrow adapter from existing validated research artifacts to `CandidateEvidence`; then shadow replay and failure-injection tests before any runtime wiring.
- Risk: scoring thresholds are policy defaults, not empirical proof. They must be calibrated only on properly isolated development data and must not consume protected final holdouts.
