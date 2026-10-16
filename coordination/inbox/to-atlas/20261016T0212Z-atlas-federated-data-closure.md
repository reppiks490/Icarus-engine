From: Atlas / ChatGPT
To: Atlas / future Atlas units
Date: 2026-10-16T02:12Z
Subject: STANDING DIRECTIVE — complete ICARUS data-plane access and gap closure
Reply-needed: no
Re: PR #178

The owner requires every AI unit to access and account for the entirety of the ICARUS evidence/data plane and to continue closing gaps. This directive persists across future sessions/accounts.

Before data-aware work, read:
- `config/data_ingestion_manifest.json`
- `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`
- `docs/agent-handoffs/DATA_GAP_LEDGER.md`
- `config/credential_contract.json`

The source ledger includes GitHub-native provider collectors, supplemental Unusual Whales / Alpha Vantage / Finnhub collection, Databento depth/order-book lanes, SEC/EDGAR, official economic events, external data fabric, the main Icarus Unusual Whales connector intake, shared provider research context, and connector-only evidence sources.

Verified current boundary:
- Unusual Whales: live real data; resumable partial catalog, transport gap fixed.
- Alpha Vantage: live partial; current-plan 403 entitlement boundaries remain explicit.
- Finnhub: stored secret returns HTTP 401; external credential repair required.
- Intrinio, Quiver, Alpaca, Tickstream: missing credential blockers remain explicit.
- BLS GitHub-runner transport: HTTP 403; official snapshot fallback is active.
- Databento depth recovery: `ICARUS_DATA_ARCHIVE_KEY` is absent; integrity gate must not be weakened.

Standing rule: every discovered credential/ingestion/consumption mismatch is an actionable gap. Fix ICARUS-owned defects, publish exact external blockers, and never claim a source is available merely because another AI account can see it. Never expose plaintext secrets.
