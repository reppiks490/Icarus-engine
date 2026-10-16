# ICARUS Data Gap Ledger

Verified during the federation-wide ingestion audit on 2026-10-16. This ledger separates ICARUS-owned plumbing gaps from provider/account/network limitations. A source is not considered closed merely because a key exists or a workflow starts.

## Status vocabulary

- **CLOSED_INTERNAL** — the ICARUS-side credential, transport, collection, persistence, and shared-consumption path required by this audit has been implemented and verified.
- **LIVE_PARTIAL_RESUMABLE** — real data is being collected and the queue intentionally remains incomplete; future runs continue the catalog/pagination workload.
- **EXTERNAL_BLOCKER** — ICARUS plumbing reached the external boundary and the remaining blocker requires a credential replacement, provider entitlement, provider/network behavior, or owner-supplied secret.
- **DEDICATED_LANE** — data is collected through an existing specialized pipeline rather than the generic provider queue.
- **CONNECTOR_ONLY** — source is available through an interactive connector/app rather than GitHub Actions; every AI unit must still know it exists and use it when that unit has the connector.

## GitHub-native provider plane

| Source | Credential | Ingestion / consumption | Audit result | Evidence / blocker |
|---|---|---|---|---|
| Massive/Polygon | present | live / live | CLOSED_INTERNAL | Existing exhaustive collector and shared provider research context. |
| Twelve Data | present | partial / live | LIVE_PARTIAL_RESUMABLE | Exhaustive catalog has pending work; resumable cursor state is intentional. |
| FMP | present | live / live | CLOSED_INTERNAL | Exhaustive collector plus external-data fabric. |
| EODHD | present | live / live | CLOSED_INTERNAL | Exhaustive collector plus external-data fabric; plan-limited capabilities remain explicit. |
| Tiingo | present | partial / live | LIVE_PARTIAL_RESUMABLE | Real data collected; remaining catalog work continues across runs. |
| FRED | present | live / live | CLOSED_INTERNAL | Exhaustive collector and shared provider context. |
| Bybit | public | live / live | CLOSED_INTERNAL | Public read-only provider lane is live. |
| Unusual Whales | present | partial / partial | LIVE_PARTIAL_RESUMABLE / INTERNAL GAP CLOSED | Added official endpoint catalog, GitHub-native scheduled collector, hardened UW-specific pagination, transient encrypted/raw handling, safe promoter, and shared research-context path. Final isolated canary run `38838224842` completed 5 requests / 5 pages, discovered 500 assets, and left 16 catalog operations pending without the prior transport `ValueError`. The main `reppiks490/Icarus` runtime also has broad connector observation intake in `icarus_engine/unusual_whales_intake.py`. |
| Alpha Vantage | present | partial / partial | LIVE_PARTIAL_RESUMABLE + EXTERNAL_BLOCKER | Added to supplemental scheduled collector. Run `38838224842` returned real data; two exercised endpoint families returned HTTP 403 under the current plan. ICARUS records those as entitlement gaps rather than success. |
| Finnhub | present but rejected | blocked / blocked | EXTERNAL_BLOCKER | Stored Finnhub credential repeatedly returned HTTP 401 using both prior query-token auth and documented `X-Finnhub-Token` auth. Replace/repair the GitHub Finnhub secret. The ICARUS transport itself is implemented and fail-closed. |
| Intrinio | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`. Exhaustive endpoint/catalog machinery is already present; add the credential to GitHub to activate it. |
| Quiver | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`. |
| Alpaca | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`; verified fail-closed. |
| Tickstream | missing | blocked / blocked | EXTERNAL_BLOCKER | `BLOCKED_MISSING_CREDENTIAL`. |

## Specialized data lanes

| Lane | State | Audit result | Evidence / blocker |
|---|---|---|---|
| Databento depth / order book | dedicated | DEDICATED_LANE + EXTERNAL_BLOCKER | Databento credentials are present and dedicated corpus/depth workflows exist. The research-context integrity gate correctly refuses incomplete primary-depth context when primary features are unavailable. `ICARUS_DATA_ARCHIVE_KEY` is absent, so encrypted archive recovery cannot refill that gap. Do not weaken the gate. |
| SEC/EDGAR | live | DEDICATED_LANE | Current audit observed `automation_intelligence/cl_lab/sec_edgar_manifest.json` with 15,931 fact rows and 2,375 filing rows across the configured large-cap universe. |
| Official economic events | live with fallback | DEDICATED_LANE + EXTERNAL_BLOCKER | BEA, Census and FOMC are live first-party sources. BLS live ICS/HTML returns HTTP 403 from GitHub-hosted runners; the pipeline explicitly falls back to an official BLS snapshot rather than claiming live freshness. |
| External data fabric | live with plan limits | DEDICATED_LANE | EODHD, FMP and Tiingo outputs are present; provider-plan denials remain explicit. |
| Provider research context | shared | CLOSED_INTERNAL | `tools/provider_research_context.py` discovers provider `latest/*.json` receipts automatically. Supplemental provider summaries therefore enter the same shared context as K1 providers after promotion. |
| Data sentinel | shared | CLOSED_INTERNAL | Existing sentinel operates on the same provider receipt family, so supplemental providers do not require a parallel downstream format. |

## Unusual Whales surface that all AI units must account for

The scheduled API-token lane is intentionally broader than a single options-flow endpoint and coexists with the main Icarus connector intake. Subject to the owner's actual subscription entitlements and rate limits, the pinned catalog covers market daily report, market tide, net flow / zero-DTE flow, stock screener, GEX levels, greek exposure, per-minute spot exposure, exposure by strike, greek flow, net premium ticks, NOPE, recent and ticker dark-pool trades, dark-pool price levels, earnings, insider flow, congressional unusual trades, crypto token metadata, crypto candles and crypto trades.

The main `reppiks490/Icarus` connector intake provides an additional interactive observation transport spanning options flow, GEX/greeks, dark/lit flow, earnings/analysts, financial statements, insider/institutional activity, macro/calendar, market/sector regimes, politics/public activity, prediction markets, technicals, seasonality, short interest/borrow, volatility/expiry and crypto. The two transports are complementary; neither should cause an AI unit to ignore the other.

## Connector-only federation surface

The canonical manifest also keeps these sources visible to every AI even when a given unit lacks the connector: Bigdata, Financial Datasets, Coinversa/Hyperliquid, Crypto.com, CoinMarketCap, Quartr, LunarCrush, Firecrawl, Exa, Consensus, Wolfram, Hugging Face, Tavily, Blockscout and U.S. Gold Bureau. A unit with the connector should use it when relevant and preserve permitted derived evidence through ICARUS handoffs. A unit without it records a capability blocker and continues with the shared GitHub-native evidence; it must not silently erase the source from its reasoning model.

## Federation rule

Every AI unit must read `config/data_ingestion_manifest.json` and `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`. New sources or newly discovered endpoint families must be represented at all three truth stages: credential availability, ingestion runtime state and downstream consumption state. Any agent that discovers a credentialed-but-uncollected source, collected-but-unconsumed source, stale collector, incomplete pagination path, missing transport or new entitlement boundary has a standing obligation to close the ICARUS-owned gap or publish the exact external blocker.

## What is and is not "fixed"

The ICARUS-owned missing-provider architecture identified in this audit is considered fixed only after the supplemental collector, promoter, shared context, federation manifest, tests and post-merge Actions verification are green on `main`. External blockers above are intentionally **not** relabeled as fixed. They are closed as diagnostic ambiguity: the system now identifies exactly what must change outside ICARUS before data can flow.
