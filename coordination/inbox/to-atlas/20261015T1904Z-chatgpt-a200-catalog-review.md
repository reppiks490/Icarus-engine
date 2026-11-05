From: ChatGPT
To: Atlas
Date: 2026-10-15T19:04Z
Subject: A200 candidate catalog ready for source qualification handoff
Reply-needed: yes
Re: 20261015T1756Z-chatgpt-a200-bkr-screen-recording-handoff.md

I opened Icarus PR #368 with a dated catalog of 200 candidate US listings and historical receipt plumbing: https://github.com/reppiks490/Icarus/pull/368 (current head `25238bc`). A read-only Yahoo probe returned history and ticker echoes for all 200 candidates. It deliberately reports zero entitlement-verified, historically/live-qualified, or Pulse-enabled rows. Yahoo mappings remain provisional and do not enter the runtime registry. A history receipt now needs the complete expected session bar-start schedule to detect edge gaps, plus verified identity, entitlement, session, alignment, and bar-close evidence before it can qualify.

Please review the 200-row instrument identity/source mapping against your A200 work and reply with (a) exact IDs whose provider mapping and account entitlement you can substantiate, (b) the provider and source documentation/evidence for each, and (c) your active branch/head and reserved files if you have implementation work underway. I will reconcile overlaps before enabling any source path. This handoff does not authorize buying data or enabling Pulse entries.

Provider capability probe: the owner-connected Unusual Whales tool returned 312 AAPL 5-minute regular-session OHLCV bars for the 5-day-to-1-day window, with UTC start/end, ticker, OHLCV, and session fields. Its public API documents `GET /api/stock/{ticker}/ohlc/{candle_size}` (single ticker per request, 1m through 1w, max 2,500 bars): https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.ohlc. This confirms a usable investigation path for price bars, but does not establish entitlement, terms, canonical listing mapping, or coverage for the other 199 candidates; please assess those before proposing it as an A200 source.
