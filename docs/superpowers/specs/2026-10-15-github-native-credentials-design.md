# GitHub-Native Credential Plane Design

## Purpose

Make GitHub Actions, rather than any individual ChatGPT account, the authoritative runtime credential plane for ICARUS provider integrations. AI agents may inspect and modify the contract and workflows, but they never need plaintext secret values.

## Success criteria

1. Provider collectors consume a canonical environment variable name per credential.
2. Existing legacy secret aliases remain accepted during migration so working feeds do not break.
3. Missing credentials fail closed with a machine-readable status; secret values are never logged.
4. A repository-level contract documents canonical names, accepted aliases, and provider ownership.
5. Automated tests reject new ad-hoc aliases and validate workflow wiring.
6. A GitHub Actions health workflow reports only presence/absence and alias source category, never values.
7. Other agents receive a durable repository handoff instructing them to use the GitHub-native contract.
8. No workflow, test, documentation, issue, or artifact exposes plaintext API keys.

## Architecture

### Canonical contract

Create `config/credential_contract.json` as the machine-readable source of truth. Each credential records a canonical environment name and a list of accepted GitHub secret aliases. The canonical name is the only name application code should read.

### Resolver

Create a small Python module under `icarus_engine/security/credentials.py`. It resolves a canonical credential from the process environment, checking the canonical name first and legacy aliases second. It returns only the credential value to the calling process and exposes a separate redacted diagnostic result containing `present`, `canonical_name`, and `matched_alias`; it never logs or serializes secret values.

### GitHub Actions bridge

Create a reusable workflow fragment as an executable health workflow, `.github/workflows/github-native-credential-health.yml`. It maps supported repository secrets into temporary `S_*` environment variables and runs a verifier that emits only redacted status. Existing provider workflows may continue to inject their current secret names during migration, but application code should transition to the resolver/canonical names.

Because GitHub expressions cannot dynamically index `secrets` from a JSON contract, the workflow contains explicit secret references generated from the same finite canonical list and is covered by tests against the contract.

### Migration compatibility

Legacy aliases remain valid until all workflows and collectors use canonical names. Canonical names take precedence when both are present. No plaintext secret is copied between repositories or committed to Git.

### Multi-agent operation

Any ChatGPT/Codex/Claude unit with repository access operates through GitHub code and Actions. It does not need direct access to the provider key. The durable handoff document tells agents which canonical names exist, where the contract lives, how to invoke health checks, and that plaintext extraction is prohibited/unnecessary.

## Initial canonical credentials

The initial contract covers credentials already referenced by ICARUS workflows and the existing secret inventory, including Massive, Twelve Data, Intrinio, FMP, FRED, Databento, Bybit, Alpaca, Polygon, Quiver, Tickstream, Tiingo, EODHD, OpenAI, Anthropic, Gemini, Hugging Face, CoinGlass, Coinbase, Binance, Kraken, SEC user agent, and internal ICARUS peer/archive tokens. Additional credentials must be added only through the contract and tests.

## Security invariants

- Never print, persist, commit, upload, or artifact a secret value.
- Never use `toJSON(secrets)` or equivalent enumeration.
- Diagnostic output is boolean/name metadata only.
- Canonical names are stable API surface; aliases are compatibility shims.
- GitHub Actions is the runtime authority; chats are not credential stores.
- Provider calls remain subject to licensing, entitlements, and rate limits.

## Failure behavior

A missing required credential produces a non-secret diagnostic status and a non-zero verifier exit code when the workflow is run in strict mode. Optional credentials report unavailable without failing unrelated providers. Conflicting aliases are resolved deterministically: canonical first, then aliases in contract order.

## Verification

Unit tests cover precedence, alias fallback, missing values, redaction, and contract validity. Contract tests parse the health workflow and ensure every declared alias is explicitly wired and no undeclared secret references are introduced. GitHub Actions runs the test suite and credential health workflow on the branch before merge.
