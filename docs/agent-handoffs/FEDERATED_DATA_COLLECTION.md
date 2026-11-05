# ICARUS Federated Data Collection Directive

## Mandatory directive for every AI unit

Every AI unit working on ICARUS — ChatGPT, Codex, Claude, Atlas, local agents, scheduled GitHub-native agents, and future units — must operate from the same shared data and evidence plane. No unit may assume that a provider, dataset, research context, collector, subsystem, specialist output, peer packet, or evidence source is "someone else's data" and silently omit it.

The canonical source/access ledger is `config/data_ingestion_manifest.json`. Read it together with `ICARUS_STATE.md`, `automation_intelligence/manifest.json`, and `docs/agent-handoffs/DATA_GAP_LEDGER.md` at the beginning of work that can be affected by market, macro, order-flow, options, fundamental, alternative, economic, event, news, filing, on-chain, specialist-agent, or research evidence.

## Required shared surfaces

Every AI unit must account for all applicable parts of the ICARUS evidence plane, including:

- `ICARUS_STATE.md` — system truth and ownership boundaries.
- `config/data_ingestion_manifest.json` — canonical source/access/collection/consumption ledger.
- `config/credential_contract.json` — canonical GitHub-native credential names and aliases.
- `automation_intelligence/manifest.json` — internal specialist/engine topology and evidence locations.
- `.github/workflows/provider-exhaustive-collection.yml` — existing resumable provider acquisition.
- `.github/workflows/provider-supplemental-collection.yml` — additive acquisition for credentialed providers that were missing from the K1 matrix.
- `.github/workflows/native-provider-access.yml` — bounded independent credential/provider canary for Alpha Vantage, Finnhub, and Unusual Whales.
- `automation_intelligence/provider_collection_v1/research_context.json` — safe aggregated provider context.
- `.github/workflows/native-five-research.yml` and `automation_intelligence/native_research_v1/**` — hourly native research using Coinbase, Kraken, Bybit, Fed, ECB, BLS, and public FRED evidence.
- `.github/workflows/cl-lab.yml` and `automation_intelligence/cl_lab/**` — CL research fabric including Binance public bulk, Coinbase, FRED/ALFRED, Cboe volatility indices, CFTC positioning, U.S. Treasury fiscal data, Databento futures/context, and related research outputs.
- Databento depth/order-book evidence and the encrypted depth-vault lanes.
- SEC/EDGAR filings and derived filing evidence.
- Official BLS/BEA/Census/FOMC economic-event collection and macro event evidence.
- External data fabric outputs from FMP, EODHD, and Tiingo.
- Unusual Whales options flow, GEX/greeks, dark pool, market tide, earnings, insider/congress, stock screener and crypto surfaces when entitled.
- Massive/Polygon, Twelve Data, FMP, EODHD, Tiingo, FRED, Alpha Vantage, Finnhub, Bybit and every other provider admitted by the manifest.
- The opt-in runtime research collector `icarus_engine/market_sources.py` / `icarus_engine/source_watch.py`, which can acquire CFTC, BLS, Federal Reserve, BEA, SEC, Coinbase and `yahoo-dxy` evidence. SourceWatch is disabled by default; never describe it as running unless runtime state says it is enabled.
- The EIA spot-context snapshot in `reppiks490/Icarus:icarus_engine/data/research_context/` contains daily Brent, WTI, and Henry Hub observations for a read-only Financial & Data research panel. It is a fixed, SHA-256-pinned snapshot with no refresh workflow; the manifest records it as staged content and evidence-only consumption. It is not a futures feed, strategy feature, qualification input, or order input. Other candidates from the attached DataHub catalog remain unavailable or quarantined until their upstream rights and data semantics are resolved.
- Engine market feeds under `icarus_engine/feeds/**`, including public Coinbase/Kraken and delayed Yahoo futures bars where those feeds are actually selected by runtime configuration.
- `automation_intelligence/interrepo/latest.json` and the canonical Icarus acceptance packet used by the inter-repository federation bridge.
- Active specialist evidence from Robustness Guardian, Advanced CSV, Alpha Synthesis, Flow Microstructure, and Apex Council, including the cross-repo `reppiks490/icarus-csv-evidence-lab` evidence ledger.
- `automation_intelligence/mcp_interface/**` events/research runs and other source-qualified downstream evidence.
- `automation_intelligence/sentinel/data_health.json` and `DATA_HEALTH.md` for freshness/failure state. A source appearing in the ledger does not override a current Sentinel failure.
- Interactive connector-only sources recorded in the manifest when the current unit has that connector; if it does not, the unit records the capability blocker instead of pretending the source does not exist.
- Coordination inboxes, agent boards, research logs, MCP evidence events and any source-qualified downstream consumer artifacts relevant to the task.

## Three-stage truth model

A key existing is not the same as data being collected, and collected data is not the same as data being consumed. Every source is tracked separately as:

1. `credential_state`
2. `ingestion_state`
3. `consumption_state`

Do not claim a source is usable merely because a secret exists. Do not claim a source is collected merely because a workflow exists. Do not claim ICARUS is using a source unless runtime evidence shows that a downstream context/consumer can see it.

The same rule applies to internal evidence. A specialist heartbeat proves that lane persisted a run; it does not prove that every consumer incorporated the specialist's evidence. Cross-repo or connector availability must remain explicit.

## Runtime evidence rule

Do not claim a gap is closed without runtime evidence. Valid evidence includes a successful GitHub Actions job, a current provider `latest/*.json` receipt, a safe aggregated research-context row, a dedicated collector receipt, a persisted specialist heartbeat/finalization receipt, a current peer packet, or an explicit blocked/denied status that accurately identifies an external dependency.

