# ICARUS Data Gap Ledger

Verified during the federation-wide ingestion audit on 2026-10-16. This ledger separates ICARUS-owned plumbing gaps from provider/account/network/licensing limitations. A source is not considered closed merely because a key exists or a workflow starts.

## Status vocabulary

- **CLOSED_INTERNAL** — the ICARUS-side credential, transport, collection, persistence, health-monitoring, and shared-consumption path required by this audit has been implemented and verified.
- **LIVE_PARTIAL_RESUMABLE** — real data is being collected and the queue intentionally remains incomplete; future runs continue the catalog/pagination workload.
- **EXTERNAL_BLOCKER** — ICARUS plumbing reached the external boundary and the remaining blocker requires a credential replacement, provider entitlement, provider/network behavior, or owner-supplied secret.
- **DEDICATED_LANE** — data is collected through an existing specialized pipeline rather than the generic provider queue.
- **RUNTIME_CAPABILITY** — an opt-in/local runtime collector exists but is not evidence of always-on acquisition unless its runtime state says it is enabled.
- **CONNECTOR_ONLY** — source is available through an interactive connector/app rather than GitHub Actions; every AI unit must still know it exists and use it when that unit has the connector.
- **EVIDENCE_FABRIC** — internal specialist/cross-repository evidence that every AI unit must read when relevant even though it is not an external market-data API.

## GitHub-native provider plane

| Source | Credential | Ingestion / consumption | Audit result | Evidence / blocker |
|---|---|---|---|---|
| Massive/Polygon | present | live / live | CLOSED_INTERNAL | Existing exhaustive collector and shared provider research context. |
| Twelve Data | present | partial / live | LIVE_PARTIAL_RESUMABLE | Exhaustive catalog has pending work; resumable cursor state is intentional. |
| FMP | present | live / live | CLOSED_INTERNAL | Exhaustive collector plus external-data fabric. |
| EODHD | present | live / live | CLOSED_INTERNAL | Exhaustive collector plus external-data fabric; plan-limited capabilities remain explicit. |
| Tiingo | present | partial / live | LIVE_PARTIAL_RESUMABLE | Real data collected; remaining catalog work continues across runs. |
| FRED | present | live / live | CLOSED_INTERNAL | Exhaustive collector, FRED/ALFRED lane, native public macro lane and shared provider context. |
| Bybit | public | live / live | CLOSED_INTERNAL | Public read-only provider lane plus native research spot/linear context. |
| Unusual Whales | present, rejected | blocked / blocked | EXTERNAL_BLOCKER: BLOCKED_AUTHENTICATION | Credential presence is confirmed by redacted health run `38902710676`, but supplemental run `38902990406` received HTTP 401 on greek-exposure (0 rows), and native canary `38897165047` received HTTP 401 on market-tide. Earlier successful canary `38838224842` is historical evidence, not current access. Repair/replace the GitHub Actions credential or provider authorization. The separate main-repo interactive connector intake remains a distinct transport and does not make the Actions lane available. |
| Alpha Vantage | present | partial / partial | LIVE_PARTIAL_RESUMABLE + EXTERNAL_BLOCKER | Added scheduled collector and independent native canary. Accessible endpoints returned real data; two exercised endpoint families returned HTTP 403 under the current plan. ICARUS records those as entitlement gaps rather than success. |
| Finnhub | present but rejected | blocked / blocked | EXTERNAL_BLOCKER | Stored credential repeatedly returned HTTP 401 using both the prior query-token canary and documented `X-Finnhub-Token` header auth. Both supplemental and native canary transports now use fail-closed classification; replace/repair the GitHub Finnhub secret. |
| Intrinio | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`. Exhaustive endpoint/catalog machinery is present; add the credential to GitHub to activate it. |
| Quiver | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`. |
| Alpaca | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`; verified fail-closed. |
| Tickstream | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`. |

## Specialized and public data lanes

