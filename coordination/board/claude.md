# Claude — task list

Edited only by Claude. Protocol: `coordination/README.md`.

## Owns

- CL lab: `cl_lab/**`, `tests_cl/**`, `docs/CL_*.md`, `automation_intelligence/cl_lab/**`,
  `.github/workflows/cl-lab.yml`, `.github/workflows/cl-depth-sweep.yml`
- Depth vault: `tools/depth_vault.py`, `data/depth_vault/**`, `.github/workflows/depth-vault.yml`
- Sentinel and coordination tooling: `tools/data_sentinel.py`, `tools/coordination.py`,
  `automation_intelligence/sentinel/**`, `.github/workflows/data-sentinel.yml`
- Agent roadmap and pre-registrations Claude writes: `docs/AGENTS_ROADMAP.md`, `docs/DEPTH_PREREG_D1.md`,
  future `docs/*PREREG*.md` from Claude
- Restored panel: `data/panel/**`, `tools/asset_panel.py`

## Tasks

| Id | Task | Status | Branch / PR | Updated |
|---|---|---|---|---|
| X1 | Claude ↔ ChatGPT coordination: this folder, `tools/coordination.py`, coordinator routine | in progress | claude/verification-conversation-ebkh15 | 2026-10-11 |
| L1 | Move `data/panel/*.csv` (raw vendor ETF bars, restored 2026-10-10) out of the public tree into the encrypted vault | planned | - | 2026-10-11 |
| C2 | Win-rate frontier: win rate vs expectancy over TP/SL/time-stop per setup, against a random-entry null | planned | - | 2026-10-11 |
| P1 | Shadow trader: forward paper trades of the noise-boundary rule on MNQ | planned | - | 2026-10-11 |
| C4 | Regime cartographer: regime labels known in advance; which rules are on today | planned | - | 2026-10-11 |
| C3 | Meta-labeler: take/skip model on the Icarus entry | planned | - | 2026-10-11 |
| I1 | Red team: look-ahead, Heikin-Ashi fills, roll jumps, cost stress on every claimed result | planned | - | 2026-10-11 |
| I2 | Fragility scanner: 1,000 small perturbations per setup | planned | - | 2026-10-11 |
| R1 | Claims referee: ledger of every AI claim, checked against repo and CI | planned | - | 2026-10-11 |
| T6 | Optional-dependency test skips and cleanup | planned | - | 2026-10-11 |
| D1 | Order-flow test D1 (`docs/DEPTH_PREREG_D1.md`) | waiting | needs 20 vaulted NQ MBP-10 days | 2026-10-11 |
| S1 | Data-health sentinel | done | #131 | 2026-10-11 |
| C8 | Daily phone briefing routine | done | - | 2026-10-11 |
| R2 | `ICARUS_STATE.md` single source of truth | done | #131 | 2026-10-11 |
| F1 | ALFRED vintages requested as of FRED's date (daily CL lab failure) | done | #132 | 2026-10-11 |
| F2 | SEC EDGAR fair-access contact | done | #133 | 2026-10-11 |

Full agent design: `docs/AGENTS_ROADMAP.md`.
