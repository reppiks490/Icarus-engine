# Agent credential entrypoint

All agents working in ICARUS must use the GitHub-native credential plane.

Read `docs/agent-handoffs/GITHUB_NATIVE_CREDENTIALS.md`, `config/credential_contract.json`, and `config/data_ingestion_manifest.json` before adding or changing provider authentication or claiming provider data is inaccessible. Also read the federation-wide directive `reppiks490/icarus-owner-actions:coordination/directives/GITHUB_NATIVE_DATA_ACCESS.md`.

New code uses canonical credential names through `icarus_engine.security.credentials`; GitHub Actions supplies secret values at runtime.

## Important: access does not mean plaintext possession

Agents are **not expected to read or possess secret strings**. Do not search local `.env` files, `$ICARUS_HOME/.env`, DAV task comments, Plant/operator notes, another ChatGPT account, or another worker's workspace for shared private keys. Those locations are not credential authority.

If a chat cannot see a plaintext key, that is expected. Check `.github/workflows/github-native-credential-health.yml` for redacted availability, then use `config/data_ingestion_manifest.json` and its `evidence_paths` to consume already-collected shared data. When fresh collection is required, use or extend the established GitHub Actions collector so the workflow receives the secret without exposing it.

Never request, print, paste, commit, artifact, or otherwise expose plaintext API keys. A missing/invalid credential is a blocker only when the canonical health/manifest or verified provider response says so.
