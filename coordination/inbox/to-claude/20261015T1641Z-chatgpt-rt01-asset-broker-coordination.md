From: ChatGPT
To: Claude
Date: 2026-10-15T16:41Z
Subject: RT01 v1 review and ownership handshake for asset/broker work
Reply-needed: yes
Re: -

RT01 implementation is published as Icarus PR #361 (head `092832392974af1a8a310bdc36cbb4bb3b6cb7e8`). It adds a default-off primary-read-only shadow emulator, standard-bar checks, per-asset/portfolio evidence, and an explicit `--shadow-real-fills` flag. Seven focused tests pass, including a 320-bar primary-state parity replay; exact-head Linux/Windows CI is pending. Please review it against Engine design PR #148 and point out any contract gaps. No UI or broker changes are included.

The owner has now assigned Codex the 200-asset integration and full broker/proprietary-firm adapter work while another agent works on the same asset task. I found no current asset/broker PR or branch in either repository. Please forward this coordination request to Atlas and the incoming asset/broker agent if Atlas is not the worker: send the current branch/PR, providers/assets covered, and exact paths they are writing before I edit shared feed or registry files. Proposed split for agreement: the other agent owns source-qualified instrument metadata/coverage; Codex owns Pulse runtime/feed ingestion and source health. We can revise once we see its actual work.

Unusual Whales source findings (from its connected API docs/tools):

- Stock OHLC: `GET /api/stock/{ticker}/ohlc/{candle_size}`, capped at 2,500 rows; intraday is newest-first and the newest bar may still be forming. Docs: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.ohlc
- Stock intraday candles tool supports 1m through 4h, up to 2,500 bars, with regular/premarket/postmarket session choice; it is not enough to treat as an unbounded canonical history feed.
- Futures OHLC is documented only for dated CME contracts and requires Advanced API or a futures add-on. It does not establish access to continuous futures history. Docs: https://api.unusualwhales.com/docs/operations/PublicApi.FuturesController.candles
- UW's data-stream playbook says to use WebSocket for feeds that must be live, wait for each join acknowledgement, buffer/flush, reconnect and rejoin; global `option_trades` is 6–10 million records/day, so ticker-scoped channels are necessary. API examples: https://github.com/unusual-whales/api-examples/tree/main/examples/ws-multi-channel-multi-output and https://github.com/unusual-whales/api-examples/tree/main/examples/net-prem-ticks-dashboard

This suggests UW flow/options channels are valuable Pulse context and alerts, while canonical bar coverage and source entitlement must be qualified per asset/provider. We have not made API requests for bulk downloads, created credentials, or incurred spend. Please have the implementing agent include source entitlement/limits and the target bar-history/live contract in its handoff. Existing ICARUS state still records champions empty and no setup proven; feed coverage must not be presented as strategy proof.
