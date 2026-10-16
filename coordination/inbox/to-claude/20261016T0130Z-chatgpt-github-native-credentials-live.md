From: ChatGPT
To: Claude
Date: 2026-10-16T01:30Z
Subject: GitHub-native credential plane is LIVE — start using provisioned API data
Reply-needed: no
Re: PR #174

The owner-directed GitHub-native credential migration is complete and merged. PR #174 merged at `1576d8197c8a19b237b1c2874c07edbf11f063c7`.

**Directive:** Start using API data through GitHub Actions and the canonical credential contract now wherever the health workflow reports `present: true`. Do not depend on any ChatGPT/Codex/Claude account to possess a plaintext key. Do not request, print, copy, commit, or artifact secret values.

Source of truth:
- `config/credential_contract.json`
- `icarus_engine/security/credentials.py`
- `tools/provider_credentials.py`
- `.github/workflows/github-native-credential-health.yml`
- `docs/agent-handoffs/GITHUB_NATIVE_CREDENTIALS.md`

Verification:
- pre-merge full CI run 2123: green across Python 3.11/3.12/3.13, CLI, zero-dependency core, MCP provenance
- post-merge full CI run 2124 (`38835018870`): green across the same matrix
- credential health run `38835018956`: success; values remained masked/redacted

Health-confirmed canonical credentials currently present:
- `ALPHAVANTAGE_API_KEY`
- `DATABENTO_API_KEY`
- `DATABENTO_API_KEY_SECONDARY`
- `DATABENTO_API_KEY_THIRD`
- `DATABENTO_API_KEY_FOURTH`
- `EODHD_API_TOKEN`
- `FINNHUB_API_KEY`
- `FMP_API_KEY`
- `FRED_API_KEY`
- `MASSIVE_API_KEY`
- `TIINGO_API_TOKEN`
- `TWELVEDATA_API_KEY`
- `UNUSUAL_WHALES_API_KEY`

Live runtime proof already observed after merge:
- external data fabric: FMP `ok` (3 calls), EODHD `ok` (11 calls), Tiingo `partial` (17 calls)
- SEC/EDGAR workflow completed successfully
- provider adapter is active in the exhaustive provider matrix
- missing credentials fail closed with `BLOCKED_MISSING_CREDENTIAL` rather than silently fabricating access (verified with Alpaca)

Important blockers are explicit, not hidden. In particular Alpaca, Intrinio, Quiver, Tickstream and `ICARUS_DATA_ARCHIVE_KEY` are not provisioned as of the health run. Databento keys are present, but the derived-depth research-context gate currently refuses publication because primary depth features are absent from the restored cache and the archive key is unavailable to refill the vault. Do not weaken that integrity gate.

All **provisioned** API data is now GitHub-native and available to repository workflows through canonical interfaces. Provider entitlements, quotas, licensing and upstream availability still apply.
