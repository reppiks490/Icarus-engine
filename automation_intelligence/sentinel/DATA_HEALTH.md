# Data health — 2026-10-11 03:59 UTC

**FAILING** 5 · **BLOCKED** 7 · **DEGRADED** 4 · **OK** 63

## Needs attention

| Source | Verdict | Why |
|---|---|---|
| feed:databento_dx_5m | FAILING | FeedError: Databento cost estimate failed for DX.v.0: BentoClientError: 422 data_end_after_available_end The dataset IFUS.IMPACT has data available up to '2026- |
| feed:databento_vxm_5m | FAILING | FeedError: Databento cost estimate failed for VXM.v.0: BentoClientError: 422 data_end_after_available_end The dataset XCBF.PITCH has data available up to '2026- |
| workflow:cl-lab.yml | FAILING | latest run failure: https://github.com/reppiks490/Icarus-engine/actions/runs/38098381290 |
| workflow:databento-depth-research-context.yml | FAILING | latest run failure: https://github.com/reppiks490/Icarus-engine/actions/runs/38110054086 |
| workflow:sec-edgar-data.yml | FAILING | latest run failure: https://github.com/reppiks490/Icarus-engine/actions/runs/38095178688 |
| provider:alpaca | BLOCKED | no key reaches the runner |
| provider:intrinio | BLOCKED | no key reaches the runner |
| provider:massive | BLOCKED | no key reaches the runner |
| provider:quiver | BLOCKED | no key reaches the runner |
| provider:tickstream | BLOCKED | no key reaches the runner |
| provider:twelve | BLOCKED | no key reaches the runner |
| sec_edgar | BLOCKED | SEC_USER_AGENT is required for SEC fair-access requests; set the GitHub Actions repository variable to a declared identity such as 'ICARUS Research contact@example.com' |
| provider:bybit | DEGRADED | no key; keyless endpoints only, none ready |
| provider:eodhd | DEGRADED | 68183 rows; 29 endpoints denied by plan |
| provider:fmp | DEGRADED | key present but 0 rows (COLLECTED_PARTIAL) |
| provider:tiingo | DEGRADED | 1 rows; 4 endpoints denied by plan |

## Delivering

economic_events, feed:btcusd_cb_5m, feed:btcusdt_5m, feed:cboe_skew, feed:cboe_vix, feed:cboe_vix3m, feed:cboe_vix9d, feed:cboe_vvix, feed:cftc_disaggregated_all, feed:cftc_tff_all, feed:cftc_tff_nasdaq, feed:databento_6a_5m, feed:databento_6b_5m, feed:databento_6e_5m, feed:databento_6j_5m, feed:databento_btc_5m, feed:databento_cl_5m, feed:databento_es_5m, feed:databento_gc_5m, feed:databento_hg_5m, feed:databento_m2k_5m, feed:databento_mbt_5m, feed:databento_mcl_5m, feed:databento_mes_5m, feed:databento_mgc_5m, feed:databento_mnq_5m, feed:databento_mym_5m, feed:databento_ng_5m, feed:databento_nq_5m, feed:databento_pa_5m, feed:databento_pl_5m, feed:databento_rty_5m, feed:databento_si_5m, feed:databento_sil_5m, feed:databento_sr3_5m, feed:databento_ym_5m, feed:databento_zb_5m, feed:databento_zc_5m, feed:databento_zf_5m, feed:databento_zn_5m, feed:databento_zs_5m, feed:databento_zt_5m, feed:databento_zw_5m, feed:ethusdt_5m, feed:fred_dff, feed:fred_dgs10, feed:fred_dgs2, feed:fred_nasdaq100, feed:fred_t10y2y, feed:fred_vixcls, feed:treasury_auctions, feed:treasury_debt_to_penny, feed:treasury_operating_cash, fred_alfred, provider:fred, workflow:cl-depth-sweep.yml, workflow:databento-depth-corpus.yml, workflow:depth-vault.yml, workflow:external-data-fabric.yml, workflow:native-five-research.yml, workflow:official-economic-events.yml, workflow:provider-exhaustive-collection.yml, workflow:tests.yml

## Order-book data

Vaulted files: {'corpus': 133} (key: HKDF(DATABENTO_API_KEY)). D1 status: {'D1-A': 'INSUFFICIENT_DATA', 'D1-B': 'INSUFFICIENT_DATA', 'days': 0}.

| Budget | Cap | Spent | Left |
|---|---|---|---|
| corpus__primary | $11.33 | $0.82 | $10.51 |
| corpus__secondary | $3.56 | $0.0 | $3.56 |
| depth__diversifier | $95.0 | $94.99 | $0.01 |
| depth__index | $93.0 | $92.97 | $0.03 |
| depth__sweep__primary | $35.04 | $26.53 | $8.51 |
| depth__sweep__secondary | $4.0 | $1.94 | $2.06 |
| depth__sweep__third | $12.0 | $5.96 | $6.04 |
| history__ES | $25.0 | $18.14 | $6.86 |
| history__NQ | $25.0 | $17.5 | $7.5 |

## Research

Champions: 0. Pulse variants: {'CANDLES': 'REJECTED', 'HA_HA_FILLS': 'ARTIFACT_REFERENCE', 'HA_REAL_FILLS': 'REJECTED'}. CL lab last run: 2026-10-10T07:55:42.337492+00:00.
