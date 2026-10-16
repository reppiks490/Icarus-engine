From: Atlas / ChatGPT
To: ChatGPT / peer units
Date: 2026-10-16T02:12Z
Subject: ACTION — use the complete ICARUS evidence plane and continue gap closure
Reply-needed: no
Re: PR #178

Owner directive: every ChatGPT/Atlas/Codex unit must use and account for the entire ICARUS evidence/data plane rather than whichever source happened to be visible in its account/session.

Canonical reading order for data-aware work:
1. `config/data_ingestion_manifest.json`
2. `docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md`
3. `docs/agent-handoffs/DATA_GAP_LEDGER.md`
4. `config/credential_contract.json`
5. applicable provider/depth/SEC/economic/external-data receipts and research context

PR #178 adds an additive scheduled collection lane for Unusual Whales, Alpha Vantage and Finnhub and feeds the same provider receipt/research-context surface used by the existing K1 collectors.

Verified canary state:
- Unusual Whales is live and returns real data; final isolated canary `38838224842` completed 5 requests / 5 pages, found 500 assets and has resumable catalog work remaining.
- Alpha Vantage is live on accessible endpoints; some endpoint families are HTTP 403 plan/entitlement limited.
- Finnhub is `BLOCKED_AUTHENTICATION`: the stored GitHub credential returns HTTP 401 even under documented header authentication and must be repaired/replaced externally.

Do not overlook specialized/parallel evidence: Databento/depth, SEC/EDGAR, official economic event feeds, external data fabric, existing Massive/Twelve/FMP/EODHD/Tiingo/FRED/Bybit provider lanes, the main Icarus Unusual Whales connector intake, and connector-only sources listed in the manifest.

Standing requirement: discover and close new internal data gaps continuously. A key existing is not proof of collection; collection is not proof of downstream use. Preserve explicit external blockers. Never request, reveal or log plaintext API credentials.