| Lane / source | State | Audit result | Evidence / blocker |
|---|---|---|---|
| Databento depth / order book | dedicated | DEDICATED_LANE + INTEGRITY_BLOCKED_PRIMARY_FEATURE_GAP | The integrity gate correctly refuses publication: the current vault has 135 corpus entries (68 secondary, 65 third, 2 lane manifests) and no primary feature entries; the derived context has 156,928 secondary/third feature rows only. Primary sweep `38862254022` recorded a 165-row partial-day purchase for 2026-10-15, but that feature file is now absent; later sweep `38885474677` made no new purchase. Vault recovery works via `HKDF(DATABENTO_API_KEY)` (`data/depth_vault/manifest.json`), so the missing standalone `ICARUS_DATA_ARCHIVE_KEY` is not the current blocker. The primary ledger has $34.317511 spent against $34.344215 allocated ($0.026704 remaining). Recover the already-paid feature source or record a separate recovery allocation; do not weaken the gate or spend beyond the ledger. |
| SEC/EDGAR | live | DEDICATED_LANE | Current audit observed `automation_intelligence/cl_lab/sec_edgar_manifest.json` with 15,931 fact rows and 2,375 filing rows across the configured large-cap universe. |
| Official economic events | live with fallback | DEDICATED_LANE + EXTERNAL_BLOCKER | BLS/BEA/Census/FOMC pipeline exists. BLS live ICS/HTML returns HTTP 403 from GitHub-hosted runners; the pipeline explicitly preserves an official BLS snapshot fallback rather than claiming live freshness. |
| External data fabric | live with plan limits | DEDICATED_LANE | EODHD, FMP and Tiingo outputs are present; provider-plan denials remain explicit. |
| Native five research | live hourly | CLOSED_INTERNAL | `native-five-research.yml` acquires Coinbase BTC spot, Kraken BTC spot, Bybit spot/linear, Federal Reserve/ECB/BLS release feeds and public FRED rates/DXY-proxy series. `automation_intelligence/native_research_v1/latest.json` currently reports all five research lanes verified/substantive. |
| CL lab public fabric | live | CLOSED_INTERNAL | `cl-lab.yml` / `cl_lab/feeds/registry.py` cover Binance public bulk, Coinbase, FRED/ALFRED, Cboe VIX-family indices, CFTC TFF/disaggregated positioning, U.S. Treasury FiscalData, and a broad Databento futures/context universe. |
| Coinbase public | live in multiple lanes | CLOSED_INTERNAL | Engine public feed, CL lab and native research surfaces are represented in the shared manifest. |
| Kraken public | live | CLOSED_INTERNAL | Engine fallback feed and native research surface represented in the shared manifest. |
| Binance public bulk | live | CLOSED_INTERNAL | CL lab registry and derived feed manifest. |
| Cboe volatility indices | live | CLOSED_INTERNAL | CL lab Cboe history collector/manifest. |
| CFTC positioning | live | CLOSED_INTERNAL | CL lab TFF/disaggregated feeds plus opt-in runtime public-source collector. |
| U.S. Treasury fiscal | live | CLOSED_INTERNAL | CL lab FiscalData feeds. |
| Fed / ECB / BLS release feeds | live with source-specific limits | CLOSED_INTERNAL + EXTERNAL source limits | Native research preserves official source evidence; BLS cloud-runner behavior remains explicit. |
| Provider research context | shared | CLOSED_INTERNAL | `tools/provider_research_context.py` discovers provider `latest/*.json` receipts automatically. Supplemental provider summaries enter the same shared context after safe promotion. |
| Inter-repo peer intelligence | live | EVIDENCE_FABRIC | `interrepo-peer-intelligence.yml` exports `automation_intelligence/interrepo/latest.json` and checks canonical Icarus acceptance evidence. |

## Runtime-only collection capabilities

`icarus_engine/market_sources.py` exposes bounded public collection for CFTC, BLS, Federal Reserve, BEA, SEC, Coinbase and Yahoo DXY. `icarus_engine/source_watch.py` can poll those sources with durable claims but is **disabled by default**. This is a RUNTIME_CAPABILITY, not proof of continuous collection. Every AI unit must consult runtime status before saying SourceWatch is active.

Engine feeds under `icarus_engine/feeds/**` also provide keyless Coinbase/Kraken data and delayed Yahoo futures bars. Yahoo's own documented/observed delay and per-interval history limits remain part of the source qualification; they must not be relabeled as real-time depth/order-flow data.

## Internal specialist evidence fabric

The following persisted evidence is part of the shared ICARUS context and must not remain siloed by AI account:

