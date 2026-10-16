# ICARUS futures universe expansion — 2026-10-16

## Purpose

This change expands the runtime/dashboard with a deliberately macro-diverse futures set instead of selecting ten arbitrary roots. The selection adds information that is complementary to the existing NQ/ES/YM, metals and crypto surfaces: small-cap breadth, energy/inflation, industrial growth, major-currency policy/carry, and Treasury duration.

The runtime source in this change is the existing Yahoo public chart adapter. It is **delayed research data** and is not a broker or exchange-entitled low-latency feed. Source capability and current source reachability are separate facts. `tools/futures_universe_probe.py` records actual public-source reachability without credentials and does not silently convert a blocked provider into success.

**Live broker arming is disabled.** Adding a futures contract to the registry, dashboard, replay or paper engine does not authorize live orders. Broker-specific dated-contract mapping, account permissions, market-data entitlement, venue reconciliation and owner arming remain separate gates.

## Handpicked ten-root expansion

| Root | Smaller counterpart | Why it is valuable to ICARUS | Exchange family | Asset class |
|---|---|---|---|---|
| RTY | M2K | Russell 2000 small-cap breadth/risk appetite; complements NQ/ES mega-cap concentration | CME | equity index |
| CL | MCL | WTI oil, inflation, geopolitics, transport and cross-commodity risk | NYMEX | energy |
| NG | MNG | Natural-gas weather/storage/power volatility and energy-regime separation | NYMEX | energy |
| HG | MHG | Copper as an industrial/global-growth and China-sensitive macro surface | COMEX | metal |
| 6E | M6E | EUR/USD exposure to Fed/ECB relative policy and global dollar regimes | CME | FX |
| 6J | MJY | JPY/USD exposure to BoJ policy, carry unwinds and risk-off episodes | CME | FX |
| 6B | M6B | GBP/USD exposure to BoE/UK macro and transatlantic policy divergence | CME | FX |
| 6A | M6A | AUD/USD commodity/China/risk-beta exposure | CME | FX |
| ZN | — | 10-year Treasury duration; central macro rate/discount-rate signal | CBOT | rates |
| ZB | — | 30-year Treasury long-duration/convexity regime information | CBOT | rates |

ZN and ZB do not have a simple one-tenth price-futures counterpart analogous to the micro contracts above, so this change does not invent one.

## Contract identity used by the emulator

`multiplier` is the contract amount used by the emulator: P&L = price change × multiplier × contracts. Tick value therefore equals `mintick × multiplier`.

| Symbol | Yahoo ticker | Min tick | Multiplier | Tick value | Session in Icarus | Micro parent |
|---|---|---:|---:|---:|---|---|
| RTY | RTY=F | 0.10 | 50 | 5.00 | RTH | — |
| M2K | M2K=F | 0.10 | 5 | 0.50 | RTH | RTY |
| CL | CL=F | 0.01 | 1,000 | 10.00 | ETH | — |
| MCL | MCL=F | 0.01 | 100 | 1.00 | ETH | CL |
| NG | NG=F | 0.001 | 10,000 | 10.00 | ETH | — |
| MNG | MNG=F | 0.001 | 1,000 | 1.00 | ETH | NG |
| HG | HG=F | 0.0005 | 25,000 | 12.50 | ETH | — |
| MHG | MHG=F | 0.0005 | 2,500 | 1.25 | ETH | HG |
| 6E | 6E=F | 0.00005 | 125,000 | 6.25 | ETH | — |
| M6E | M6E=F | 0.0001 | 12,500 | 1.25 | ETH | 6E |
| 6J | 6J=F | 0.0000005 | 12,500,000 | 6.25 | ETH | — |
| MJY | MJY=F | 0.000001 | 1,250,000 | 1.25 | ETH | 6J |
| 6B | 6B=F | 0.0001 | 62,500 | 6.25 | ETH | — |
| M6B | M6B=F | 0.0001 | 6,250 | 0.625 | ETH | 6B |
| 6A | 6A=F | 0.00005 | 100,000 | 5.00 | ETH | — |
| M6A | M6A=F | 0.0001 | 10,000 | 1.00 | ETH | 6A |
| ZN | ZN=F | 0.015625 | 1,000 | 15.625 | ETH | — |
| ZB | ZB=F | 0.03125 | 1,000 | 31.25 | ETH | — |

