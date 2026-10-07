# API connection and value audit — 2026-10-07

The project has useful scheduled data collection, but a blanket “all keys connected and valuable” statement is not supported. Key values were never read or persisted. GitHub secret administration is unavailable through the connected tools, so this inventory covers configured references and successful outputs, not every secret held in every account.

| Provider | Evidence of value | Limit |
|---|---|---|
| Databento primary | 32 futures bar feeds succeeded in latest manifest; NQ depth sweep maintained | DX/VXM licensing failures; bar completion at 11:05 UTC, not current real-time |
| Databento secondary | 39 cached index depth slices; authenticated cost estimates support budget decisions | Corpus budget only $0.02732 remaining; latest run downloaded zero slices; shared NQ corpus does not prove independent second capture |
| Databento third | 52 cached diversifier depth slices; authenticated cost estimates support budget decisions | Corpus budget only $0.01117 remaining; latest run downloaded zero slices |
| FRED/ALFRED | 39 macro series, including point-in-time vintages for release-sensitive research | No failure in inspected receipt |
| EODHD | 251 daily bars per 10 equities/ETFs; returns and volatility in external fabric used by cl_lab/run.py | Ticks HTTP 403, denied |
| FMP | 37 earnings-calendar rows and 4 focus events plus profiles; fresh SPY quote connector success | No failure in inspected receipt |
| Tiingo | Long-run daily history for 10 symbols and 390 five-minute bars for 6 symbols; volatility/ranges in external fabric | News HTTP 403, denied |
| Massive | Fresh SPY previous-day OHLC provides independent reconciliation with Twelve/FMP | No callable credential export or GitHub secret wiring observed; cannot promise scheduled use |
| Twelve Data | Fresh 3 daily SPY bars and quota check successful; previous close 779.09 agrees with Massive | No callable credential export or GitHub secret wiring observed; cannot promise scheduled use |
| OpenAI | Paid-model transport exists but replacement deliberately uses runner-local inference | Presence/current validity unknown; no paid call enabled |
| Anthropic | Advisory implementation reference only | Presence/current validity and active use unknown; no paid call enabled |

Dated, machine-readable evidence is in `automation_intelligence/native_research_v1/api_value_audit_20261007.json`. Existing external-data-fabric runs weekday 22:40 UTC; cl-lab runs 01:41, 13:41 and 21:41 UTC. The new five-lane research runs hourly minute 41. Existing provider collectors retain budget caps; no paid model fallback or new paid historical downloads were enabled. Cached corpus reuse provides continuing research value without repeated purchases.

Connector credentials are not automatically available on GitHub runners. Massive/Twelve authenticated data checks succeeded in this audit; recurring GitHub collection remains unwired and needs a runner-accessible credential/authorized adapter. Optional model credentials are intentionally unnecessary for the token-free replacement. Unobserved providers and secret names remain unverified.
