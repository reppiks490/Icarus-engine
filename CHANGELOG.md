# Icarus Engine — Changelog

A numbered record of the system's progression. One strategy, refined forward.
Every entry states what changed, and why the change makes the system harder to
fool.

---

## 1. v1.0.0 — Genesis (2026-09-20)

First complete implementation of the master system: a dependency-free streaming
core, a chart twin, and a validation harness that is hostile to its own results.

### 1.1 Core thesis, encoded
- **Single trigger:** a liquidity pool is raided, the raid fails, the level is
  reclaimed. No other layer may originate a trade (`icarus/signal.py`).
- **Seven-layer confluence:** sweep quality, order flow, structure, volatility
  regime, location vs session value, momentum, sentiment — weighted, normalised
  to `[0, 1]`, gated on a per-asset threshold.
- **Hard gates vs soft scores:** closed session, untradable regime, absent
  trigger and insufficient room to the next pool are absolute vetoes; weak
  confirmations only drain conviction.

### 1.2 Liquidity layer (`features/liquidity.py`)
- Pool map over prior-session extremes, running session extremes, confirmed
  swing pivots, clustered equal highs/lows and the session open, each carrying a
  weight for the resting size it is believed to hold.
- Sweep state machine with a penetration band (`min`/`max` ATR): too shallow is
  noise, too deep is a genuine breakout.
- Sweep quality scored from four independent reads — penetration depth in the
  sweet spot, reclaim speed, rejection wick, and pool weight.

### 1.3 Order flow (`features/orderflow.py`)
- True aggressor delta when the venue serves `bid_volume`/`ask_volume`;
  close-location delta proxy otherwise, **labelled as a proxy** and discounted
  in the composite score rather than passed off as equivalent.
- Session-anchored CVD, delta z-score, absorption (effort without result) and
  price/CVD divergence.

### 1.4 Structure (`features/structure.py`)
- Fractal pivot detector with an explicit, never-removed confirmation lag.
- BOS / CHoCH state machine that requires a **close** through the level; a wick
  through a swing is a raid, and belongs to the liquidity layer.
- Alignment scoring that rewards a *fresh* CHoCH in the trade's direction most.

### 1.5 Volatility regime (`features/volatility.py`)
- ATR percentile band rejects dead tape and shock tape.
- `min_atr_to_cost_ratio` rejects any tape where the target sits inside the
  modelled friction.
- Regime fitness peaks on mid-band volatility expanding out of compression.

### 1.6 Risk (`risk.py`, `execution.py`)
- Stop parked beyond the **raid extreme** — the price at which the premise is
  factually wrong — not at a fixed ATR distance or a round number.
- Fixed-fractional sizing on the real stop distance, so size collapses
  automatically as volatility widens the stop.
- Three independent brakes: per-trade risk, session loss limit in R, and a
  consecutive-loss throttle that halves risk on a streak and restores it on a win.
- Scale out at 1R → stop to breakeven → ATR trail; plus a time stop and a forced
  session flatten.

### 1.7 Adaptation without dilution
- Four asset-class profiles (equity, futures, forex, crypto) re-scale sessions,
  friction, gates and layer weights. **None of them changes what the engine looks
  for.** Futures weight real order flow highest; forex discounts it to proxy
  level; crypto widens the sweep ceiling for fat tails and weights funding-driven
  sentiment most.

### 1.8 Validation harness (`backtest.py`)
- Event-driven backtest driving the exact same `on_bar` a live adapter drives —
  research and production cannot silently diverge.
- **Permutation null test:** the tape is rebuilt from the same bars in shuffled
  order, preserving the return distribution and each bar's internal shape while
  destroying the sequence. The p-value is `(beats + 1) / (runs + 1)`, which can
  never collapse to a dishonest zero.
- Contiguous walk-forward folds — never randomly sampled, because surviving
  regime change is the whole point.
- `verdict` refuses to say `ACCEPT` without ≥30 trades, positive summed R,
  p < 0.05 and expectancy ≥ 0.05R.

