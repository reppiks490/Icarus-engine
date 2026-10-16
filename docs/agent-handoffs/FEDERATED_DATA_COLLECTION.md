# ICARUS Federated Data Collection Directive

## Mandatory directive for every AI unit

Every AI unit working on ICARUS — ChatGPT, Codex, Claude, Atlas, local agents, scheduled GitHub-native agents, and future units — must operate from the same shared data plane. No unit may assume that a provider, dataset, research context, collector, subsystem, or evidence source is "someone else's data" and silently omit it.

The canonical source inventory is `config/data_ingestion_manifest.json`. Read it at the beginning of work that can be affected by market, macro, order-flow, options, fundamental, alternative, economic, event, news, filing, on-chain, or research evidence.

## Required shared surfaces

Every AI unit must account for all applicable parts of the ICARUS evidence plane, including:

- `ICARUS_STATE.md` — system truth and ownership boundaries.
- `config/data_ingestion_manifest.json` — canonical source/access/collection/consumption ledger.
- `config/credential_contract.json` — canonical GitHub-native credential names and aliases.
- `.github/workflows/provider-exhaustive-collection.yml` — existing resumable provider acquisition.
- `.github/workflows/provider-supplemental-collection.yml` — additive acquisition for credentialed providers that were missing from the K1 matrix.
- `automation_intelligence/provider_collection_v1/research_context.json` — safe aggregated provider context.
- Databento depth/order-book evidence and the encrypted depth-vault lanes.
- SEC/EDGAR filings and derived filing evidence.
- Official economic event collection and macro event evidence.
- External data fabric outputs.
- Unusual Whales options flow, GEX/greeks, dark pool, market tide, earnings, insider/congress, stock screener and crypto surfaces when entitled.
- Massive/Polygon, Twelve Data, FMP, EODHD, Tiingo, FRED, Alpha Vantage, Finnhub, Bybit and every other source admitted by the manifest.
- Interactive connector-only sources recorded in the manifest when the current unit has that connector; if it does not, the unit records the capability blocker instead of pretending the source does not exist.
- Coordination inboxes, agent boards, research logs, MCP evidence events and any source-qualified downstream consumer artifacts relevant to the task.

## Three-stage truth model

A key existing is not the same as data being collected, and collected data is not the same as data being consumed. Every source is tracked separately as:

1. `credential_state`
2. `ingestion_state`
3. `consumption_state`

Do not claim a source is usable merely because a secret exists. Do not claim a source is collected merely because a workflow exists. Do not claim ICARUS is using a source unless runtime evidence shows that a downstream context/consumer can see it.

## Runtime evidence rule

Do not claim a gap is closed without runtime evidence. Valid evidence includes a successful GitHub Actions job, a current provider `latest/*.json` receipt, a safe aggregated research-context row, a dedicated collector receipt, or an explicit blocked/denied status that accurately identifies an external dependency.

A 401 is authentication failure. A 403/402 is entitlement/plan denial. A 429 is quota/rate-limit pause. Missing credentials remain `BLOCKED_MISSING_CREDENTIAL`. These are not silently converted to success.

## GitHub-native provider data

For GitHub-native API sources, use the canonical provider adapter and the shared provider collection state. Secret values remain inside GitHub Actions. Never ask another AI account to reveal an API key.

The existing `provider-exhaustive-collection.yml` remains the owner-qualified K1 lane. The additive `provider-supplemental-collection.yml` closes the missing credentialed-provider surface for Unusual Whales, Alpha Vantage and Finnhub without overwriting K1. Both write the same provider receipt schema and are consumed by the same `provider_collection_v1/research_context.json` aggregator. New provider additions must update the manifest, credential contract where applicable, endpoint catalog, tests and runtime health evidence together.

## Unusual Whales

Unusual Whales is not just a credential-health check. The ICARUS collection surface must cover, subject to the owner's actual plan entitlements and rate limits, market tide/daily report, net premium flow, stock screener, GEX/greek exposure, per-minute exposure, strike exposure, greek flow, dark-pool trades/price levels, earnings, insider flow, congressional unusual trades, crypto metadata/candles/trades, and any additional read-only official endpoints added to the pinned catalog.

Premium or Advanced-only Unusual Whales endpoints that return 403 remain explicit entitlement gaps. The collector must not purchase access or weaken the denial into a success state.

## Connector-only sources

Some sources exist only through an interactive connector rather than GitHub Actions. They remain part of ICARUS. If a unit has the connector, it should use it when relevant and preserve permitted derived evidence through normal ICARUS handoff paths. If a unit lacks the connector, it must record `EXTERNAL_CONNECTOR`/capability unavailable and continue with the shared GitHub-native evidence. It must not infer that another account's connector session grants it direct access.

## Security and licensing

Do not print, paste, commit, artifact, or otherwise extract plaintext credentials. Do not use `toJSON(secrets)`. Do not commit licensed raw vendor payloads to this public repository. Use the existing encrypted archive/vault paths or derived, non-redistributable-safe evidence rules.

## Continuous gap closure

Every AI unit has a standing obligation to identify and close source gaps encountered during its work. If it discovers a credentialed source without ingestion, ingestion without downstream consumption, stale collection, unsupported pagination, an unrepresented transport, or a missing provider endpoint family, it must either repair the gap within its ownership boundary or publish a concrete coordination message naming the blocker and evidence path.

The target is one shared ICARUS evidence fabric: every unit sees the same source ledger, the same runtime receipts, and the same explicit blockers. Account-local memory is never the authority.
