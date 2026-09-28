# Automation Intelligence

Durable output sink for the five scheduled market-intelligence engines.

Each engine writes its current state to `latest.json` and immutable timestamped run logs under `history/`. OMEGA also maintains `omega_fused_state.json` and `manifest.json`.

A scheduler run must never claim persistence unless the GitHub write succeeds and a commit SHA is returned.
