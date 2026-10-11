# Claude — task list

Edited only by Claude. Protocol: `coordination/README.md`. Package IDs and ownership as agreed with
Codex on 2026-10-11.

## Owns

All paths are in `reppiks490/Icarus-engine` unless named otherwise.

- CL lab: `cl_lab/**`, `tests_cl/**`, `docs/CL_*.md`, `automation_intelligence/cl_lab/**`,
  `.github/workflows/cl-lab.yml`, `.github/workflows/cl-depth-sweep.yml`
- Provider acquisition and source health (hand-over agreed 2026-10-11): `tools/provider_exhaustive_collection.py`,
  `tests/test_provider_exhaustive_collection.py`, `.github/workflows/provider-exhaustive-collection.yml`,
  `.github/workflows/databento-depth-corpus.yml`, `.github/workflows/databento-depth-research-context.yml`,
  `.github/workflows/sec-edgar-data.yml`. Generated receipts stay producer-owned.
- Encrypted vault: `tools/depth_vault.py`, `data/depth_vault/**`, `tests/test_depth_vault.py`,
  `.github/workflows/depth-vault.yml`
- J01 producer side, sole editor of the shared contract: `automation_intelligence/mcp_interface/icarus_consumer_contract.json`,
  `icarus_engine/interrepo_bridge.py`, `tools/export_peer_intelligence.py`, `tests_engine/test_interrepo_bridge.py`,
  `tests_engine/test_peer_export_workflow.py`, `tests/test_cross_repo_handoff.py`,
  `tests/test_provider_research_context.py`, the J01 specification and producer fixtures
- Sentinel and coordination tooling: `tools/data_sentinel.py`, `tools/coordination.py`,
  `automation_intelligence/sentinel/**`, `.github/workflows/data-sentinel.yml`
- Research documents Claude writes: `docs/AGENTS_ROADMAP.md`, `docs/DEPTH_PREREG_D1.md`, future
  `docs/*PREREG*.md` from Claude
- Restored panel being contained: `data/panel/**`, `tools/asset_panel.py`
- Editor of the shared state files `ICARUS_STATE.md`, `AGENTS.md`, `CLAUDE.md`, one change at a time, with
  Codex's review when its rules or ownership are affected

## Tasks

| Id | Task | Status | Branch / PR | Updated |
|---|---|---|---|---|
| X1 | Protocol corrections from Codex refinement A; this board; receipts | in progress | claude/verification-conversation-ebkh15 | 2026-10-11 |
| L1 | Contain the 13 public vendor panel CSVs: seal into the vault, verify, then remove from the tree. Codex reviews rights (S01) | in progress | claude/verification-conversation-ebkh15 | 2026-10-11 |
| J02 | Source-supported origin labels for every vault object; authenticated decrypt-and-hash verify on a runner | in progress | claude/verification-conversation-ebkh15 | 2026-10-11 |
| J01-P | J01: specification and labeled fixtures for Codex approval, then the producer/exporter after Codex's consumer | planned | - | 2026-10-11 |
| K1 | Alpha Vantage and Finnhub in provider collection, with typed outcomes, rights, clocks and readback | planned | - | 2026-10-11 |
| CL-84 | Compare #84 with current `cl_lab`; propose porting its guards to a fresh CL PR. #84 stays open and intact until Codex agrees | planned | #84 | 2026-10-11 |
| DB4 | `DATABENTO_API_KEY_FOURTH` in a workflow: needs an owner-approved purpose and cap, enforced before requests, and CL-84 resolved | blocked | - | 2026-10-11 |
| R01-C2 | Win-rate frontier: complete family, selection rule, endpoints, null, multiplicity and cost stress preregistered first | planned | - | 2026-10-11 |
| R01-P1 | Forward research simulator for registered rules; no broker, no execution | planned | - | 2026-10-11 |
| R01-C4 | Regime labels known in advance | planned | - | 2026-10-11 |
| R01-C3 | Take/skip meta-labeler on the Icarus entry | planned | - | 2026-10-11 |
| R01-I2 | Fragility: small perturbations per setup | planned | - | 2026-10-11 |
| R01-D1 | Order-flow test D1 (`docs/DEPTH_PREREG_D1.md`) | waiting | needs 20 genuine NQ MBP-10 days | 2026-10-11 |
| T6 | Optional-dependency test skips and cleanup | planned | - | 2026-10-11 |
| MAXP | MAX Pine | blocked | parked by the owner; build a narrow port only after a setup passes HOLD and forward tests | 2026-10-11 |
| X1-0 | Coordination channel set up | done | #134 | 2026-10-11 |
| S1 | Data-health sentinel | done | #131 | 2026-10-11 |
| C8 | Daily phone briefing routine | done | - | 2026-10-11 |
| R2 | `ICARUS_STATE.md` single source of truth | done | #131 | 2026-10-11 |
| F1 | ALFRED vintages requested as of FRED's date | done | #132 | 2026-10-11 |
| F2 | SEC EDGAR fair-access contact | done | #133 | 2026-10-11 |

## Duties of the two dropped agents

Claude dropped its planned claims referee (R1) and red team (I1) to avoid a second framework. Their
duties are not dropped; each is assigned below and counts as covered only when its evidence exists.

| Duty | Covered by | Acceptance evidence | Evidence today |
|---|---|---|---|
| Every research claim has numbers on TUNE and HOLD, with a file or CI run | each R01 package (Claude); Codex reviews | `docs/RESEARCH_LOG.md` entry linking the run | none yet for new packages |
| Requirement-to-evidence ledger across AIs | M02 (Codex) | owner-actions continuations | Codex |
| Look-ahead and leakage | R01 preregistration checklist (Claude) and Codex's independent leakage review | checklist section in each preregistration; review on the PR | not yet exercised |
| Real-price fills only, never Heikin-Ashi | R01 checklist; `cl_lab/backtest.py` fill rules | tests | existing tests; trade-through take-profit rule still to add in R01-C2 |
| Roll jumps | `cl_lab/integrity.py` (cl-data-2, cl-data-3) | `tests_cl` | existing |
| Cost stress (doubled MNQ cost) | R01 checklist; `cl_lab/costs.py` `MNQ_STRESS` | per-package result | tool exists |
| Random-entry and permutation nulls | R01 checklist | per-package result | per package |
| Multiplicity and the global trial count | R01 trial ledger (Claude) | `automation_intelligence/research/trial_ledger.jsonl` | ledger not built yet |
| Prior exposure of HOLD (2025-10-01 onward) | every R01 preregistration states it; only forward evidence qualifies | preregistration text; forward log | to state in R01-C2 |
| Robustness to small changes | R01-I2 | per-setup result | planned |

Full agent design: `docs/AGENTS_ROADMAP.md`.