### 1.9 Correctness work done during the build
1. **Same-bar sweeps were unreachable.** The pending-raid state was opened after
   resolution ran, so a poke-and-reclaim inside one bar — the fastest and highest
   quality version of the setup — could never confirm. Order reversed.
2. **Broken pools were never retired.** A decisive break beyond the penetration
   ceiling left the pool live, so a later shallow poke at a level nobody was
   defending still read as a raid. A breakout now consumes the pool.
3. **Cross-instrument state leak.** The liquidity map's clustering tolerance was
   held on the class, not the instance, so a multi-symbol portfolio would have
   shared one symbol's ATR scale across all of them.
4. **CVD window crash on session roll.** Cumulative delta re-anchors each
   session while the price window does not; the divergence check compared a full
   price window against an empty CVD window. Both are now required.
5. **Forex was permanently cost-bound.** The profile was cut against a retail
   dealing-desk spread, which vetoed every 5-minute bar as unprofitable-by-
   construction. Re-cut to a raw/ECN book with commission carried in currency.
6. **Synthetic tape had no price scale.** A $100 fixture against a $0.25 futures
   tick made every asset look cost-bound — an artefact of the fixture, not the
   engine. Tapes are now calibrated per asset class.

### 1.10 Deliverables
- `icarus/` — the engine, standard library only.
- `pine/icarus_engine.pine` — TradingView twin, same gates and weights.
- `tests/` — 96 tests, including a no-look-ahead guarantee that runs the engine
  on a prefix and on the full series and demands byte-identical intents.
- `python -m icarus {demo,backtest,walk,live}`.

### 1.11 Known limits, stated plainly
- The bundled synthetic tape is a **plumbing fixture**, not a market. It is a
  regime-switching random walk with no exploitable microstructure, so the engine
  correctly posts ~flat-minus-costs on it and the verdict line rejects it. No
  parameter has been tuned against it.
- Sentiment ships **neutral**. Live adapters (crypto funding/OI, equity
  put/call and breadth, FX positioning) are injectable but deliberately not
  fabricated here.
- Bar-level fills only. Sub-bar sequencing, queue position and partial fills
  need a tick-level model; the current model resolves stop-before-target, which
  is pessimistic by design.
- One position at a time by design. Portfolio-level correlation control is not
  yet implemented.

## 2. v1.1.0 — The exit layer (2026-09-20)

Source: **ICARUS PROTO SUITE 01** running on MNQ1! 10m, transcribed frame by
frame from a screen recording of its input panel and live HUD. The Suite holds
trades ~10 bars; v1.0.0 routinely opened and closed on the same bar. This entry
is the diagnosis, the transplant, and the measured result.

### 2.1 The diagnosis, measured on the engine's own blotter

Instrumented `_open_position` to record stop distance in ATRs at every entry,
across 12,000 synthetic bars per asset:

| asset | trades | same-bar deaths | median hold | **median stop (ATR)** | exits that were stops |
|---|---|---|---|---|---|
| equity | 21 | 14.3% | 3 bars | 1.15 | 52% |
| futures | 38 | 21.1% | 3 bars | 1.04 | 63% |
| forex | 21 | 4.8% | 8 bars | 1.74 | 81% |
| crypto | 109 | 8.3% | 6 bars | 1.24 | **88%** |

**Root cause: the stop sat ~1 ATR from entry, and 1 ATR *is* one bar's expected
range.** The trade was therefore a coin flip on its own entry bar. Expected
first-passage time under diffusion scales with the *square* of the barrier
distance, so the Suite's 4.5-ATR stop buys roughly **16-20x the survival time**
— which is precisely the 3-bar vs 10-bar gap, and it is geometry, not alpha.

Two compounding faults behind the same symptom:
1. **A fixed 2.6R runner caps the winner** at exactly the size a stop-dominated
   loser side cannot pay for.
2. **The trail rode the raw bar extreme** (`bar.high - k*ATR`), which ratchets
   the stop up on every noise spike and is then taken out by the next one.

### 2.2 Exit policies (`icarus/exits.py`) — the refactor