## Existing micro-identity repairs

The old registry did not model several already-important micro futures correctly. Most seriously, `MNQ` was an alias to full-size `NQ`, so resolving MNQ inherited the NQ $20/point multiplier instead of the micro $2/point multiplier. MES, MYM, MGC and SIL were absent and could fall through the generic unknown-symbol Coinbase path.

This expansion makes all five first-class futures:

| Symbol | Yahoo ticker | Min tick | Multiplier | Parent | Icarus session |
|---|---|---:|---:|---|---|
| MNQ | MNQ=F | 0.25 | 2 | NQ | RTH |
| MES | MES=F | 0.25 | 5 | ES | RTH |
| MYM | MYM=F | 1.0 | 0.5 | YM | RTH |
| MGC | MGC=F | 0.10 | 10 | GC | RTH |
| SIL | SIL=F | 0.005 | 1,000 | SI | RTH |

MGC and SIL intentionally retain the existing parent metal strategy's RTH behavior in this change; identity correction does not silently change the strategy session. HG/MHG are new and are configured for ETH.

## Source and session semantics

- `feed=yahoo` means the existing public Yahoo chart adapter is the research source.
- `feed_mode=public_delayed` is a capability label, **not** a claim that the endpoint is reachable from every runner.
- The Yahoo adapter already documents delayed CME futures data and uses the feed's own `regularMarketTime` when deciding whether a bar is closed.
- Equity-index additions use the system's existing RTH convention for strategy parity.
- New energy, copper, FX and Treasury futures use ETH so they are not incorrectly constrained to the equity 09:30–16:15 ET RTH window.
- The existing `CMECalendar` currently has equity/metals holiday schedules. This change does not invent untested holiday groups; `asset_class` carries the precise economic class while calendar behavior stays within the existing tested model.

## Dashboard/API integration

The dashboard is registry-driven rather than maintaining a second symbol list. `GET /api/assets` iterates `REGISTRY.values()`, and `dashboard.html` fetches `/api/assets` to render the add-asset registry. Therefore every first-class registry entry in this change becomes visible and addable through the existing UI path without duplicating/hardcoding the universe in JavaScript.

Paper/replay P&L and sizing use the `AssetSpec` multiplier and mintick, which is why the micro-identity repair is part of the same acceptance contract as UI visibility.

## Verification gates

1. Contract tests require every root/micro to be a first-class futures spec with the expected source ticker, min tick, multiplier, exchange, asset class, micro relationship and session.
2. Continuous-style aliases (`MNQ1!`, `M2K1!`, `MCL1!`, etc.) must resolve to the correct contract size rather than a parent.
3. API/dashboard tests prove the UI remains registry-driven.
4. `tools/futures_universe_probe.py` probes the public source and emits machine-readable per-symbol evidence.
5. A provider/network block is recorded as blocked/unavailable, never relabeled as connected.
6. No gate in this work changes the central owner constraint: live broker arming remains disabled.

## Research basis

Contract sizes/ticks/micro mappings were checked against current CME Group product specifications and product guides for Micro E-mini equity index futures, WTI/Micro WTI, Henry Hub/Micro Henry Hub, Copper/Micro Copper, CME FX and Micro FX, U.S. Treasury futures, Micro Gold and Micro Silver. Public-source ticker availability was separately checked against Yahoo Finance symbol surfaces and is re-tested by the repository probe because public ticker availability can change independently of exchange contract specifications.
