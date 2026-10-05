# ICARUS Databento Data-Fabric Expansion Plan

Status: research/data architecture only. This plan does not authorize trading or production decisions.

## Current three-account allocation

### Account 1 — breadth and regime memory
Credential: `DATABENTO_API_KEY`

Purpose:
- build a continuous-futures OHLCV research corpus before spending heavily on depth;
- keep ICARUS's currently registered 16 futures as first priority;
- add macro/volatility context that can condition those markets without silently promoting context symbols into tradable assets.

Initial continuous OHLCV universe:

Core (registered):
- NQ, MNQ, ES, MES, YM, MYM, RTY, M2K
- GC, MGC, SI, SIL, PL, PA
- BTC, MBT

Context:
- Volatility: VX, VXM (CFE / XCBF.PITCH)
- Rates: ZN, ZB, ZF, ZT, SR3
- Energy: CL, MCL, NG
- Industrial metals: HG
- FX: 6E, 6J, 6B, 6A
- Dollar Index: DX (ICE Futures US / IFUS.IMPACT)
- Agricultural inflation: ZC, ZS, ZW

Existing non-Databento context retained:
- VIX, VIX9D, VIX3M, VVIX, SKEW
- DGS10, DGS2, T10Y2Y, DFF
- CFTC TFF Nasdaq positioning
- BTC/ETH spot public feeds

Spend protection:
- every paid request is estimated before download;
- per-feed historical OHLCV cap: $3;
- 35 Databento OHLCV feeds => $105 theoretical empty-cache ceiling before any over-cap request is rejected;
- terminal range is clamped behind the historical availability watermark;
- raw vendor rows remain in Actions/local cache and are not committed.

### Account 2 — equity-index microstructure
Credential: `DATABENTO_API_KEY_SECONDARY`

Primary research goal:
- queue/order-flow/absorption/liquidity-state evidence for the markets closest to the user's NQ/MNQ focus.

Initial allocation:
- NQ: MBO, target up to 12 regime-diverse days
- MNQ: MBO, target up to 12 days
- ES: MBO, target up to 8 days
- MES: MBO, target up to 8 days
- RTY/M2K: MBP-10, target up to 6 days each
- YM/MYM: MBP-10, target up to 5 days each

Budget:
- hard estimated-spend budget: $95 per acquisition cycle when cache is empty;
- per-request cap: $15;
- leave at least ~$30 of a nominal $125 pool unallocated for retries, rare regimes, or later higher-value discoveries.

Selection:
- breadth-first: try to acquire at least one slice per priority root;
- then allocate by regime-weighted information per dollar;
- prefer high-range, high-volume, upper-quartile, median, lower-quartile, quiet and recent days rather than a homogeneous recent-only sample.

### Account 3 — metals, crypto, volatility and macro depth
Credential: `DATABENTO_API_KEY_THIRD`

Initial allocation:
- GC/MGC: MBO, target up to 8 days each
- SI/SIL: MBO, target up to 6 days each
- BTC/MBT: MBO, target up to 5 days each
- PL/PA: MBP-10, target up to 4 days each
- VX/VXM: MBP-10 initially, target 5/4 days
- ZN: MBP-10, target up to 5 days
- DX: MBP-10, target up to 4 days

Why VX/VXM begin at MBP-10:
- CFE depth is strategically valuable but materially more expensive per GB than CME.
- Start with useful depth coverage, measure value and cost, then promote selected VX windows to MBO only when the measured benefit justifies it.

Budget:
- hard estimated-spend budget: $95;
- per-request cap: $15;
- no credential fallback or automatic account rotation.

## Data reduction and provenance

Raw MBO/MBP files are not retained in git.

For each selected slice:
1. call Databento `metadata.get_cost()`;
2. reject the request if it violates per-request or account budget;
3. stream the raw DBN response to a temporary compressed file;
4. hash the raw response for provenance;
5. reduce it into one-minute microstructure features;
6. hash and cache the derived feature file;
7. delete the raw DBN from the runner;
8. commit only the compact manifest/provenance record.

Derived features include:
- add/cancel/modify/trade/fill event counts;
- event and trade size;
- bid/ask event and size imbalance;
- cancellation/addition ratio;
- event-to-receive latency statistics;
- event-price range;
- MBP-10 spread and depth aggregates where available.

These are research features, not validated alpha by themselves.

## Next legitimate account/data lanes

Do not create duplicate accounts merely to multiply promotional credits or bypass provider/team limits. The lanes below are for separately legitimate, independently entitled or paid Databento accounts/subscriptions if the user later provisions them.

### Future lane 4 — Nasdaq constituent lead/lag microstructure
Best dataset:
- `XNAS.ITCH` (Nasdaq TotalView-ITCH)

Priority symbols:
- QQQ
- NVDA
- AAPL
- MSFT
- AMZN
- META
- GOOGL/GOOG
- TSLA
- AVGO
- other high-weight Nasdaq-100 constituents selected dynamically by index weight/liquidity

Data plan:
- broad OHLCV/trades first;
- MBO on QQQ and the highest-impact constituents;
- Nasdaq opening/closing auction imbalance (NOII/Imbalance) events;
- order-book imbalance, quote lifetime, cancellation intensity, auction pressure and lead/lag features against NQ/MNQ.

Why:
- NQ is a weighted basket. Constituent and QQQ order-book behavior can provide a cross-market state view that futures-only data cannot.

### Future lane 5 — options/volatility-surface intelligence
Best dataset:
- `OPRA.PILLAR`

Priority underlyings/parents:
- QQQ options
- SPY/SPX/SPXW options
- VIX options
- selected NVDA/AAPL/MSFT options

Data plan:
- start with definitions + trades + consolidated BBO rather than full-venue firehose;
- select expirations around 0DTE/1DTE/weekly/monthly horizons;
- derive realized/implied-volatility relationships, skew/term-structure, put-call pressure, strike concentration and gamma-sensitive state variables;
- preflight every window because OPRA can become extremely large.

Why:
- options contain forward-looking volatility and strike-positioning information that is absent from futures bars and ordinary MBO.

### Future lane 6 — macro shock and real-economy depth
Datasets:
- `GLBX.MDP3`
- `IFUS.IMPACT`
- later ICE Europe datasets only when separately licensed and cost-justified

Priority markets:
- Rates: ZN, ZB, ZF, ZT, SR3
- Dollar/FX: DX, 6E, 6J, 6B, 6A
- Energy: CL, MCL, NG
- Industrial metals: HG
- Agriculture/inflation: ZC, ZS, ZW

Data plan:
- MBP-10 breadth across the macro basket;
- MBO only on the markets whose depth state has demonstrated incremental explanatory value for NQ/ES/GC;
- preserve synchronized timestamps for lead/lag and shock-propagation research.

Why:
- this lane captures rates, dollar, inflation, energy and growth shocks that can reprice equity-index and metals futures before those relationships are visible in isolated price bars.

## Promotion rules for any new dataset

A new dataset is not promoted merely because it exists.

Promotion path:
1. provenance and integrity pass;
2. cost/value measurement;
3. causal timestamp audit;
4. out-of-sample feature stability;
5. incremental value versus existing features;
6. multiple-testing correction;
7. forward validation;
8. only then expose as a research signal in the UI.

Execution authorization remains false unless a separate, explicit production process authorizes it.
