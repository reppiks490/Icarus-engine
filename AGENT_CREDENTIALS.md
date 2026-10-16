# Agent credential entrypoint

All agents working in ICARUS must use the GitHub-native credential plane.

Read `docs/agent-handoffs/GITHUB_NATIVE_CREDENTIALS.md` and `config/credential_contract.json` before adding or changing provider authentication. New code uses canonical credential names through `icarus_engine.security.credentials`; GitHub Actions supplies secret values at runtime.

Never request or expose plaintext API keys. Use `.github/workflows/github-native-credential-health.yml` for redacted availability checks.
