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
| Twelve Data | present | partial / live | LIVE_PARTIAL_RESUMABLE | Exhaustive catalog has pending work; resumable cursor state is intentional. The latest sampled slice can still fail closed when every attempted operation is denied/not found. |
| FMP | present | live / live | CLOSED_INTERNAL | Exhaustive collector plus external-data fabric. |
| EODHD | present | live / live | CLOSED_INTERNAL | Exhaustive collector plus external-data fabric; plan-limited capabilities remain explicit. |
| Tiingo | present | partial / live | LIVE_PARTIAL_RESUMABLE | Real data collected; remaining catalog work continues across runs. |
| FRED | present | live / live | CLOSED_INTERNAL | Exhaustive collector, FRED/ALFRED lane, native public macro lane and shared provider context. |
| Bybit | public | live / live | CLOSED_INTERNAL | Public read-only provider lane plus native research spot/linear context. Secondary-repository jobs may correctly emit `STANDBY_PREFERRED_OWNER` rather than duplicate collection. |
| Unusual Whales | present | partial / partial | LIVE_PARTIAL_RESUMABLE / INTERNAL GAP CLOSED | Added official endpoint catalog, GitHub-native scheduled collector, hardened UW-specific pagination, encrypted/raw handling, safe promoter, shared research-context path and independent native canary. Canary run `38838224842` completed 5 requests / 5 pages, discovered 500 assets, and left catalog operations pending without the prior transport `ValueError`. The main `reppiks490/Icarus` runtime also has metadata-only connector observation intake. |
| Alpha Vantage | present | partial / partial | LIVE_PARTIAL_RESUMABLE + EXTERNAL_BLOCKER | Added scheduled collector and independent native canary. Accessible endpoints returned real data; two exercised endpoint families returned HTTP 403 under the current plan. ICARUS records those as entitlement gaps rather than success. |
| Finnhub | present but rejected | blocked / blocked | EXTERNAL_BLOCKER | Stored credential repeatedly returned HTTP 401 using both the prior query-token canary and documented `X-Finnhub-Token` header auth. Both supplemental and native canary transports use fail-closed classification; replace/repair the GitHub Finnhub secret. |
| Intrinio | present in preferred `reppiks490/Icarus`, rejected | blocked / blocked | EXTERNAL_BLOCKER | Latest preferred-repository run `38865138563` (receipt `provider-intrinio-38865138563-1`, completed 2026-10-16 07:07:33Z) reached the real Intrinio collector with the credential present, issued a bounded request to `/companies`, and received HTTP 401 with zero collected rows (`BLOCKED_AUTHENTICATION`). The earlier run `38861416940` is superseded. The GitHub-native cross-repo plumbing is working; repair the preferred repository's credential or account authorization rather than adding another collector. |
| Quiver | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`. |
| Alpaca | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`; verified fail-closed. |
| Tickstream | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`. |

## Specialized and public data lanes

| Lane / source | State | Audit result | Evidence / blocker |
|---|---|---|---|
| Databento depth / order book | dedicated | DEDICATED_LANE + INTEGRITY_BLOCKER | Databento credentials and dedicated corpus/depth workflows are present. The primary sweep receipt reports `status: OK` and one bought partial-day slice for 2026-10-15 (165 feature rows, generated 2026-10-16 06:38:48Z), alongside 21 held days. A later research-context publication attempt failed its integrity gate because complete primary-depth coverage is still absent; valid secondary/third account features and cached files do not replace that missing primary coverage. Do not weaken the gate or buy data merely to turn health green. |
| SEC/EDGAR | live pipeline | DEDICATED_LANE | Current audit observed `automation_intelligence/cl_lab/sec_edgar_manifest.json` with 15,931 fact rows and 2,375 filing rows across the configured large-cap universe. Cadence repair PR #190 is merged. Post-merge SEC run `38864917807` succeeded on 2026-10-16; continued long-term freshness still requires more scheduled observations. |
| Official economic events | live with fallback | DEDICATED_LANE + EXTERNAL_BLOCKER | BLS/BEA/Census/FOMC pipeline exists. BLS live ICS/HTML returns HTTP 403 from GitHub-hosted runners; the pipeline explicitly preserves an official BLS snapshot fallback rather than claiming live freshness. |
| External data fabric | live with plan limits | DEDICATED_LANE | EODHD, FMP and Tiingo outputs are present; provider-plan denials remain explicit. Sentinel PR #187 is merged and runtime-proven to aggregate this dedicated delivery without hiding generic-sampler denials. |
| Native five research | live pipeline | CLOSED_INTERNAL data path | `native-five-research.yml` acquires Coinbase BTC spot, Kraken BTC spot, Bybit spot/linear, Federal Reserve/ECB/BLS release feeds and public FRED rates/DXY-proxy series. Cadence repair PR #190 is merged; post-merge Native Five run `38863768170` succeeded on 2026-10-16. Continued long-term freshness still requires more scheduled observations. |
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

The audit originally found Sentinel blind spots and later a provider-classification error. PR #178 expanded monitored workflow coverage, and PR #187 (`cfa66db5af672f7ff869487a2f67cb78f7b77ca0`) fixed false provider `BLOCKED` classifications when the dedicated external-data fabric is delivering. The post-merge Sentinel rebuilt at `2026-10-16T06:36:48Z`, correctly reporting FMP/EODHD as `DEGRADED` with dedicated call counts and plan denials preserved. Missing credentials remain `BLOCKED`.

## Federation rule

Every AI unit must read `config/data_ingestion_manifest.json`, `automation_intelligence/manifest.json`, `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`, `docs/agent-handoffs/DATA_GAP_LEDGER.md`, current Sentinel health, and relevant coordination inbox/board state. New sources or newly discovered endpoint families must be represented at all three truth stages: credential availability, ingestion runtime state and downstream consumption state.

Any agent that discovers a credentialed-but-uncollected source, collected-but-unconsumed source, stale collector, incomplete pagination path, missing transport, health-monitor blind spot, specialist output invisible to peers, or new entitlement boundary has a standing obligation to close the ICARUS-owned gap or publish the exact external blocker.

## Completion gate

The ICARUS-owned data/federation architecture identified in this audit is considered fixed only after the supplemental collector, promoter, native canary, shared context, federation manifest/directive/ledger, Sentinel coverage, focused tests, full repository CI and post-merge Actions verification are green on `main`.

External blockers are intentionally **not** relabeled as fixed. They are closed only as diagnostic ambiguity: the system must identify exactly what must change outside ICARUS before data can flow. Zero known **internal** errors is the completion condition.