Exit geometry is now a pluggable policy instead of a hardwired constant, so the
hold-time question is a first-class experiment:

1. **`PulseExit`** — v1.0.0 preserved verbatim as the experimental control. All
   97 pre-existing tests pass unchanged against it.
2. **`SuiteExit`** — the Suite's model: structure-anchored stop with the
   0.5xATR buffer, ATR floor/ceiling of 1.9/5.0, TP1 at 3xATR, **Trailing TP2
   replacing the static target**, Kalman trail at 1.5xATR + 0.3xATR buffer,
   endurance target at the opposite HTF edge.
3. **`HybridExit`** — the synthesis. Keeps Pulse's raid extreme as the premise
   (that is the genuine edge and it is not diluted), but **floors the stop at
   1.6 ATR** so it can never be a coin flip, pushes TP1 to 1.5R, banks less
   (40%) and runs more, then trails on the Kalman estimate toward a structural
   endurance target.

### 2.3 Adaptive filters (`icarus/filters.py`)

* **`FractalDimensionIndex`** — Ehlers FDI, ~1.0 trend to ~2.0 chop.
* **`AdaptiveKalman`** — scalar random-walk Kalman filter whose measurement
  noise *rises with FDI choppiness*, plus the Suite's shock handling (z-trigger
  2.5, decay 8 bars, boost 1.35x). Measured gain on MNQ: 0.131, median lag 0.9
  ATR. **This is what the trail now rides.** A test pins the behaviour: a
  20-ATR spike moves the estimate less than 5 points.

### 2.4 Micro Nasdaq as a first-class venue

`AssetClass.MICRO_FUTURES` (MNQ1!), calibrated bar-for-bar off the Suite's own
panel: $2/point, 0.25 tick, 05:30-15:30 ET, ATR length 25, structure pivot
length 3, cooldown 15 bars, `exit_policy="hybrid"`. `point_value` is threaded
through sizing and P&L, so a micro contract sizes correctly without the engine
needing to know what a micro contract is.

### 2.5 Timeframe engine (`icarus/timeframe.py`)

`resample()` aggregates to any timeframe on the wall-clock grid; `at_timeframe()`
rescales every **bar-count** parameter by the timeframe ratio and deliberately
leaves ATR-relative and fractional ones alone. Moving a 10m calibration to 2m
without this turns a 4-hour time stop into 48 minutes — a different strategy
wearing the same name.

### 2.6 The comparison bench (`icarus/lab.py`)

Runs the identical entry engine under different exit policies on the identical
tape, so every difference is attributable to the exit layer and nothing else.
Reports `same_bar_pct`, `median_hold`, `stop_pct`, `median_risk_atr` and
`mfe_capture` alongside the usual P&L, and runs the permutation null **under
each policy separately**.

### 2.7 Results — 90,000 synthetic MNQ bars, four timeframes

| policy | tf | n | medHold | sameBar% | stop% | riskATR | sumR | expR |
|---|---|---|---|---|---|---|---|---|
| pulse | 2m | 195 | 5.0 | 12.8 | 84.6 | 1.11 | −4.18 | −0.021 |
| **suite** | 2m | 182 | **11.5** | **3.3** | 69.8 | 1.90 | **+30.84** | **+0.169** |
| hybrid | 2m | 182 | 12.0 | 4.9 | 83.5 | 1.60 | +24.97 | +0.137 |
| pulse | 5m | 113 | 3.0 | 18.6 | 87.6 | 1.16 | −26.20 | −0.232 |
| suite | 5m | 108 | 9.0 | 7.4 | 63.0 | 1.90 | −12.66 | −0.117 |
| hybrid | 5m | 108 | 8.5 | 10.2 | 74.1 | 1.60 | −12.34 | −0.114 |
| pulse | 10m | 60 | 2.0 | 25.0 | 86.7 | 1.04 | −21.55 | −0.359 |
| suite | 10m | 56 | 5.0 | 5.4 | 62.5 | 1.90 | −19.23 | −0.343 |
| hybrid | 10m | 57 | 4.0 | 8.8 | 71.9 | 1.60 | −15.67 | −0.275 |
| pulse | 30m | 32 | 1.0 | 31.2 | 68.8 | 0.85 | −4.12 | −0.129 |
| suite | 30m | 31 | 7.0 | 3.2 | 54.8 | 1.90 | −6.92 | −0.223 |
| hybrid | 30m | 31 | 5.0 | 3.2 | 64.5 | 1.60 | −6.38 | −0.206 |

