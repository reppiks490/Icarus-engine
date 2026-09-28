# ICARUS Agent Fabric v1

This package adds three advisory layers without changing the existing runtime or granting trading authority.

## 1. Robustness Guardian

`RobustnessGuardianAgent` is a fail-closed promotion gate. It rejects candidates with look-ahead evidence, protected-holdout contamination, incomplete point-in-time/provenance coverage, weak deterministic replay, insufficient out-of-sample/regime breadth, non-positive lower-confidence-bound expectancy, or an edge that disappears under stressed costs.

Its score also incorporates deflated Sharpe, probabilistic Sharpe, sample depth, regime/walk-forward stability, perturbation survival, parameter stability, drawdown, and PBO pressure. The purpose is to make a spectacular backtest insufficient by itself.

## 2. Alpha Synthesis

`AlphaSynthesisAgent` optimizes for risk-adjusted *net* edge rather than gross return. It rewards annualized return, lower-confidence-bound expectancy, stressed net expectancy, deflated Sharpe, probabilistic Sharpe, drawdown efficiency, tail-risk survival, diversification, capacity headroom, parameter stability and bootstrap sign stability.

It hard-vetoes profitability that becomes non-positive under uncertainty or execution stress. This is a research promotion mechanism, not a promise of future profit.

## 3. Apex Council

`ApexCouncilAgent` is a deterministic hierarchical council containing ten internal agents:

1. robustness-guardian
2. alpha-synthesis
3. data-integrity
4. regime-sentinel
5. execution-sentinel
6. tail-risk-sentinel
7. adversarial-sentinel
8. calibration-sentinel
9. multiple-testing-sentinel
10. ood-sentinel

The council uses specialist vetoes, quorum, minimum promotion votes, a robust median aggregate, disagreement-aware confidence, and a deterministic SHA-256 trace over the evidence, configuration and child verdicts. A veto beats aggregate profitability.

The council can emit only `promote`, `hold`, or `reject`. `promote` means eligible for shadow evaluation only. `execution_authorized` is structurally fixed to `False` and the package exposes no broker/order handle.

## Evidence contract

`CandidateEvidence` requires point-in-time, auditable inputs covering:

- trial count and multiple-testing pressure
- trade count, OOS windows and regime coverage
- annualized return and gross/net expectancy
- lower-confidence-bound and stressed net expectancy
- Sharpe, deflated Sharpe, probabilistic Sharpe, PBO
- max drawdown and expected shortfall
- turnover and capacity utilization
- regime and walk-forward return series
- perturbation survival and parameter stability
- provenance and point-in-time coverage
- calibration error and strategy correlation
- bootstrap positivity and OOD stability
- cost-model coverage and latency-stress survival
- deterministic replay evidence
- explicit look-ahead, data-quality and holdout-contamination flags

Malformed, non-finite or out-of-domain evidence is rejected before scoring.

## Integration boundary

Phase 1 is intentionally isolated under `icarus_engine.agents`. It does not mutate `icarus_engine.orchestration`, research ledgers, broker bridges, activation logic or execution controls.

The next integration step should be a narrow adapter from the existing validated research artifact into `CandidateEvidence`, followed by shadow-only replay tests. Runtime activation must remain separately gated by the existing ICARUS approval/rollback controls.

## Research basis

The design explicitly accounts for multiple testing and selection bias rather than treating a high historical Sharpe as proof of edge. The evidence model therefore includes Deflated Sharpe Ratio and Probability of Backtest Overfitting inputs and requires point-in-time/OOS evidence, costs, stress tests and deterministic replay.
