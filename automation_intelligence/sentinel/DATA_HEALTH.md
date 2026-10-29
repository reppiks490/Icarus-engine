# Data health — 2026-10-29 06:24 UTC

**FAILING** 36 · **BLOCKED** 8 · **STALE** 4 · **DEGRADED** 4 · **OK** 34

## Needs attention

| Source | Verdict | Why |
|---|---|---|
| feed:databento_6a_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_6b_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_6e_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_6j_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_btc_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_cl_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_dx_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_es_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_gc_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_hg_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_m2k_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_mbt_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_mcl_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_mes_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_mgc_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_mnq_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_mym_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_ng_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_nq_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_pa_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_pl_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_rty_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_si_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_sil_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_sr3_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_vxm_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_ym_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_zb_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_zc_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_zf_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_zn_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_zs_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_zt_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| feed:databento_zw_5m | FAILING | root not in CL_DATABENTO_ROOTS |
| workflow:cl-depth-sweep.yml | FAILING | latest run failure: https://github.com/reppiks490/Icarus-engine/actions/runs/40800070536 |
| workflow:databento-depth-research-context.yml | FAILING | latest run failure: https://github.com/reppiks490/Icarus-engine/actions/runs/40800070590 |
| provider:alpaca | BLOCKED | no key reaches the runner |
| provider:bybit | BLOCKED | no key reaches the runner |
| provider:finnhub | BLOCKED | BLOCKED_AUTHENTICATION |
| provider:intrinio | BLOCKED | no key reaches the runner |
| provider:quiver | BLOCKED | no key reaches the runner |
| provider:tickstream | BLOCKED | no key reaches the runner |
| provider:twelve | BLOCKED | BLOCKED |
| provider:unusual_whales | BLOCKED | BLOCKED_AUTHENTICATION |
| workflow:native-five-research.yml | STALE | last success 3.4 h ago (expected within 3 h) |
| workflow:provider-exhaustive-collection.yml | STALE | last success 5.4 h ago (expected within 3 h) |
| workflow:provider-supplemental-promote.yml | STALE | last success 6.0 h ago (expected within 3 h) |
| workflow:sec-edgar-data.yml | STALE | last success 3.4 h ago (expected within 3 h) |
| provider:alphavantage | DEGRADED | key present but 0 rows (QUOTA_OR_RATE_LIMIT_PAUSED) |
| provider:eodhd | DEGRADED | dedicated fabric live (11 calls, 2510 known rows); generic sampler blocked; 29 endpoints denied by plan |
| provider:fmp | DEGRADED | dedicated fabric live (3 calls, 51 known rows); generic sampler blocked; 85 endpoints denied by plan |
| provider:tiingo | DEGRADED | 47567 rows; 4 endpoints denied by plan |

## Delivering

economic_events, feed:btcusd_cb_5m, feed:btcusdt_5m, feed:cboe_skew, feed:cboe_vix, feed:cboe_vix3m, feed:cboe_vix9d, feed:cboe_vvix, feed:cftc_disaggregated_all, feed:cftc_tff_all, feed:cftc_tff_nasdaq, feed:ethusdt_5m, feed:fred_dff, feed:fred_dgs10, feed:fred_dgs2, feed:fred_nasdaq100, feed:fred_t10y2y, feed:fred_vixcls, feed:treasury_auctions, feed:treasury_debt_to_penny, feed:treasury_operating_cash, fred_alfred, provider:fred, provider:massive, sec_edgar, workflow:cl-lab.yml, workflow:databento-depth-corpus.yml, workflow:depth-vault.yml, workflow:external-data-fabric.yml, workflow:interrepo-peer-intelligence.yml, workflow:native-provider-access.yml, workflow:official-economic-events.yml, workflow:provider-supplemental-collection.yml, workflow:tests.yml

## Order-book data

Vaulted files: {'bars_primary': 33, 'bars_secondary': 2, 'bars_third': 1, 'corpus': 135, 'panel': 13, 'sweep': 10} (key: HKDF(DATABENTO_API_KEY)). Last vault decrypt/hash check: OK at 2026-10-28T09:50:27+00:00 with 0 failures. D1 status: {'D1-A': 'INSUFFICIENT_DATA', 'D1-B': 'INSUFFICIENT_DATA', 'days': 4}.

| Budget | Cap | Spent | Left |
|---|---|---|---|
| corpus__primary | $3.54 | $2.54 | $1.0 |
| corpus__secondary | $2.19 | $1.17 | $1.03 |
| depth__diversifier | $95.0 | $94.99 | $0.01 |
| depth__index | $93.0 | $92.99 | $0.01 |
| depth__sweep__primary | $34.34 | $34.32 | $0.03 |
| depth__sweep__secondary | $3.36 | $3.31 | $0.05 |
| depth__sweep__third | $12.0 | $11.87 | $0.13 |
| history__ES | $25.0 | $18.14 | $6.86 |
| history__NQ | $25.0 | $17.5 | $7.5 |

## Research

Champions: 0. Pulse variants: {'CANDLES': 'REJECTED', 'HA_HA_FILLS': 'ARTIFACT_REFERENCE', 'HA_REAL_FILLS': 'REJECTED'}. CL lab last run: 2026-10-29T01:17:59.772801+00:00.

## Coordination (Claude, ChatGPT, Atlas)

- claude: done 5, in progress 2, planned 9, waiting 1; awaiting its reply: 14; stale in-progress: X1, CL-84
- chatgpt: done 3, in progress 9, planned 5, waiting 9; awaiting its reply: 2; stale in-progress: X1-Codex, IB01, IB04, REVIEW01, A200, SYS22, C02, M01
- atlas: waiting 4; awaiting its reply: 2
- malformed messages: to-claude/20261011T213350Z-atlas-registry-checkpoint.md: to, date, reply-needed, file name; to-claude/20261013T2311Z-chatgpt-ib03-pr336-review.md: from, to, date, subject, reply-needed; to-claude/20261013T2327Z-chatgpt-ib03-pr336-final-head.md: from, to, date, subject, reply-needed; to-claude/20261013T2338Z-chatgpt-ib03-pr336-review.md: from, to, date, subject, reply-needed; to-claude/20261014T0003Z-chatgpt-ib03-pr336-head-update.md: from, to, date, subject, reply-needed; to-chatgpt/20261011T213350Z-atlas-registry-checkpoint.md: to, date, reply-needed, file name
