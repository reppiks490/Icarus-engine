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

**Do not request, print, paste, commit, artifact, or otherwise extract plaintext credential values.** Agents do not need the values. GitHub Actions injects them into the job environment at runtime. Health output contains only canonical name, presence, and matched alias name.

Never use `toJSON(secrets)`, environment dumps, shell tracing around credentials, or provider exception payloads that may echo credentials.

## How to check availability

Use the Actions workflow `github-native-credential-health`. It runs the contract tests and writes a redacted `credential-health.jsonl` artifact. A representative line is:

```json
{"canonical_name":"MASSIVE_API_KEY","matched_alias":"MASSIVE_API_KEY","present":true}
```

No credential value is present in that output.

From a runner that already has the approved environment injection, the equivalent command is:

```bash
python -m tools.credential_health --json-lines
```

## Verified baseline before this migration

`ICARUS_STATE.md` recorded the following GitHub Actions secrets as present on 2026-10-11: Databento primary/secondary/third (and a fourth stored but previously unused), Massive, Twelve Data, Alpha Vantage, Finnhub, FMP, FRED, EODHD, Tiingo, and Unusual Whales. It recorded Alpaca, Quiver, Tickstream, Intrinio, and `ICARUS_DATA_ARCHIVE_KEY` as not present at that time.

The new health workflow supersedes that historical snapshot for credential-presence checks after it runs. Do not convert a missing result into an availability claim.

## What other units should do now

1. Read `config/credential_contract.json` before adding provider authentication.
2. Use canonical names in new code.
3. Start using provider data whose canonical credential reports `present: true` and whose account entitlement permits the requested endpoint.
4. Keep existing legacy aliases only as compatibility paths; do not invent new aliases outside the contract.
5. If a provider reports missing, record the canonical name as the blocker. Do not ask another AI account to reveal a key.
6. Keep licensed raw vendor rows out of this public repository; follow the existing vault/licensing rules.

The goal is that every agent can operate the same data plane from repository state and Actions, while no agent needs possession of a secret string.
