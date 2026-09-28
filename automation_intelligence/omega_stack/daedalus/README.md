# DAEDALUS PRIME isolated operational namespace

Owned by the OMEGA five-loop stack on branch `feature/aion-daedalus-prime-v2`.

Use `heartbeat.json` for IN_PROGRESS only, immutable `history/<RUN_ID>.json` for completed runs, and advance `latest.json` only after immutable-history re-read verification. Never write this lane's state to the shared global scheduler manifest. `execution_authorized=false`.
