# Agent credential entrypoint

All agents working in ICARUS must use the GitHub-native credential/data plane for shared provider access.

Read `docs/agent-handoffs/GITHUB_NATIVE_CREDENTIALS.md`, `config/credential_contract.json`, and `config/data_ingestion_manifest.json` before adding or changing provider authentication or claiming provider data is inaccessible. Also read the federation-wide directive `reppiks490/icarus-owner-actions:coordination/directives/GITHUB_NATIVE_DATA_ACCESS.md`.

New provider code uses canonical credential names through `icarus_engine.security.credentials`; GitHub Actions supplies secret values at runtime.

## Important: access does not mean plaintext possession

Agents are **not expected to read or possess secret strings**. Do not search local `.env` files, `$ICARUS_HOME/.env`, DAV task comments, Plant/operator notes, another ChatGPT account, or another worker's workspace for shared provider keys. Those locations are not provider-credential authority.

If a chat cannot see a plaintext provider key, that is expected. Check `.github/workflows/github-native-credential-health.yml` for redacted availability, then use `config/data_ingestion_manifest.json` and its `evidence_paths` to consume already-collected shared data. When fresh collection is required, use or extend the established GitHub Actions collector so the workflow receives the secret without exposing it.

## Do not confuse provider credentials with Plant runtime control

`ADMIN_TOKEN` / `ICARUS_ADMIN_TOKEN`, bridge webhook secrets, and machine-local broker/runtime credentials are **local Plant / bridge runtime controls**. They are privileged local-runtime secrets, not the shared provider credential plane. Legacy bridge/Plant code may correctly load those from the operator's local `.env` because the bridge runs on the local machine.

A cloud agent that cannot read the Plant admin token must not conclude that market/provider data is inaccessible. For data/research, use the GitHub-native evidence plane. If a task genuinely requires privileged Plant control, report `LOCAL_RUNTIME_CAPABILITY_REQUIRED` and use an explicitly approved/brokered runtime-control path; do not copy the admin token into chats, issues, coordination notes, workflows, or repository files.

**Live broker arming remains disabled.** The existence of local admin credentials does not grant live execution authority. Read-only observability and verified paper/shadow operations remain separate from live-order arming.

Never request, print, paste, commit, artifact, or otherwise expose plaintext credentials. A missing/invalid provider credential is a blocker only when canonical health/manifest state or a verified provider response says so.
