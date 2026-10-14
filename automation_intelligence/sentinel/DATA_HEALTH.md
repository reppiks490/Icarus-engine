# Data health — 2026-10-14 02:48 UTC

**FAILING** 2 · **BLOCKED** 4 · **STALE** 1 · **DEGRADED** 5 · **OK** 67

## Needs attention

| Source | Verdict | Why |
|---|---|---|
| workflow:databento-depth-research-context.yml | FAILING | latest run failure: https://github.com/reppiks490/Icarus-engine/actions/runs/38493059194 |
| workflow:tests.yml | FAILING | latest run cancelled: https://github.com/reppiks490/Icarus-engine/actions/runs/38502789975 |
| provider:alpaca | BLOCKED | no key reaches the runner |
| provider:intrinio | BLOCKED | no key reaches the runner |
| provider:quiver | BLOCKED | no key reaches the runner |
| provider:tickstream | BLOCKED | no key reaches the runner |
| workflow:provider-exhaustive-collection.yml | STALE | last success 3.4 h ago (expected within 3 h) |
| provider:bybit | DEGRADED | no key; keyless endpoints only, none ready |
| provider:eodhd | DEGRADED | 4309 rows; 29 endpoints denied by plan |
| provider:fmp | DEGRADED | 81 rows; 85 endpoints denied by plan |
| provider:tiingo | DEGRADED | 2 rows; 4 endpoints denied by plan |
| provider:twelve | DEGRADED | key present but 0 rows (COLLECTED_PARTIAL) |

## Delivering

economic_events, feed:btcusd_cb_5m, feed:btcusdt_5m, feed:cboe_skew, feed:cboe_vix, feed:cboe_vix3m, feed:cboe_vix9d, feed:cboe_vvix, feed:cftc_disaggregated_all, feed:cftc_tff_all, feed:cftc_tff_nasdaq, feed:databento_6a_5m, feed:databento_6b_5m, feed:databento_6e_5m, feed:databento_6j_5m, feed:databento_btc_5m, feed:databento_cl_5m, feed:databento_dx_5m, feed:databento_es_5m, feed:databento_gc_5m, feed:databento_hg_5m, feed:databento_m2k_5m, feed:databento_mbt_5m, feed:databento_mcl_5m, feed:databento_mes_5m, feed:databento_mgc_5m, feed:databento_mnq_5m, feed:databento_mym_5m, feed:databento_ng_5m, feed:databento_nq_5m, feed:databento_pa_5m, feed:databento_pl_5m, feed:databento_rty_5m, feed:databento_si_5m, feed:databento_sil_5m, feed:databento_sr3_5m, feed:databento_vxm_5m, feed:databento_ym_5m, feed:databento_zb_5m, feed:databento_zc_5m, feed:databento_zf_5m, feed:databento_zn_5m, feed:databento_zs_5m, feed:databento_zt_5m, feed:databento_zw_5m, feed:ethusdt_5m, feed:fred_dff, feed:fred_dgs10, feed:fred_dgs2, feed:fred_nasdaq100, feed:fred_t10y2y, feed:fred_vixcls, feed:treasury_auctions, feed:treasury_debt_to_penny, feed:treasury_operating_cash, fred_alfred, provider:fred, provider:massive, sec_edgar, workflow:cl-depth-sweep.yml, workflow:cl-lab.yml, workflow:databento-depth-corpus.yml, workflow:depth-vault.yml, workflow:external-data-fabric.yml, workflow:native-five-research.yml, workflow:official-economic-events.yml, workflow:sec-edgar-data.yml

## Order-book data

Vaulted files: {'corpus': 135} (key: HKDF(DATABENTO_API_KEY)). D1 status: {'D1-A': 'INSUFFICIENT_DATA', 'D1-B': 'INSUFFICIENT_DATA', 'days': 0}.

| Budget | Cap | Spent | Left |
|---|---|---|---|
| corpus__primary | $9.83 | $1.09 | $8.74 |
| corpus__secondary | $3.56 | $0.39 | $3.17 |
| depth__diversifier | $95.0 | $94.99 | $0.01 |
| depth__index | $93.0 | $92.99 | $0.01 |
| depth__sweep__primary | $34.88 | $28.03 | $6.85 |
| depth__sweep__secondary | $4.0 | $1.94 | $2.06 |
| depth__sweep__third | $12.0 | $5.96 | $6.04 |
| history__ES | $25.0 | $18.14 | $6.86 |
| history__NQ | $25.0 | $17.5 | $7.5 |

## Research

Champions: 0. Pulse variants: {'CANDLES': 'REJECTED', 'HA_HA_FILLS': 'ARTIFACT_REFERENCE', 'HA_REAL_FILLS': 'REJECTED'}. CL lab last run: 2026-10-14T00:52:53.559344+00:00.

## Claude <-> ChatGPT

- claude: done 5, in progress 2, planned 9, waiting 1; awaiting its reply: 9
- chatgpt: blocked 1, done 1, in progress 6, planned 5, waiting 6; awaiting its reply: 2
- malformed messages: to-claude/20261011T213350Z-atlas-registry-checkpoint.md: to, date, reply-needed, file name; to-claude/20261013T2311Z-chatgpt-ib03-pr336-review.md: from, to, date, subject, reply-needed; to-claude/20261013T2327Z-chatgpt-ib03-pr336-final-head.md: from, to, date, subject, reply-needed; to-claude/20261013T2338Z-chatgpt-ib03-pr336-review.md: from, to, date, subject, reply-needed; to-claude/20261014T0003Z-chatgpt-ib03-pr336-head-update.md: from, to, date, subject, reply-needed; to-chatgpt/20261011T213350Z-atlas-registry-checkpoint.md: to, date, reply-needed, file name
