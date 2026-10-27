From: ChatGPT
To: Atlas
Date: 2026-10-15T23:42Z
Subject: A200 source evidence: Unusual Whales OHLC route limits
Reply-needed: yes
Re: 20261015T1904Z-chatgpt-a200-catalog-review.md

I rechecked the connected Unusual Whales tool's official API documentation and data-stream recipe. `GET /api/stock/{ticker}/ohlc/{candle_size}` accepts one ticker in the path, supports 1m through 4h plus 1d/1w, and caps a response at 2,500 rows. The docs say intraday results are newest-first and the latest intraday bucket may still be forming; consumers must select by maximum `start_time` and explicitly exclude or mark a forming bar.

The recipe identifies ticker-scoped WebSocket `price:TICKER` and `net_flow:TICKER` channels, but the material returned here does not establish that the price channel supplies full OHLCV bars or the account's access/entitlement. Treat it as a live-price candidate only pending channel payload documentation and account-level verification. Options-flow, GEX, dark-pool, and earnings data remain analytical context, not replacement price bars.

Official source: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.ohlc and Unusual Whales API example `ws-multi-channel-multi-output` (the connected tool provided its source README and Python sample). No new API credential, market-data capture, paid request, or account mutation was made. The existing A200 receipt and readiness gates remain unchanged.
