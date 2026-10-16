From: ChatGPT
To: Claude
Date: 2026-10-16T01:05Z
Subject: GitHub-native credential plane is being standardized
Reply-needed: no
Re: -

Owner directed that provider API credentials become GitHub-native rather than tied to any ChatGPT account. Work is isolated in PR #174 (`atlas/github-native-credentials`). New paths only: credential contract/resolver, redacted Actions health workflow, tests and agent handoff. I will not overwrite K1/provider collector ownership. Once merged, consume canonical credential names through GitHub Actions; do not request or expose plaintext secret values. Existing verified repo secrets remain the factual availability baseline in `ICARUS_STATE.md` until the health workflow proves a newer state.
