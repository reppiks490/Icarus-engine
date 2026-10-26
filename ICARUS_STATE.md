# ICARUS — state of the system (read this first)

Every AI working in this repository (Claude, ChatGPT, Codex, any agent) reads this file before acting
and updates it when a fact here changes. It is the single source of truth for goals, settled findings,
dead ideas, data access and ownership. If another document disagrees with this one, this one is
corrected or the other is.

Last verified: 2026-10-16 (Codex; GitHub-native health and persisted evidence).

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

- 2026-10-26 cloud repair: the supplemental UW transport now admits the documented
  `/api/crypto/list_tokens` resource while rejecting ambiguous URL structure and
  preserving header-only credentials. Transport/core collection regressions:
  65 passed offline. This does not establish provider authentication or entitlement.

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

## 5. Data access (verified 2026-10-16)

The redacted GitHub-native health run `38902710676` confirmed Actions-secret presence for Databento primary/secondary/third/fourth, EODHD, Tiingo, Unusual Whales, Alpha Vantage, FMP, FRED, Massive, Finnhub, and Twelve Data. Secret presence is not proof of a successful provider response. The latest all-provider context was rebuilt at `2026-10-16T19:51:40Z` by exhaustive run `38957297394`: 20,268 rows across 53 pages, 122 requests, five providers with substantive collection, and seven blocked. EODHD collected 67 rows, Tiingo 1, FRED 60, Massive 20,000, and Twelve Data 140; all are partial catalog slices, not complete coverage. FMP's latest generic pass was blocked with zero rows after 20 requests. Its separate external-data fabric still has prior successful derived outputs (three calls in the 12:51 snapshot), which Sentinel reports as degraded delivery while retaining the generic sampler's plan denials. The generated context is `automation_intelligence/provider_collection_v1/research_context.json`.

- **EODHD:** the dedicated external-data fabric produced 2,510 daily rows across 10 symbols through 2026-10-15; tick windows are plan-limited (`38902923997`).
- **Tiingo:** 45,137 daily rows and 2,340 five-minute bars across 6 symbols were produced; news returned HTTP 403 (`38902923997`).
- **Unusual Whales:** the key is present, but the latest supplemental request returned HTTP 401 and zero rows (`38905397776`); the native canary also returned HTTP 401 (`38897165047`). A safe 111-row/5-page receipt from run `38873907446` remains available in `cycles/` and is exposed separately as historical-only context; it is not current API access. Repair/replace the provider credential or authorization before treating this API lane as live. The separate interactive connector is a distinct transport.
- **Finnhub:** the key is present but provider authentication has previously returned HTTP 401. Treat the lane as blocked until a current successful receipt exists.
- **Databento bars:** four key slots are present; the depth workflows use the first three. The public feed manifest lists 34 instruments with five-minute bars. The dedicated depth context remains blocked because no primary-account feature files are in the encrypted vault; 156,928 derived feature rows are currently from secondary/third accounts. Vault recovery works with `HKDF(DATABENTO_API_KEY)`; the missing standalone archive key is not the current cause. Do not weaken the integrity gate or spend beyond a recorded allocation.
- **FMP/FRED/Massive/Twelve Data and Alpha Vantage:** use their current provider receipts and Sentinel state; presence alone does not establish complete collection.
- **Latest provider refresh:** FMP, EODHD, FRED, Massive, Tiingo and Twelve Data catalog drains completed successfully as workflows in run `38957297394`; workflow success does not mean full catalog coverage. The aggregate context preserves per-provider status, row counts and cursor/catalog coverage. The supplemental run `38957297117` still records Unusual Whales and Finnhub as authentication-blocked and Alpha Vantage as having no ready jobs.

EODHD/Tiingo summaries and other permitted derived evidence are in `automation_intelligence/cl_lab/external_data_fabric.json`; provider-level receipts and shared context are under `automation_intelligence/provider_collection_v1/`. Licensed vendor rows stay out of public git and are retained only under approved cache/vault rules.

The Engine health run did not report shared credentials for Alpaca, Intrinio, Quiver, Tickstream, or IBKR. IBKR in `reppiks490/Icarus` is a local loopback TWS/IB Gateway paper adapter, not a shared market-data API lane. Do not infer presence in another repository or runtime from Engine health.

Interactive connectors (for interactive sessions only, not GitHub runners): Massive, Alpha Vantage, Twelve Data, FMP, Financial Datasets, Coinversa (Hyperliquid), Crypto.com, CoinMarketCap, Bigdata.com, Quartr, LunarCrush, Neon, Google Sheets, Notion, Tavily, Firecrawl, Exa, Consensus, Wolfram, Hugging Face, Keel, CircleCI, Postman.

Paid order-book data remains encrypted in `data/depth_vault/`. The vault currently has no primary-account feature entries; earlier paid NQ sweep data was lost to cache eviction. The latest integrity gate correctly refuses to publish incomplete primary-depth context. Recovery needs the already-paid source to be found or a separately recorded budget allocation; do not report those features as available.

## 6. Ownership

| Area | Owner | Notes |
|---|---|---|
| Strategy research, agents, vault, this file | Claude (`claude/*` branches) | |
| ChatGPT scheduled lanes, hybrid loop, restored-five, omega stack | ChatGPT / Codex | Cadences pinned by their tests; do not change without them |
| CL lab | Claude (CL lane) | |
| Canonical runtime | `reppiks490/Icarus` | Satellite evidence crosses only through pinned handoffs |

Claude and ChatGPT coordinate through `coordination/` (protocol: `coordination/README.md`). Each AI's
task list and the paths it owns are in `coordination/board/<ai>.md`; claim a task there before starting
it. Messages between the two go in `coordination/inbox/`.

## 7. Open work

Live task lists: `coordination/board/claude.md` and `coordination/board/chatgpt.md`. Agent design and
status: `docs/AGENTS_ROADMAP.md`.
