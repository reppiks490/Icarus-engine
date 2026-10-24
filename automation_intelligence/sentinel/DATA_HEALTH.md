# Data health — 2026-10-24 06:25 UTC

**FAILING** 2 · **BLOCKED** 6 · **STALE** 2 · **DEGRADED** 6 · **OK** 70

## Needs attention

| Source | Verdict | Why |
|---|---|---|
| workflow:cl-depth-sweep.yml | FAILING | latest run failure: https://github.com/reppiks490/Icarus-engine/actions/runs/40043884356 |
| workflow:databento-depth-research-context.yml | FAILING | latest run failure: https://github.com/reppiks490/Icarus-engine/actions/runs/40043884380 |
| provider:alpaca | BLOCKED | no key reaches the runner |
| provider:finnhub | BLOCKED | BLOCKED_AUTHENTICATION |
| provider:intrinio | BLOCKED | no key reaches the runner |
| provider:quiver | BLOCKED | no key reaches the runner |
| provider:tickstream | BLOCKED | no key reaches the runner |
| provider:unusual_whales | BLOCKED | BLOCKED_AUTHENTICATION |
| workflow:provider-supplemental-promote.yml | STALE | last success 5.4 h ago (expected within 3 h) |
| workflow:sec-edgar-data.yml | STALE | last success 4.8 h ago (expected within 3 h) |
| provider:alphavantage | DEGRADED | 14376 rows; 3 endpoints denied by plan |
| provider:bybit | DEGRADED | no key; keyless endpoints only, none ready |
| provider:eodhd | DEGRADED | dedicated fabric live (11 calls, 2510 known rows); generic sampler blocked; 29 endpoints denied by plan |
| provider:fmp | DEGRADED | dedicated fabric live (3 calls, 53 known rows); generic sampler blocked; 27 endpoints denied by plan |
| provider:tiingo | DEGRADED | 47537 rows; 4 endpoints denied by plan |
| provider:twelve | DEGRADED | 140 rows; 1 endpoints denied by plan |

## Delivering

economic_events, feed:btcusd_cb_5m, feed:btcusdt_5m, feed:cboe_skew, feed:cboe_vix, feed:cboe_vix3m, feed:cboe_vix9d, feed:cboe_vvix, feed:cftc_disaggregated_all, feed:cftc_tff_all, feed:cftc_tff_nasdaq, feed:databento_6a_5m, feed:databento_6b_5m, feed:databento_6e_5m, feed:databento_6j_5m, feed:databento_btc_5m, feed:databento_cl_5m, feed:databento_dx_5m, feed:databento_es_5m, feed:databento_gc_5m, feed:databento_hg_5m, feed:databento_m2k_5m, feed:databento_mbt_5m, feed:databento_mcl_5m, feed:databento_mes_5m, feed:databento_mgc_5m, feed:databento_mnq_5m, feed:databento_mym_5m, feed:databento_ng_5m, feed:databento_nq_5m, feed:databento_pa_5m, feed:databento_pl_5m, feed:databento_rty_5m, feed:databento_si_5m, feed:databento_sil_5m, feed:databento_sr3_5m, feed:databento_vxm_5m, feed:databento_ym_5m, feed:databento_zb_5m, feed:databento_zc_5m, feed:databento_zf_5m, feed:databento_zn_5m, feed:databento_zs_5m, feed:databento_zt_5m, feed:databento_zw_5m, feed:ethusdt_5m, feed:fred_dff, feed:fred_dgs10, feed:fred_dgs2, feed:fred_nasdaq100, feed:fred_t10y2y, feed:fred_vixcls, feed:treasury_auctions, feed:treasury_debt_to_penny, feed:treasury_operating_cash, fred_alfred, provider:fred, provider:massive, sec_edgar, workflow:cl-lab.yml, workflow:databento-depth-corpus.yml, workflow:depth-vault.yml, workflow:external-data-fabric.yml, workflow:interrepo-peer-intelligence.yml, workflow:native-five-research.yml, workflow:native-provider-access.yml, workflow:official-economic-events.yml, workflow:provider-exhaustive-collection.yml, workflow:provider-supplemental-collection.yml, workflow:tests.yml

## Order-book data

Vaulted files: {'bars_primary': 33, 'bars_secondary': 2, 'bars_third': 1, 'corpus': 135, 'panel': 13, 'sweep': 10} (key: HKDF(DATABENTO_API_KEY)). Last vault decrypt/hash check: OK at 2026-10-23T08:42:28+00:00 with 0 failures. D1 status: {'D1-A': 'INSUFFICIENT_DATA', 'D1-B': 'INSUFFICIENT_DATA', 'days': 4}.

| Budget | Cap | Spent | Left |
|---|---|---|---|
| corpus__primary | $3.54 | $2.5 | $1.04 |
| corpus__secondary | $2.19 | $1.13 | $1.06 |
| depth__diversifier | $95.0 | $94.99 | $0.01 |
| depth__index | $93.0 | $92.99 | $0.01 |
| depth__sweep__primary | $34.34 | $34.32 | $0.03 |
| depth__sweep__secondary | $3.36 | $3.31 | $0.05 |
| depth__sweep__third | $12.0 | $11.87 | $0.13 |
| history__ES | $25.0 | $18.14 | $6.86 |
| history__NQ | $25.0 | $17.5 | $7.5 |

## Research

Champions: 0. Pulse variants: {'CANDLES': 'REJECTED', 'HA_HA_FILLS': 'ARTIFACT_REFERENCE', 'HA_REAL_FILLS': 'REJECTED'}. CL lab last run: 2026-10-24T00:10:42.190284+00:00.

## Coordination (Claude, ChatGPT, Atlas)

- claude: done 5, in progress 2, planned 9, waiting 1; awaiting its reply: 14; stale in-progress: X1, CL-84
- chatgpt: done 3, in progress 8, planned 5, waiting 9; awaiting its reply: 2; stale in-progress: X1-Codex, IB01, IB04, REVIEW01, A200, SYS22, C02, M01
- atlas: waiting 4; awaiting its reply: 2
- malformed messages: to-claude/20261011T213350Z-atlas-registry-checkpoint.md: to, date, reply-needed, file name; to-claude/20261013T2311Z-chatgpt-ib03-pr336-review.md: from, to, date, subject, reply-needed; to-claude/20261013T2327Z-chatgpt-ib03-pr336-final-head.md: from, to, date, subject, reply-needed; to-claude/20261013T2338Z-chatgpt-ib03-pr336-review.md: from, to, date, subject, reply-needed; to-claude/20261014T0003Z-chatgpt-ib03-pr336-head-update.md: from, to, date, subject, reply-needed; to-chatgpt/20261011T213350Z-atlas-registry-checkpoint.md: to, date, reply-needed, file name
