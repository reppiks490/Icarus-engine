# Shared data access crosswalk

Verified 2026-10-16 against the mounted workspace, the connected Dropbox account, and `reppiks490/Icarus-engine` main.

## One index for every AI unit

Start with `config/data_ingestion_manifest.json`. It distinguishes credential presence, ingestion, and consumption. For provider credentials, use the GitHub Actions workflows and `tools/provider_credentials.py`; secret values stay inside trusted runners. Never copy them into agent prompts, Dropbox, or repository files.

The shared committed provider surface is `automation_intelligence/provider_collection_v1/research_context.json` plus the provider-specific `latest/*.json` receipts. These are readable through the repository. They contain safe status, row/page counts, and qualified context. A successful API key check alone is not proof of data use.

## Data paths found

| Corpus | Data available | Shared location | Access and limits |
|---|---|---|---|
| Yahoo CME futures | 1-minute and 1-hour CSV archives, 16 contracts | Dropbox `/ICARUS_DATA_STAGING/Databento/incoming/`; also present in the current workspace under `/workspace/yahoo_corpus_1m_recent_2026-10-16/` and `/workspace/yahoo_corpus_1h_2026-10-16/` | Dropbox connection and this workspace can read it. Other agent Dropbox membership/mounts have not been independently verified. See the dated receipt for counts and coverage. |
| SEC companyfacts archive | A ZIP, 877,547,017 bytes | Dropbox `/ICARUS_DATA_STAGING/companyfacts 2.zip` | File metadata only verified; ZIP entries and contents are not yet validated. |
| SEC submissions archive | A ZIP, 372,666,267 bytes | Dropbox `/ICARUS_DATA_STAGING/submissions.zip` | File metadata only verified; ZIP entries and contents are not yet validated. |
| EODHD / Tiingo / Massive / FRED / Alpha Vantage / Unusual Whales | Current collection receipts and compact, source-qualified research context | GitHub `automation_intelligence/provider_collection_v1/` | Read the latest receipt and research context from main. Provider archives in workflow artifacts are encrypted and expire; use the approved workflow path, not artifact sharing. |
| Databento depth | Derived feature slices referenced by index/diversifier manifests; the current manifests report 29 and 42 cached slices, zero new downloads | GitHub `automation_intelligence/cl_lab/databento_depth_corpus_*.json`; workflow cache/vault in `.github/workflows/databento-depth-corpus.yml` | The feature files are not in the mounted workspace or Dropbox. The vault restore path is blocked while `ICARUS_DATA_ARCHIVE_KEY` is absent. Do not claim the indexed feature paths are mounted for all agents. |
| SEC EDGAR live lane | 15,931 fact rows and 2,375 filing rows in the current manifest | GitHub `automation_intelligence/cl_lab/sec_edgar_manifest.json` | This is the verified SEC evidence lane. Do not substitute the uninspected Dropbox ZIPs for it. |

## Current provider evidence and limits

- Unusual Whales: latest shared receipt `supplemental-38873907446-unusual_whales` records 111 collected rows, 5 pages, and 500 discovered assets. Its Actions artifact contains encrypted payload files and expires 2026-10-23; the committed receipt/context is the durable cross-agent surface.
- Massive: current shared research context reports 20,000 rows across 20 pages.
- Tiingo: the current exhaustive run is partial (13 pages, 1 row); a separate external-data fabric has usable daily and limited 5-minute derived context. News returned HTTP 403.
- EODHD: the current exhaustive run made requests but collected no rows; the separate external-data fabric has one-year daily context for 10 symbols. Tick access returned HTTP 403.
- Databento: its secrets are present to GitHub Actions, not to this shell or every interactive agent. Feature cache status does not prove shared file access.
- IBKR: no IBKR username is present in the latest health report, and no IBKR market-data corpus was found in mounted workspaces or Dropbox.

## Access rule for each agent

1. Read the canonical manifest and latest provider research context from the repository.
2. Use a Dropbox connector on the shared parent for the two Yahoo archives and any Dropbox archive. If a session cannot list/read that folder, record `BLOCKED_NO_DROPBOX_MOUNT`; do not borrow another agent's credentials.
3. Use GitHub-native workflows for provider API requests; consume only their committed, permitted research context or a verified downstream artifact.
4. Treat encrypted payload artifacts as non-consumable unless an authorized workflow decrypts them and emits a permitted derived result.
5. Keep source time, coverage, entitlement failures, and freshness alongside any downstream use.

The Dropbox shared-folder metadata confirms the staging folder is under shared parent ID `15245772211`. It does not disclose the complete member list, so this crosswalk does not claim every agent currently has Dropbox permission.