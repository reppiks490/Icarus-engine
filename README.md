# Icarus Engine

**One intraday system. Four asset classes. No dilution.**

Icarus is a single, cohesive intraday strategy — not a library of strategies. It
hunts exactly one thing, on every venue it is pointed at:

> A known pool of resting liquidity is raided, the raid **fails**, the level is
> **reclaimed**, and order flow plus market structure confirm the failure —
> inside a volatility regime worth paying the spread for.

Everything in this repository exists to trigger that idea, confirm it, veto it,
size it, or prove whether it is real.

---

## The DNA

| Layer | Question it answers | Module |
|---|---|---|
| **Liquidity** | Where are the stops, and did price just raid them and fail? | `icarus/features/liquidity.py` |
| **Order flow** | Who absorbed that raid — and is cumulative delta confirming the failure? | `icarus/features/orderflow.py` |
| **Structure** | Did the market actually change hands (BOS / CHoCH), or was that just a wick? | `icarus/features/structure.py` |
| **Volatility** | Is this tape worth trading at all, or is the target inside the spread? | `icarus/features/volatility.py` |
| **Location** | Are we buying discount and selling premium against session value? | `icarus/signal.py` |
| **Sentiment** | Is the external bias with us? *(scales conviction — never flips direction)* | `icarus/features/sentiment.py` |
| **Confluence** | What is the composite conviction, and does it clear the bar? | `icarus/signal.py` |
| **Risk** | How much size, where is the stop, and when do we stand down? | `icarus/risk.py` |

### Rules that do not bend

1. **The sweep is the only trigger.** No other layer can originate a trade.
2. **Hard gates are boolean; soft layers are continuous.** A closed session, a
   dead or shocked tape, or no room to the next pool kills the trade outright.
   A weak confirmation only drains conviction.
3. **Direction comes from price.** Sentiment and momentum scale the score. They
   cannot produce a short out of a bullish sweep.
4. **Strict causality.** A decision made on bar *t* fills on bar *t+1*'s open.
   This is enforced inside `IcarusEngine.on_bar`, and it is covered by a test
   (`test_no_look_ahead_truncating_the_future_cannot_change_the_past`) that runs
   the engine on a prefix and on the full series and demands identical intents.
5. **Friction is modelled, not assumed away.** Spread, volatility-scaled
   slippage and commission are charged on entry and on every exit.
6. **When both a stop and a target sit inside one bar, the stop filled.**
   Optimistic intrabar ordering is how backtests lie.

---

## One system, four calibrations

The profiles in `icarus/config.py` never change *what* Icarus looks for. They
re-scale its senses to the microstructure of each venue.

| | Equity | Futures | **Micro (MNQ)** | Forex | Crypto |
|---|---|---|---|---|---|
| Sessions | US RTH drives | RTH + London overlap | 05:30–15:30 ET | London / NY killzones | 24/7 |
| Order-flow weight | 0.95 | **1.10** (real aggressor data) | 1.05 | 0.70 (proxy only) | 1.05 |
| Sentiment weight | 0.35 | 0.20 | 0.25 | 0.35 | **0.45** (funding) |
| Max sweep depth | 1.30 ATR | 1.30 ATR | 1.30 ATR | 1.30 ATR | **1.60 ATR** (fat tails) |
| Risk / trade | 0.50% | 0.60% | 0.60% | 0.40% | 0.40% |
| Point value | 1.0 | 1.0 | **$2 / pt** | 1.0 | 1.0 |
| Exit policy | pulse | pulse | **hybrid** | pulse | pulse |

---

## Exits: the hold-time problem, and the fix

v1.0.0 routinely opened and closed a trade **on the same bar**. Instrumenting
the blotter showed why, and the number is unambiguous:

> **The median stop sat 1.0–1.2 ATR from entry — and 1 ATR *is* one bar's
> expected range.** The trade was a coin flip on its own entry bar. 8–21% died
> there; 52–88% of all exits were stops.