**Suite and Hybrid beat Pulse on expectancy at 4 of 4 timeframes.** Same-bar
deaths collapse from 12.8-31.2% to 3.2-7.4%. Median hold multiplies 2-7x. On
MNQ 10m the hybrid posts avg win +1.63R against avg loss −0.89R (payoff 1.83)
with a 16.9-bar mean hold, against Pulse's 4.

This is a **random-walk tape**, so absolute P&L is meaningless and mostly
negative, as it should be. The *relative ordering across four independent
timeframes* is the finding: it is mechanical, not fitted.

### 2.8 ML seam (`icarus/ml.py`)

* **`ModelVote`** implements the Suite's HUD contract exactly: `XGB5:67L/44S`
  resolves to a +0.207 directional edge.
* **`MLGate`** folds that vote in as an **eighth confluence layer** with
  staleness decay. `ConfluenceWeights.ml` defaults to **0.0** and an absent
  model scores a hard 0.5 — the engine behaves identically to before unless a
  real model is attached. A model that does not exist cannot move size.
* **`triple_barrier()`** labels each bar by which barrier price reached first,
  resolving an ambiguous bar pessimistically. This is the correct target for a
  trade-entry classifier; a plain forward return conflates a clean winner with
  one that first ran the stop.
* **`export_training_set()`** replays the engine and writes a 38-feature
  labelled matrix (`FEATURE_COLUMNS`), built from the same code path that runs
  live — **no train/serve skew by construction**.

### 2.9 Pine twin brought to parity

`pine/icarus_engine.pine` gains the exit-policy selector, ATR stop clamp,
Ehlers FDI, the scalar Kalman filter, HTF endurance target via
`request.security(..., lookahead_off)`, cooldown and daily-loss breakers, and
`$/point` sizing for MNQ.

### 2.10 What is still outstanding

* **No real MNQ bars have touched this.** Every number above is synthetic.
* **XGB5 is a socket, not a model.** No weights, no training data, no model
  artifact was supplied, so nothing is fitted and `ml` weight stays 0.0.
* **The bucketed financials data is not in this repository.** The exporter is
  ready to join it on timestamp; the data is not here.
* `ltf_strength` proxies the Suite's 2m/5m signal-failure read with order-flow
  pressure, because the core has one data feed. Labelled as a proxy in code.
* Not yet transplanted from the Suite: Permutation Entropy / TRC / Hurst vetoes,
  MAMA+FAMA, Cyber Cycle, Market Profile POC/VAH/VAL pools, Po3 state machine,
  Order Blocks, the 5-connection HTF vote, and the adaptive vote weights.

---

## Next

Priority order. Each must be justified by out-of-sample evidence on **real MNQ
bars** before it enters the core.

1. **Real data.** Export MNQ1! 2m or 10m history to CSV and re-run
   `python -m icarus compare --csv mnq.csv --asset micro_futures --permutations 200`.
   Every conclusion above is provisional until this happens.
2. **Train XGB5 on the engine's own features.** `export-features` already emits
   the labelled matrix; fit it, wrap the model behind `MLGate`, then raise
   `ConfluenceWeights.ml` off zero *only* if the permutation verdict improves.
3. **Join the bucketed financials** on timestamp into the feature matrix as
   additional columns; they need no engine change, only the join.
4. Transplant the Suite's veto stack: Permutation Entropy, TRC/Hurst bounds,
   and the composite divergence veto.
5. Market Profile POC/VAH/VAL as first-class liquidity pools.
6. The Suite's 5-connection HTF vote (1h/4h/1d/1w/1M) as an explicit gate.
7. Portfolio layer: correlation-aware concurrent risk across instruments.
