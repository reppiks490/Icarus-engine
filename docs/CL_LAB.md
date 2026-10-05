# CL lab — keyless feeds → pre-registered edge grammar → gate stack → champions

CL (Claude, Anthropic) — 2026-10-03. Lane tag **CL**: branches `claude/cl-*`, commits `[CL]`.

## What it does (every scheduled run, free on public Actions)

1. **Feeds** (`cl_lab/feeds/`): keyless public sources, live-verified 2026-10-04 — Binance public bulk 5m klines (BTCUSDT, ETHUSDT, with taker-buy volume), Coinbase Exchange 5m candles (BTC-USD), FRED (DGS10, DGS2, T10Y2Y, DFF, VIXCLS), Cboe (VIX, VIX9D, VIX3M, VVIX, SKEW), CFTC TFF for E-mini / Micro E-mini / consolidated Nasdaq-100. Yahoo is deliberately not used (terms ban automated collection; HTTP 429 from cloud IPs). Raw rows live only in the Actions cache; the repo receives manifests (rows, coverage, sha256, integrity) and derived statistics.
2. **Grammar** (`cl_lab/grammar.py`, `cl-g1`, 492 pre-registered candidates): intraday momentum (Gao, Han, Li & Zhou 2018), noise-boundary breakout (Zarattini, Aziz & Barbon 2024), opening-range breakout incl. the 5-minute first-candle rule, overnight gap fade/follow, prior-day/overnight **liquidity sweep** reversal vs continuation (the ICARUS premise), same-half-hour persistence (Heston, Korajczyk & Sadka 2010), VWAP trend (Zarattini & Aziz 2023), each × volatility regime (all / high / low, causal).
3. **Backtester** (`cl_lab/backtest.py`): decisions on bar closes, fills at the next bar open; stops checked from the entry bar; same-bar stop+target = stop; gap-through fills at the open. Costs: MNQ $0.85/side + 1 tick/side ($2.70 RT); stress 2×. Crypto 5 bp fee + 1 bp slippage per side; stress 2×.
4. **Gates** (`cl_lab/validate.py`, `cl-gates-1`): TUNE < 2025-10-01, HOLD 2025-10-01 → 2026-10-04 (untouched by the grammar's design), FORWARD ≥ 2026-10-05. Sample → Newey–West t ≥ 2 → BH-FDR q ≤ 0.10 over all 492 → Deflated Sharpe ≥ 0.95 with Li–Ji effective trials → HOLD t ≥ 1.65 with Holm → doubled-cost stress → quarterly + parameter-neighbour stability → asset-level Hansen SPA p ≤ 0.10 and CSCV PBO ≤ 0.25.
5. **Registry** (`automation_intelligence/cl_lab/champions.json`): a rule is frozen at first registration (CANDIDATE or better); forward evidence counts only sessions after that date; entries are never deleted.

## THE PULSE OF ICARUS (cl_lab/pulse_track.py)

The repo's own v3.1 port runs every time its code, preset or the 20m tape change, on three variants: Heikin-Ashi signals with REAL fills (what a broker gives), standard candles, and HA-chart-with-HA-fills (TradingView's default; status always `ARTIFACT_REFERENCE`). CL base costs $0.85/side/contract + 1 tick, stress $1.70 + 2 ticks; the repo's historical $0.37 + 2 ticks is reported too and reproduces the earlier +$11,853. First run (2024-09 → 2026-09, 10 MNQ): HA real fills +$11,915 over 490 trades (TUNE t 0.27, HOLD t 0.37) → REJECTED; candles +$33,746 (TUNE t 1.68, HOLD t 0.31) → REJECTED; HA fills +$317,187 → artifact. Deflated Sharpe assumes 100 tuning trials (the TradingView history is unrecorded).

## Edge explorer (cl_lab/explore.py, `cl-x1`)

Each run invents 24 never-tested compositions per asset from ~56k (wider grids × regime × 14 causal day conditioners: prior-session direction, overnight gap and range, day of week, VIX level and VIX9D/VIX term structure). Every attempt is appended to `explore_ledger.jsonl`; BH-FDR includes every earlier TUNE p-value, the Deflated Sharpe counts every earlier trial, and HOLD uses Bonferroni over every rule that ever reached HOLD — so more searching cannot manufacture a champion. `cl_lab/causality.py` makes the look-ahead checks reusable; every conditioner and sampled composition passes them.

## Federation watch (cl_lab/watch.py, `cl-federation-watch.yml`)

Runs after every peer export, event-contract and tests run on main (plus hourly): canonical gate result, engine event-contract and tests results, peer-packet age vs 1800 s, malformed custom-agent events (exact legacy blobs honoured), and scheduled-run delivery. Verdict GREEN / DEGRADED / RED in `automation_intelligence/cl_lab/federation_health.json` (written only on change) and one `[CL] Federation health` issue opened, updated or closed automatically. Read-only: it never repairs or relaxes a check. First live read (2026-10-04 16:5xZ): RED — canonical gate failure, event contract failure, packet 3578 s old, 4 malformed events; peer export delivered 5 scheduled runs in 24 h against a `*/10` cron.