Expected first-passage time under diffusion scales with the **square** of the
barrier distance. A 4.5-ATR stop therefore buys roughly 16–20× the survival of a
1.1-ATR stop. That is geometry, not alpha — and it is the entire gap between a
3-bar hold and a 10-bar hold.

Two faults compounded it: a fixed 2.6R runner **capped the winner** at exactly
the size a stop-dominated loser side could not pay for, and the trail rode the
**raw bar extreme**, ratcheting up on every noise spike and getting taken out by
the next one.

Exit geometry is now a pluggable policy (`icarus/exits.py`):

| | `pulse` | `suite` | `hybrid` |
|---|---|---|---|
| Stop anchor | raid extreme | structural swing | raid extreme, or a further swing |
| Stop floor | **none** | 1.9 ATR | 1.6 ATR |
| First target | 1.0R | 3.0 ATR | 1.5R |
| Banked at TP1 | 55% | 50% | 40% |
| Runner | **fixed 2.6R** | HTF edge, else unbounded | HTF edge, else unbounded |
| Trail anchor | **raw bar extreme** | Kalman estimate | Kalman estimate |

Measured on 90,000 synthetic MNQ bars, resampled to four timeframes:

| policy | tf | n | medHold | sameBar% | riskATR | expectancy |
|---|---|---|---|---|---|---|
| pulse | 2m | 195 | 5.0 | 12.8% | 1.11 | −0.021R |
| **suite** | 2m | 182 | **11.5** | **3.3%** | 1.90 | **+0.169R** |
| hybrid | 2m | 182 | 12.0 | 4.9% | 1.60 | +0.137R |
| pulse | 10m | 60 | 2.0 | 25.0% | 1.04 | −0.359R |
| suite | 10m | 56 | 5.0 | 5.4% | 1.90 | −0.343R |
| hybrid | 10m | 57 | 4.0 | 8.8% | 1.60 | −0.275R |

**Suite and Hybrid beat Pulse at 4 of 4 timeframes.** The tape is a random walk,
so the absolute P&L is meaningless — the *consistent relative ordering across
four independent timeframes* is the finding, and it is mechanical.

```bash
python -m icarus compare --asset micro_futures --timeframes 2m,5m,10m,30m
```

## Timeframes

A parameter measured in *bars* is really measured in *time*. `at_timeframe()`
rescales every bar-count field by the timeframe ratio and deliberately leaves
ATR-relative and fractional fields alone — moving a 10m calibration to 2m
without that turns a 4-hour time stop into 48 minutes, which is a different
strategy wearing the same name.

```bash
python -m icarus demo --asset micro_futures --timeframe 2m --policy hybrid
```

## Machine learning: the socket, not a model

The Suite's HUD carries `XGB5:67L/44S` — a model voting 67 long against 44
short. `icarus/ml.py` implements that contract (`ModelVote.edge` → +0.207) and
folds it in as an **eighth confluence layer**, under the same discipline as
sentiment: it scales conviction, it can never originate a trade, and it can
never flip a direction that price set.

`ConfluenceWeights.ml` defaults to **0.0** and an absent model scores a hard
0.5. **Nothing is fitted here and no model ships with this repository** — a
model that does not exist must not be able to move size.

What *is* shipped is the part that makes training possible:

```bash
python -m icarus export-features --asset micro_futures --out train.csv \
    --upper-atr 2.0 --lower-atr 1.0 --horizon 24
```

This replays the engine and writes a 38-feature labelled matrix built from the
**same code path that runs live**, so there is no train/serve skew by
construction. Labels are triple-barrier (did a 2-ATR favourable move happen
*before* a 1-ATR adverse one), resolved pessimistically when one bar spans both
— which is the question the strategy actually faces, unlike a plain forward
return.

## Running it

The core has **no third-party dependencies** — standard library only, so the
same code path runs in a research loop and inside a live broker callback.