A 401 is authentication failure. A 403/402 is entitlement/plan denial. A 429 is quota/rate-limit pause. Missing credentials remain `BLOCKED_MISSING_CREDENTIAL`. These are not silently converted to success.

A workflow wrapper completing successfully is not sufficient by itself: inspect the receipt/status generated inside the job. Conversely, an explicit provider/account blocker is not an ICARUS code error when the transport and classification paths have been independently verified.

## GitHub-native provider data

For GitHub-native API sources, use the canonical provider adapter and the shared provider collection state. Secret values remain inside GitHub Actions. Never ask another AI account to reveal an API key.

The existing `provider-exhaustive-collection.yml` remains the owner-qualified K1 lane. The additive `provider-supplemental-collection.yml` closes the missing credentialed-provider surface for Unusual Whales, Alpha Vantage and Finnhub without replacing K1. Both write the same provider receipt schema and are consumed by the same `provider_collection_v1/research_context.json` aggregator. Supplemental state must be resumable across clean GitHub runners, and its safe promoter may persist receipts/context but never public raw licensed archives.

New provider additions must update the manifest, credential contract where applicable, endpoint catalog, tests, Sentinel coverage, and runtime health evidence together.

## Unusual Whales

Unusual Whales is not just a credential-health check. The ICARUS collection surface must cover, subject to the owner's actual plan entitlements and rate limits, market tide/daily report, net premium flow, stock screener, GEX/greek exposure, per-minute exposure, strike exposure, greek flow, dark-pool trades/price levels, earnings, insider flow, congressional unusual trades, crypto metadata/candles/trades, and any additional read-only official endpoints added to the pinned catalog.

The GitHub-native collector and the private metadata-only Icarus connector intake are complementary transports. They must not be treated as duplicate proof of historical coverage, licensing, point-in-time eligibility, or redistribution rights.

Premium or Advanced-only Unusual Whales endpoints that return 403 remain explicit entitlement gaps. The collector must not purchase access or weaken the denial into a success state.

## Public and official non-secret sources

Keyless sources are still first-class ICARUS data. Every unit must account for the public venue and official-agency feeds in the manifest: Coinbase, Kraken, Bybit public data, Binance public bulk archives, Cboe volatility indices, CFTC reports, U.S. Treasury FiscalData, Federal Reserve/ECB/BLS release feeds, BEA/Census/FOMC calendars, SEC/EDGAR, and the currently configured public FRED/FRED-ALFRED series.

Do not infer real-time quality merely because a source is public. Yahoo futures are explicitly delayed, release feeds can be blocked by cloud-runner policy, and each collector's timing/availability metadata controls research eligibility.

## Internal specialist and cross-repository evidence

All AI units must treat the active internal evidence fabric as shared context, not private output owned by one model. This includes:

- Robustness Guardian: `automation_intelligence/agent_fabric/robustness_guardian/**`
- Advanced CSV: `reppiks490/icarus-csv-evidence-lab:automation_intelligence/advanced_csv/**`
- Alpha Synthesis: `automation_intelligence/agent_fabric/alpha_synthesis/**`
- Flow Microstructure: `automation_intelligence/flow/**`
- Apex Council: `automation_intelligence/agent_fabric/apex_council/**`
- MCP events/research runs: `automation_intelligence/mcp_interface/**`
- Cross-repo peer packet: `automation_intelligence/interrepo/latest.json`

Read access is federation-wide; write ownership remains governed by `coordination/README.md` and the boards. If an AI cannot access a cross-repo evidence path, record the capability gap rather than silently omitting the evidence family.

## Connector-only sources

Some sources exist only through an interactive connector rather than GitHub Actions. They remain part of ICARUS. If a unit has the connector, it should use it when relevant and preserve permitted derived evidence through normal ICARUS handoff paths. If a unit lacks the connector, it must record `EXTERNAL_CONNECTOR`/capability unavailable and continue with the shared GitHub-native evidence. It must not infer that another account's connector session grants it direct access.

Connector-only availability is not a credential migration target unless the service exposes an approved API credential/transport that can lawfully be placed behind the GitHub-native contract.

## Security and licensing

Do not print, paste, commit, artifact, or otherwise extract plaintext credentials. Do not use `toJSON(secrets)`. Do not commit licensed raw vendor payloads to this public repository. Use the existing encrypted archive/vault paths or derived, redistribution-safe evidence rules.

Do not turn a data-gap closure task into provider purchasing, entitlement upgrades, trading execution, or hidden spend. Existing budget caps and execution-authority gates remain authoritative.

## Continuous gap closure

Every AI unit has a standing obligation to identify and close source gaps encountered during its work. If it discovers a credentialed source without ingestion, ingestion without downstream consumption, stale collection, unsupported pagination, an unrepresented transport, a missing provider endpoint family, a specialist output invisible to peers, or a workflow absent from health monitoring, it must either repair the gap within its ownership boundary or publish a concrete coordination message naming the blocker and evidence path.

Before declaring completion, compare active collectors, workflows, runtime capabilities, specialist evidence, peer packets and connector-only sources against the shared manifest and Sentinel state. Zero known internal errors is the completion condition; external provider/account/licensing blockers remain explicit and must never be relabeled as fixed.

The target is one shared ICARUS evidence fabric: every unit sees the same source ledger, runtime receipts, internal specialist evidence, health state, and explicit blockers. Account-local memory is never the authority.