## Causality proof (tests_cl/test_core.py)

Every one of the 492 candidates passes cross-day prefix invariance and intraday truncation invariance (bars after the cut replaced with garbage); a deliberately leaky positive control is detected. The workflow refuses to publish outputs if any lab test fails.

## Outputs (namespace `automation_intelligence/cl_lab/`, 1:1 persistence invariant)

`heartbeat.json` (only mutable marker) → `history/<RUN_ID>.json` (immutable, read back) → `latest.json` (identical bytes) → `candidates_latest.jsonl`, `pulse_latest.json`, `explore_ledger.jsonl`, `champions.json`, `ui_feed.json`, `feeds_manifest.json`. RUN_ID is deterministic from the inputs, so unchanged inputs are a no-op. `ui_feed.json` (`cl_lab.ui_feed/1`) is the contract for the ICARUS UI: `ui_state` is always `RESEARCH ONLY`; nothing here is trading authority.

## First run (2026-10-04, local, same inputs as Actions)

All 492 candidates **REJECTED** on MNQ, BTCUSDT and ETHUSDT. Best MNQ TUNE t = 2.08 (gap fade, 46 trades — below the sample gate); BH-FDR rejections 0; effective trials ≈ 116–125; SPA p = 0.86 (MNQ), 0.99 (BTC), 0.57 (ETH); PBO 0.46 / 0.33 / 0.21. The published intraday rules, at these parameterizations and realistic costs, show no edge distinguishable from data-snooping on 2024–2026 data. The lab is built to keep searching honestly, not to manufacture champions.

## R2: data integrity, multi-session hypotheses, order flow, walk-forward ML (2026-10-04)

Specification, amendments and results: `docs/CL_PREREG_R2.md`. Frozen ids: `cl_lab/prereg_r2.json`.

- `integrity.py` (`cl-data-2`): the MNQ tapes are unadjusted continuous series. Contract switches are detected from the MNQ − NASDAQ-100 basis and Panama back-adjusted. Overnight ranges that may mix contracts are blanked, and holds across an undetected roll are skipped. Every run records the switches and a post-adjustment basis check.
- `multisession.py`: overnight holds marked to market at each RTH close, plus a daily-weight simulator for index series.
- `events.py`: verified 2024–2026 FOMC decision dates and month-end positions.
- `hypotheses_r2.py` (`cl-r2`): EOD reversal under the HOLD-only protocol `cl-hc1`, month-end rebalancing (40 years of NDX daily plus an MNQ execution twin), pre-FOMC event study, and crypto taker-flow imbalance.
- `ml.py` (`cl-ml1`): an L2 logistic walk-forward model per (asset, decision time). It reports Brier, AUC, calibration, coefficient stability, baselines and a label-permutation control. Prefix, intraday and leaky-control causality tests run in CI.
- New feed: FRED `NASDAQ100`.

## Changelog (CL lab)

1. 2026-10-03 — cl-g1 grammar (492), cl-gates-1, keyless feeds, registry, persistence invariant.
2. 2026-10-04 — Edge explorer cl-x1, causal conditioners, causality proofs, federation watch.
3. 2026-10-04 — THE PULSE OF ICARUS gated as an external strategy.
4. 2026-10-04 — cl-r1 conditional EOD momentum (research rank 1).
5. 2026-10-04 — cl-data-2 roll integrity fix; multi-session simulator; cl-r2 families; cl-ml1 walk-forward ML; R3-1 HOLD confirmation. No new champion. Results are in `docs/CL_PREREG_R2.md`.

## Run locally

```
pip install "numpy>=1.26,<3" "pandas>=2.2,<3" "scipy>=1.11" pytest
python -m pytest -q tests_cl
python -m cl_lab.feeds --cache .cl_cache --manifest /tmp/feeds.json
python -m cl_lab.run --out /tmp/cl_out --cache .cl_cache
```


## Optional Databento futures corpus

The canonical Icarus repository can export local continuous-futures OHLCV through its existing Databento adapter. Point CL at that export with ICARUS_DATABENTO_CORPUS=/path/to/corpus/databento. CL verifies the manifest schema, file SHA-256, row count, and CSV shape before surfacing compact corpus metadata. Raw rows remain local.

This makes the broader futures universe, including NQ/MNQ, ES/MES, YM/MYM, RTY/M2K, GC/MGC, SI/SIL, and other registered Databento-compatible futures visible as verified corpus evidence. Corpus presence is not strategy qualification: assets without a separately validated cost model and gate path remain corpus-only.
