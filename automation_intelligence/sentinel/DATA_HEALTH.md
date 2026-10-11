# Data health — 2026-10-11 15:49 UTC

**FAILING** 3 · **BLOCKED** 5 · **STALE** 1 · **DEGRADED** 4 · **OK** 66

## Needs attention

| Source | Verdict | Why |
|---|---|---|
| feed:databento_dx_5m | FAILING | FeedError: Databento historical request failed for DX.v.0: BentoClientError: 422 dataset_unavailable_range Part or all of your request for dataset 'IFUS.IMPACT' |
| feed:databento_vxm_5m | FAILING | FeedError: Databento historical request failed for VXM.v.0: BentoClientError: 403 license_not_found_unauthorized A live data license is required to access XCBF. |
| workflow:databento-depth-research-context.yml | FAILING | latest run failure: https://github.com/reppiks490/Icarus-engine/actions/runs/38136348392 |
| provider:alpaca | BLOCKED | no key reaches the runner |
| provider:intrinio | BLOCKED | no key reaches the runner |
| provider:quiver | BLOCKED | no key reaches the runner |
| provider:tickstream | BLOCKED | no key reaches the runner |
| provider:twelve | BLOCKED | BLOCKED |
| workflow:sec-edgar-data.yml | STALE | last success 3.1 h ago (expected within 3 h) |
| provider:bybit | DEGRADED | no key; keyless endpoints only, none ready |
| provider:eodhd | DEGRADED | key present but 0 rows (COLLECTED_PARTIAL) |
| provider:fmp | DEGRADED | 567 rows; 85 endpoints denied by plan |
| provider:tiingo | DEGRADED | 2 rows; 4 endpoints denied by plan |

## Delivering

economic_events, feed:btcusd_cb_5m, feed:btcusdt_5m, feed:cboe_skew, feed:cboe_vix, feed:cboe_vix3m, feed:cboe_vix9d, feed:cboe_vvix, feed:cftc_disaggregated_all, feed:cftc_tff_all, feed:cftc_tff_nasdaq, feed:databento_6a_5m, feed:databento_6b_5m, feed:databento_6e_5m, feed:databento_6j_5m, feed:databento_btc_5m, feed:databento_cl_5m, feed:databento_es_5m, feed:databento_gc_5m, feed:databento_hg_5m, feed:databento_m2k_5m, feed:databento_mbt_5m, feed:databento_mcl_5m, feed:databento_mes_5m, feed:databento_mgc_5m, feed:databento_mnq_5m, feed:databento_mym_5m, feed:databento_ng_5m, feed:databento_nq_5m, feed:databento_pa_5m, feed:databento_pl_5m, feed:databento_rty_5m, feed:databento_si_5m, feed:databento_sil_5m, feed:databento_sr3_5m, feed:databento_ym_5m, feed:databento_zb_5m, feed:databento_zc_5m, feed:databento_zf_5m, feed:databento_zn_5m, feed:databento_zs_5m, feed:databento_zt_5m, feed:databento_zw_5m, feed:ethusdt_5m, feed:fred_dff, feed:fred_dgs10, feed:fred_dgs2, feed:fred_nasdaq100, feed:fred_t10y2y, feed:fred_vixcls, feed:treasury_auctions, feed:treasury_debt_to_penny, feed:treasury_operating_cash, fred_alfred, provider:fred, provider:massive, sec_edgar, workflow:cl-depth-sweep.yml, workflow:cl-lab.yml, workflow:databento-depth-corpus.yml, workflow:depth-vault.yml, workflow:external-data-fabric.yml, workflow:native-five-research.yml, workflow:official-economic-events.yml, workflow:provider-exhaustive-collection.yml, workflow:tests.yml

## Order-book data

Vaulted files: {'corpus': 133} (key: HKDF(DATABENTO_API_KEY)). D1 status: {'D1-A': 'INSUFFICIENT_DATA', 'D1-B': 'INSUFFICIENT_DATA', 'days': 0}.

| Budget | Cap | Spent | Left |
|---|---|---|---|
| corpus__primary | $11.33 | $0.82 | $10.51 |
| corpus__secondary | $3.56 | $0.3 | $3.26 |
| depth__diversifier | $95.0 | $94.99 | $0.01 |
| depth__index | $93.0 | $92.97 | $0.03 |
| depth__sweep__primary | $35.04 | $26.53 | $8.51 |
| depth__sweep__secondary | $4.0 | $1.94 | $2.06 |
| depth__sweep__third | $12.0 | $5.96 | $6.04 |
| history__ES | $25.0 | $18.14 | $6.86 |
| history__NQ | $25.0 | $17.5 | $7.5 |

## Research

Champions: 0. Pulse variants: {'CANDLES': 'REJECTED', 'HA_HA_FILLS': 'ARTIFACT_REFERENCE', 'HA_REAL_FILLS': 'REJECTED'}. CL lab last run: 2026-10-11T04:16:16.381568+00:00.

## Claude <-> ChatGPT

- claude: done 5, in progress 2, planned 9, waiting 1; awaiting its reply: 1
- chatgpt: blocked 1, in progress 6, planned 6, waiting 4; awaiting its reply: 3
