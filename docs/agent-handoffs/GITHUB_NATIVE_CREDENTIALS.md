# ICARUS GitHub-Native Credential Handoff

## Directive for every AI unit

The ICARUS provider credential plane is GitHub-native. **Start using the API data through GitHub Actions and the canonical credential contract now wherever the health report says the credential is present.** Do not depend on a particular ChatGPT, Codex, Claude, or other agent account to hold an API key.

All API data that is actually credentialed and entitled in this repository is accessible to repository workflows through the GitHub-native runtime path. This statement is about credential plumbing, not a claim that every provider account has every paid entitlement or endpoint.

## Source of truth

- Canonical contract: `config/credential_contract.json`
- Resolver: `icarus_engine/security/credentials.py`
- Redacted verifier: `tools/credential_health.py`
- GitHub Actions health workflow: `.github/workflows/github-native-credential-health.yml`
- Historical exhaustive alias inventory: `.github/workflows/secret-inventory.yml`
- System-state baseline: `ICARUS_STATE.md`

Application code should ask for the canonical name. Example:

```python
from icarus_engine.security.credentials import resolve_credential

key = resolve_credential("MASSIVE_API_KEY")
```

The resolver prefers the canonical environment name and then checks approved legacy aliases in contract order. Do not add one-off `os.environ.get(...)` alias chains when the contract can own them centrally.

## Security rule

**Sensitive credentials belong in GitHub Actions Secrets only.** GitHub Actions Variables are reserved for non-sensitive configuration such as a public contact/user-agent string; they are not an API-key vault and must not be used as fallback storage for API keys, tokens, passwords, sessions, or private credentials.

**Do not request, print, paste, commit, artifact, or otherwise extract plaintext credential values.** Agents do not need the values. GitHub Actions injects Secrets into the job environment at runtime. Health output contains only canonical name, presence, and matched alias name.

Never use `toJSON(secrets)`, environment dumps, shell tracing around credentials, or provider exception payloads that may echo credentials.

## How to check availability

Use the Actions workflow `github-native-credential-health`. It runs the contract tests and writes a redacted `credential-health.jsonl` artifact. A representative line is:

```json
{"canonical_name":"MASSIVE_API_KEY","matched_alias":"MASSIVE_API_KEY","present":true}
```

No credential value is present in that output. The workflow resolves credential aliases from Actions Secrets only.

From a runner that already has the approved environment injection, the equivalent command is:

```bash
python -m tools.credential_health --json-lines
```

## Verified storage-class audit

A presence-only audit on 2026-10-16 verified that every currently live provider credential used by this data plane is backed by a GitHub Actions Secret: Alpha Vantage, Databento primary/secondary/third/fourth, EODHD, Finnhub, FMP, FRED, Massive/Polygon, Tiingo, Twelve Data, and Unusual Whales. None of those live credential families depended on a GitHub Variable.

**Repository scope matters.** The audit found no Secret or Variable for Intrinio in this `reppiks490/Icarus-engine` repository. The shared data-gap ledger cites a provider collection run in the preferred `reppiks490/Icarus` repository (run `38865138563`): its workflow and Intrinio job completed successfully, while the ledger reports that the collector found the credential present, then received HTTP 401 and collected zero rows. The cited receipt classified the result as `BLOCKED_AUTHENTICATION`. Therefore the available evidence says Intrinio is **present but rejected in Icarus** and **absent from Engine's local secret set**. Do not conflate those repository-scoped facts or report Intrinio as missing from the federation. The data path remains blocked until the credential/account authorization is repaired. This does not make the secret readable or transferable between repositories or agents.

Quiver, Alpaca key/secret, Tickstream, and `ICARUS_DATA_ARCHIVE_KEY` remain explicit missing-credential blockers unless current repository-scoped health evidence changes.

The audit reported booleans only and never emitted credential values.

## Verified baseline before this migration

`ICARUS_STATE.md` recorded the following GitHub Actions secrets as present on 2026-10-11: Databento primary/secondary/third (and a fourth stored but previously unused), Massive, Twelve Data, Alpha Vantage, Finnhub, FMP, FRED, EODHD, Tiingo, and Unusual Whales. It recorded Alpaca, Quiver, Tickstream, Intrinio, and `ICARUS_DATA_ARCHIVE_KEY` as not present at that time.

The new health workflow supersedes that historical snapshot for credential-presence checks after it runs. Do not convert a missing result into an availability claim.

## What other units should do now

1. Read `config/credential_contract.json` before adding provider authentication.
2. Use canonical names in new code.
3. Store sensitive values only in GitHub Actions Secrets; use Variables only for non-sensitive configuration.
4. Start using provider data whose canonical credential reports `present: true` and whose account entitlement permits the requested endpoint.
5. Keep existing legacy aliases only as compatibility names inside Secrets; do not invent new aliases outside the contract.
6. If a provider reports missing, record the canonical name as the blocker. Do not ask another AI account to reveal a key.
7. Keep licensed raw vendor rows out of this public repository; follow the existing vault/licensing rules.

The goal is that every agent can operate the same data plane from repository state and Actions, while no agent needs possession of a secret string.