| Evidence lane | Current audit state | Shared evidence |
|---|---|---|
| Robustness Guardian | active persisted | `automation_intelligence/agent_fabric/robustness_guardian/**` |
| Advanced CSV | active persisted, cross-repo | `reppiks490/icarus-csv-evidence-lab:automation_intelligence/advanced_csv/**` |
| Alpha Synthesis | active persisted | `automation_intelligence/agent_fabric/alpha_synthesis/**` |
| Flow Microstructure | active persisted | `automation_intelligence/flow/**` |
| Apex Council | active persisted | `automation_intelligence/agent_fabric/apex_council/**` |
| MCP evidence bus | canonical | `automation_intelligence/mcp_interface/events/**`, `research_runs/**` |
| Coordination fabric | mandatory session context | `coordination/**` plus the agent handoff documents |

Read access is federation-wide; write ownership remains governed by the coordination boards unless the owner explicitly overrides it to close a verified gap.

## Unusual Whales surface that all AI units must account for

The scheduled API-token lane is intentionally broader than a single options-flow endpoint and coexists with the main Icarus connector intake. Subject to the owner's actual subscription entitlements and rate limits, the pinned catalog covers market daily report, market tide, net flow / zero-DTE flow, stock screener, GEX levels, greek exposure, per-minute spot exposure, exposure by strike, greek flow, net premium ticks, NOPE, recent and ticker dark-pool trades, dark-pool price levels, earnings, insider flow, congressional unusual trades, crypto token metadata, crypto candles and crypto trades.

The main `reppiks490/Icarus` connector intake provides an additional interactive observation transport spanning options flow, GEX/greeks, dark/lit flow, earnings/analysts, financial statements, insider/institutional activity, macro/calendar, market/sector regimes, politics/public activity, prediction markets, technicals, seasonality, short interest/borrow, volatility/expiry and crypto. The two transports are complementary; neither proves the other's coverage, licensing or point-in-time eligibility.

## Connector-only federation surface

The canonical manifest keeps these sources visible to every AI even when a given unit lacks the connector: Bigdata, Financial Datasets, Coinversa/Hyperliquid, Crypto.com, CoinMarketCap, Quartr, LunarCrush, Firecrawl, Exa, Consensus, Wolfram, Hugging Face, Tavily, Blockscout and U.S. Gold Bureau. A unit with the connector should use it when relevant and preserve permitted derived evidence through ICARUS handoffs. A unit without it records a capability blocker and continues with the shared GitHub-native evidence; it must not silently erase the source from its reasoning model.

## Health-monitoring closure

The audit found that the Data Sentinel did not initially monitor four newly relevant workflow lanes: supplemental provider collection, supplemental promotion, native-provider canary, and inter-repo peer intelligence. PR #178 adds these lanes to `tools/data_sentinel.py::WORKFLOWS`, adds event triggers in `data-sentinel.yml`, and makes the federation test fail if that coverage disappears. Freshness targets are 3 h for supplemental collection/promotion, 8 h for the 6-hour native canary, and 1 h for the 10-minute peer packet lane.

This Sentinel repair is not considered CLOSED_INTERNAL until the exact PR head and post-merge `main` verification are green.

## Federation rule

Every AI unit must read `config/data_ingestion_manifest.json`, `automation_intelligence/manifest.json`, `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`, `docs/agent-handoffs/DATA_GAP_LEDGER.md`, current Sentinel health, and relevant coordination inbox/board state. New sources or newly discovered endpoint families must be represented at all three truth stages: credential availability, ingestion runtime state and downstream consumption state.

Any agent that discovers a credentialed-but-uncollected source, collected-but-unconsumed source, stale collector, incomplete pagination path, missing transport, health-monitor blind spot, specialist output invisible to peers, or new entitlement boundary has a standing obligation to close the ICARUS-owned gap or publish the exact external blocker.

## Completion gate

The ICARUS-owned data/federation architecture identified in this audit is considered fixed only after the supplemental collector, promoter, native canary, shared context, federation manifest/directive/ledger, Sentinel coverage, focused tests, full repository CI and post-merge Actions verification are green on `main`.

External blockers are intentionally **not** relabeled as fixed. They are closed only as diagnostic ambiguity: the system must identify exactly what must change outside ICARUS before data can flow. Zero known **internal** errors is the completion condition.


## Current staged Yahoo futures corpus access

The manifest tracks `yahoo_cme_futures_seed` as `STAGED`: 16 contracts at 1-minute resolution for 2026-09-17..2026-10-16 and at 1-hour resolution for 2024-10..2026-10. The archives exist in the current workspace and a Dropbox folder under parent `15245772211`, but access for every agent has not been verified. The manifest therefore marks shared consumption `BLOCKED` (`SHARING_UNVERIFIED`) rather than claiming federation-wide availability.
