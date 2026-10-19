# ICARUS Guest Experiment Sandbox

The guest sandbox is an optional, capability-limited companion surface for the ICARUS command center. It is intended for a guest on an iPad or other browser to observe the running engine and experiment with strategy inputs without receiving live runtime authority.

## Safety boundary

The guest surface is **off by default**. When enabled, it runs on its own loopback port and uses a guest capability token that is separate from the ICARUS admin token.

The guest may:

- view sanitized live status, assets, candles, positions, stops/targets, P&L, and recent trades;
- change inputs and choose presets inside the guest's in-memory workspace;
- run isolated historical backtests;
- run an isolated replay "re-warm" that does not call the live runner's warmup;
- reset only the guest workspace.

The guest may not:

- call any `/admin/` route;
- pause, resume, flatten, add, or remove live assets;
- persist or reset the owner's live inputs;
- change the owner's live preset;
- activate research, broker, or execution authority;
- read owner/admin replay jobs;
- access credentials, API keys, or the ICARUS admin token.

Guest replay compute is hard-limited to one active experiment at a time. Guest job results are visible only for jobs created by that guest workspace.

## Start ICARUS with guest sharing

Use the normal engine command and add `--guest`:

```bash
python -m icarus_engine.cli run --guest
```

All existing `run` options still apply. Guest-specific options are:

```text
--guest                         enable the guest surface
--guest-port 8792               dedicated loopback guest port
--guest-token <token>           optional explicit guest capability token
--guest-tunnel cloudflared      public Cloudflare Quick Tunnel (default)
--guest-tunnel none             local-only guest surface
```

If `--guest-token` is omitted, ICARUS creates a cryptographically random token. If an explicit guest token matches the ICARUS admin token, ICARUS discards it and creates a different random guest token instead.

The guest service binds only to `127.0.0.1`. With Cloudflare enabled, `cloudflared` tunnels the **guest port only**. The normal admin dashboard port is not exposed by this feature.

When Cloudflare provides the public endpoint, ICARUS prints a URL shaped like:

```text
https://<random>.trycloudflare.com/g/<random-guest-capability>/
```

Send only that guest URL to the experimenter. The capability segment is a bearer credential: anyone who receives the full URL can use the guest scope until that guest process stops, so do not post it publicly.

If `cloudflared` is unavailable or guest startup fails, the failure is contained. The owner ICARUS engine continues running and the live runtime is not altered.

## State lifetime

Guest input/preset overrides exist only in memory for the guest process. They do not write `inputs.json` or `inputs.<SYM>.json`. Stopping/restarting the process clears the guest workspace.

Backtests use the existing ICARUS isolated replay engine, which freezes/copies cached market history/configuration and runs a fresh in-memory runner. Guest backtests and replay re-warms therefore do not replace or mutate the live runner.

## Revoking access

Stopping ICARUS (or the guest service) destroys the current Quick Tunnel and in-memory guest state. On the next start without an explicit token, a new random guest capability is generated, making the previous guest URL invalid.