```bash
# Built-in synthetic tape, calibrated to each asset's real price scale
python -m icarus demo --asset crypto --bars 8000 --permutations 50

# Your own data
python -m icarus backtest --csv data/es_5m.csv --asset futures --permutations 100

# Contiguous walk-forward folds (never shuffled — regime change is the point)
python -m icarus walk --csv data/es_5m.csv --asset futures --folds 5

# Replay and print every order intent as it fires
python -m icarus live --csv data/es_5m.csv --asset futures --tail 40

python -m icarus compare --asset micro_futures --timeframes 2m,5m,10m,30m
python -m icarus export-features --asset micro_futures --out train.csv

pytest                                   # 166 tests
```

CSV columns are matched loosely (`ts|time|timestamp|date`, `o|open`, …). Supply
`bid_volume` / `ask_volume` when your venue serves them and the order-flow layer
switches from the close-location proxy to true aggressor delta automatically.

### Embedding

```python
from icarus import AssetClass
from icarus.strategy import IcarusEngine

engine = IcarusEngine(AssetClass.CRYPTO, starting_equity=100_000)
for bar in feed:                          # your bars, oldest first
    for intent in engine.on_bar(bar):     # ENTER / SCALE_OUT / MOVE_STOP / EXIT
        broker.submit(intent)
```

### Chart twin

`pine/icarus_engine.pine` is the TradingView implementation of the same logic —
same gates, same scoring weights, same risk envelope, `process_orders_on_close`
set so fills land on the next bar. TradingView does not serve aggressor volume
on standard bars, so the Pine version always runs the delta proxy.

---

## Proving an edge, not drawing one

`PerformanceReport.verdict` is deliberately hostile to its own strategy. It will
not return `ACCEPT` unless the run clears **all** of:

* at least 30 trades,
* positive summed R,
* a permutation p-value below 0.05,
* expectancy of at least 0.05R.

The permutation test (`icarus/backtest.py`) rebuilds the tape from the same bars
in shuffled order — preserving the return distribution and every bar's internal
shape while destroying the sequence — and re-runs the whole engine. If shuffled
noise reproduces your equity curve, you do not have an edge; you have a drawing.

### Honest status of the bundled numbers

`python -m icarus demo` runs on a **seeded synthetic tape**, which is a plumbing
fixture, not a market. It is a regime-switching geometric random walk: it has no
exploitable microstructure, so the correct result is roughly *flat minus costs*,
and that is what it prints — the engine posts small negative expectancy across
all four profiles and the verdict line rejects it. That is the null hypothesis
behaving. **No parameter in this repository has been tuned to make the synthetic
tape profitable**, because a parameter set that beats a random walk is a
parameter set fitted to noise.

Point it at real bars before drawing any conclusion, and demand the verdict.

---

## Layout

```
icarus/
  config.py              asset-class calibrations, cost models, confluence weights
  data.py                Bar, CSV loading, seeded synthetic tapes
  indicators.py          streaming O(1) primitives (ATR, RSI, EMA, session VWAP)
  filters.py             Ehlers FDI + FDI-adaptive Kalman filter (the trail anchor)
  exits.py               pulse / suite / hybrid exit policies
  timeframe.py           resampling and honest bar-count rescaling
  ml.py                  model-vote contract, triple-barrier labels, feature export
  lab.py                 policy x timeframe cross-examination bench
  features/
    structure.py         fractal pivots, trend state, BOS / CHoCH
    liquidity.py         pool map + sweep state machine
    volatility.py        regime gate and fitness
    orderflow.py         CVD, delta stats, absorption, divergence
    sentiment.py         pluggable bias overlay with age decay
  signal.py              confluence scoring and the hard gates
  risk.py                sizing, daily loss limit, streak throttle, stop geometry
  execution.py           intents, positions, fills, friction, blotter
  strategy.py            IcarusEngine -- the master system
  backtest.py            event-driven backtest, metrics, permutation null, walk-forward
  cli.py                 python -m icarus
pine/icarus_engine.pine  TradingView twin
tests/                   166 tests, including the no-look-ahead guarantee
CHANGELOG.md             numbered progression of the system
```

See `CHANGELOG.md` for the numbered record of every refinement.
