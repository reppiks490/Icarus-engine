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

---

## Next

Candidate refinements, in priority order — each must be justified by out-of-sample
evidence on real bars before it enters the core:

1. Tick/footprint order flow to replace the close-location proxy where available.
2. Volume-profile value area (POC / VAH / VAL) as a first-class pool type.
3. Higher-timeframe bias as an explicit gate rather than an implicit one.
4. Live sentiment adapters behind the existing injection point.
5. Portfolio layer: correlation-aware concurrent risk across instruments.
