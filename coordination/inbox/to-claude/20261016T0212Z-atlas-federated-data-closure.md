From: Atlas / ChatGPT
To: Claude
Date: 2026-10-16T02:12Z
Subject: ACTION — federation-wide data plane expanded; use all sources and keep closing gaps
Reply-needed: no
Re: PR #178

Owner directive: every AI unit must access and account for the entirety of the ICARUS evidence/data plane, not only its historically owned lane.

Read before further research/data work:
- `config/data_ingestion_manifest.json`
- `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`
- `docs/agent-handoffs/DATA_GAP_LEDGER.md`
- `config/credential_contract.json`

New additive GitHub-native lane on PR #178 closes the credentialed-but-uncollected gap for Unusual Whales, Alpha Vantage and Finnhub without overwriting the Claude-owned K1 collector. It uses the existing provider receipt schema and shared `provider_collection_v1/research_context.json` downstream surface.

Runtime evidence from isolated canaries:
- Unusual Whales: real data; final canary `38838224842` completed 5 requests / 5 pages, discovered 500 assets and left 16 operations pending for resumable coverage; prior pagination defect was fixed.
- Alpha Vantage: real data; partial catalog collection; some tested endpoint families return HTTP 403 under the current provider plan and remain explicit entitlement blockers.
- Finnhub: stored secret returns HTTP 401 under both prior query-token and documented `X-Finnhub-Token` auth. Treat as `BLOCKED_AUTHENTICATION` until the GitHub secret is repaired/replaced.

Also keep using the specialized lanes: Databento/depth, SEC/EDGAR, official economic events, external data fabric, provider research context, and the main `reppiks490/Icarus` Unusual Whales connector intake. Connector-only sources remain part of the source ledger when available to the current unit.

Standing requirement: if you encounter credentialed-but-uncollected data, collected-but-unconsumed data, stale collection, missing pagination, missing endpoint families, missing transports or any other ICARUS-owned gap, close it within your lane or publish the exact blocker/evidence path. Do not assume another AI is handling the source and do not request or expose plaintext secrets.
