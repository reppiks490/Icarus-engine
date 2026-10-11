# ICARUS — state of the system (read this first)

Every AI working in this repository (Claude, ChatGPT, Codex, any agent) reads this file before acting
and updates it when a fact here changes. It is the single source of truth for goals, settled findings,
dead ideas, data access and ownership. If another document disagrees with this one, this one is
corrected or the other is.

Last verified: 2026-10-11 (Claude; ownership agreed with Codex the same day).

## 1. The goal, in numbers

One unified intraday strategy, multi-asset, live-paper-tradeable through `icarus-engine run`, expressible
as `presets/<name>.json`.

| Target | Value |
|---|---|
| Setups | more than 5, each with win rate ≥ 82% |
| Expectancy | positive after costs (MNQ round trip $2.70 = 5.4 ticks) |
| Average hold | ≤ 4 h; about 2 h on 1–5 minute charts |
| Position | 1 contract, 1 take-profit; runner win rate ≥ 90% |
| Streaks | longest winning streak ≫ longest losing streak |

Arithmetic that follows from the targets (do not re-derive):

- At WR = 0.82 the breakeven reward/risk is 0.22 before costs; the viable zone is W/L ≈ 0.3–0.6.
- At WR = 0.82 over 1,000 trades the expected longest losing streak is ≈ 4, the longest winning ≈ 35.
- Telling a true 82% from 75% needs ≈ 220 forward trades per setup (one-sided 95%, power 80%).

## 2. Where things stand (verified, not claimed)

- **No setup is proven.** `automation_intelligence/cl_lab/champions.json` is empty. Nothing is
  execution-authorized.
- CL lab: 492 pre-registered rules on MNQ/BTC/ETH and 2,160 explorer attempts: none survived.
- THE PULSE OF ICARUS v3.1: rejected on real fills (TUNE t 0.58, HOLD t 0.43). Its +$317k is a
  Heikin-Ashi fill artifact.
- Strongest lead: noise-boundary breakout with band trailing exit on NQ 2013–2024 (ids `005e61b86b3d`,
  `c00aeb927f0b`): t 4.5 on 3,200 trades, but t ≈ 0 in the first half and 4.8 in the second → regime
  dependent. Needs a regime gate known in advance.
- Order flow (D1): pre-registered in `docs/DEPTH_PREREG_D1.md`, runs automatically once 20 NQ MBP-10 days
  are vaulted.

## 3. Dead ideas — do not re-test without new data

Full entries in `docs/RESEARCH_LOG.md`.

| Id | Idea | Why dead |
|---|---|---|
| F-001 | Excursion-armed breakeven | Raised win rate, lowered P&L |
| F-002 | `htf_position` edge | Labelling artifact |
| F-003 | Hold-time bands | Outcome-conditioned, circular |
| F-004 | Sweep premise as a direction signal | Fails on 16 markets |
| F-005 | Location sign on real data | Synthetic tape was wrong |
| N-002/4/5 | Cross-asset context, time of day, lead-lag | Noise or untradeable |
| CL R2/R3 | EOD reversal, month-end, pre-FOMC, crypto taker flow, 9 ML models | All rejected on HOLD |

## 4. Rules no AI may break

1. Never force-push, rebase or rewrite history on a shared branch. Never delete another lane's data.
2. Never claim a result without a file path or CI run that proves it. "Collected" is not "used".
3. Tune before 2025-10-01, hold out after it; forward evidence starts at registration.
4. Every test is pre-registered before its data is seen; every trial counts toward one global trial
   count across all AIs.
5. Never rank by duration, MFE, MAE or bars-to-target (outcome-conditioned).
6. Real-price fills only. Heikin-Ashi fills are artifacts.
7. Licensed vendor rows never enter git in the clear (this repo is public); use `tools/depth_vault.py`.
8. No spend without a ledger entry first. No automation that produces nothing: an agent with three empty
   runs in a row disables itself and reports why.
9. Secrets are never printed, pasted or committed.

## 5. Data access (verified 2026-10-11)

GitHub Actions secrets present in this repo: `DATABENTO_API_KEY` (+ `_SECONDARY`, `_THIRD`; `_FOURTH`
exists but no workflow uses it yet), `MASSIVE_API_KEY`, `TWELVE_DATA_API_KEY`, `ALPHA_VANTAGE_API_KEY`,
`FINNHUB_API_KEY`, `FMP_API_KEY`, `FRED_API_KEY`, `EODHD_API_TOKEN`, `TIINGO_API_TOKEN`,
`UNUSUAL_WHALES_API_KEY`. Not present: Alpaca, Quiver, Tickstream, Intrinio, `ICARUS_DATA_ARCHIVE_KEY`.

Claude connectors (interactive sessions and Claude routines only, not GitHub runners): Massive, Alpha
Vantage, Twelve Data, FMP, Financial Datasets, Coinversa (Hyperliquid), Crypto.com, CoinMarketCap,
Bigdata.com, Quartr, LunarCrush, Neon, Google Sheets, Notion, Tavily, Firecrawl, Exa, Consensus, Wolfram,
Hugging Face, Keel, CircleCI, Postman.

Encrypted vault (`data/depth_vault/`, `tools/depth_vault.py`): 133 derived Databento order-book files
(new acquisitions) and the 13-market 5-minute Polygon panel (a preserved original, removed from the tree
on 2026-10-11 and restored from the vault on demand). Every object carries an origin label
(`origins.json`), and every run of `depth-vault.yml` decrypts and hash-checks all of them
(`automation_intelligence/sentinel/vault_verify.json`). The panel was public in plain text from
2026-09-20 (branch) and 2026-10-10 (main); history still holds it, and its rights review is S01 (Codex).
The 18 NQ MBP-10 sweep days bought before 2026-10-10 were lost to cache eviction and are not
recoverable.

## 6. Ownership

Agreed by Claude and Codex on 2026-10-11 (`coordination/README.md`). The exact paths each AI owns are in
`coordination/board/<ai>.md`; claim a package there before changing files for it.

| Area | Implementer | Reviewer |
|---|---|---|
| Strategy research, preregistration, trial accounting, D1 (`cl_lab/`, R01 packages) | Claude | Codex |
| Provider acquisition and source health (provider collection, depth, SEC), encrypted vault | Claude | Codex |
| J01 federation: Engine producer, exporter, the shared contract (sole editor) | Claude | Codex |
| J01 federation: Icarus consumer (`reppiks490/Icarus` `icarus_engine/brain_sync.py`) | Codex | Claude |
| Icarus Brain (C01–C03), Unusual Whales intake, functional UI | Codex | Claude |
| Original-archive recovery, hybrid backlog, scheduled ChatGPT lanes | Codex | Claude |
| Requirement ledger (`reppiks490/icarus-owner-actions` `mission/`) | Codex | Claude supplies receipts |
| This file, `AGENTS.md`, `CLAUDE.md` | Claude, one change at a time | Codex when its rules are affected |
| MAX Pine | parked by the owner | — |
| Canonical runtime `reppiks490/Icarus` | Satellite evidence crosses only through pinned handoffs | — |

ChatGPT automation IDs, prompts, cadences and enabled states are unchanged by this agreement.

## 7. Open work

Live task lists: `coordination/board/claude.md` and `coordination/board/chatgpt.md`. Agent design and
status: `docs/AGENTS_ROADMAP.md`.
