# Icarus Research Log — failures, near-misses, and what not to do

Every idea that was measured and did **not** survive, every idea that looked
like it worked and turned out to be an artefact, and every methodology trap
that produced a false positive.

**Why this file exists:** a discarded idea leaves no trace in the code, so the
same idea gets rediscovered, re-implemented and re-shipped months later on the
strength of the same misleading statistic. A negative result is only worth
what it cost once — this file is how it stays paid for.

**Rules of entry.** Nothing goes in this file unless it was actually run. Every
entry states the measurement, the numbers on **both** a tuning tape and a
held-out tape, and the mechanism behind the failure. "It felt wrong" is not an
entry.

**Standing caveat:** every number below is from synthetic tapes. They prove or
disprove *mechanisms*, not market edges. A mechanism that fails here is dead;
one that survives here is merely still a candidate.

---

## F-001 · Excursion-armed breakeven — FAILED

**Status:** implemented, swept, shipped disabled (`breakeven_arm_r = 0.0`).
**Date:** 2026-09-20 · **Commit:** `9f40ef8`

### The observation that started it
Hybrid policy, 239 trades on MNQ 2m: mean MFE **+2.063R**, mean realised
**+0.325R**. **1.737R handed back per trade.** Of trades that died at the stop:

| peak MFE | n | mean realised |
|---|---|---|
| 0.5–0.8R | 36 | −1.003 |
| 0.8–1.0R | 11 | −1.003 |
| 1.0–1.5R | 28 | −1.004 |

75 trades went up to +1.5R and took a **full −1.00R**. Mean of −1.00 to three
decimals across three independent bands = mechanical cause, not variance:
`first_target_r` is 1.5, so the stop only moved to entry when TP1 filled.
The leak was the same size as the entire profit (75R vs sumR +77.79).

### The fix, and why it failed
Arm breakeven off `max_favourable` — excursion **already made**, so it forecasts
nothing. Upper bound said +0.666R vs a +0.325R baseline.

| arm R | tune expR | scratch% | DD% | avg winner | **hold expR** |
|---|---|---|---|---|---|
| **0.0 (off)** | **+0.325** | 0.4 | 12.80 | **+3.157R** | **+0.228** |
| 0.4 | +0.134 | 57.0 | 11.95 | +3.093R | −0.008 |
| 0.6 | +0.157 | 40.6 | 17.92 | +3.009R | +0.014 |
| 0.8 | +0.173 | 28.4 | 19.72 | +2.806R | +0.175 |
| 1.0 | +0.203 | 18.7 | 16.36 | +2.717R | +0.212 |
| 1.2 | +0.225 | 10.4 | 17.63 | +2.963R | +0.215 |
| 1.5 | +0.329 | 0.4 | 12.76 | +3.157R | +0.225 |

**Every level is worse than off, on both tapes.** Drawdown *rises* while
expectancy falls, ruling out "safer but smaller".

### Mechanism
The `avg winner` column. Winners average **+3.16R** and pay for every loser.
Each scratch that saves a −1.00R also scratches a trade that was going to run,
and a runner is worth ~3x what the saved loser cost.
**The give-back is not slack in the system — it is the price of the runners.**

### Do not repeat
- Do not treat `mean MFE − mean realised R` as recoverable money. It is the
  cost of staying in winners. The upper-bound arithmetic was wrong by more than
  its own magnitude.
- Any exit change must be **swept across a range** and validated on a
  **held-out tape**. A single point estimate would have shipped this.
- `arm_r = 1.5` reproducing `arm_r = 0.0` to within noise is the correctness
  check that the code path is a genuine no-op at TP1's own R. Keep that check.

---

## F-002 · `htf_position` "edge" — LABELLING ARTEFACT

**Status:** caught before use. Labeller fixed.
**Date:** 2026-09-20

### The false positive
Quintile analysis of 20,506 tuning / 20,642 held-out labelled setups put
`htf_position` (where price sits inside the higher-timeframe range) at a
top-vs-bottom win-rate spread of **+0.3988 (tune) / +0.4233 (hold)** — the
largest effect in the study, and near-identical across tapes. Cross-tape
agreement on an effect that size is normally decisive.

It was an artefact of my own measurement.

### The defect
`triple_barrier()` placed its barriers in **price space** — `+2 ATR` above and
`−1 ATR` below — regardless of which way the setup pointed. So:

- a **long** had to travel **+2 ATR** to be scored a win;
- a **short** was scored a win on a **1 ATR** move.

Shorts therefore won far more often *by construction*, and every feature
correlated with trade direction inherited a spurious relationship with the
label. `htf_position` is strongly direction-linked (price near the range low
produces short setups), so it absorbed the entire artefact.

### The fix
`triple_barrier()` now takes `direction` and orients the barriers to the trade:
`upper_atr` is always the favourable excursion, `lower_atr` always the adverse
one. `mfe_atr` / `mae_atr` are likewise reported in the trade's own frame, so
longs and shorts are comparable.

### Do not repeat
- **Cross-tape agreement does not validate a measurement.** A defect in the
  labeller reproduces perfectly on every tape, because the defect is in the
  ruler, not the thing being measured.
- Audit any effect that is **much larger than everything else in the study**
  before acting on it. Size was the tell here, not inconsistency.
- Any direction-agnostic label applied to a directional strategy is suspect.
  Longs and shorts must face identical barriers **in the trade's own frame**.
- Every result produced before this fix is void and must be re-run.

---

## N-001 · `location` component is inverted — STRONG CANDIDATE, under validation

**Status:** cross-validated at 2m on P&L; multi-timeframe confirmation running.
**Date:** 2026-09-20

### How it surfaced
Quintile study over ~6,000 direction-correctly-labelled setups (post F-002 fix),
tuning tape vs held-out tape. Seven features showed cross-tape agreement. One
was **negative**:

| feature | tune spread | hold spread |
|---|---|---|
| c_momentum | +0.165 | +0.160 |
| **c_location** | **−0.162** | **−0.146** |
| c_structure | +0.142 | +0.161 |
| score | +0.126 | +0.146 |
| c_order_flow | +0.085 | +0.102 |
| pool_weight | −0.065 | −0.081 |
| target_room_atr | −0.068 | −0.044 |

A negative spread means the component's **top** quintile wins **less** than its
bottom. `c_location` carries weight 0.70 — the third-heaviest layer — so the
engine was systematically down-weighting its own best setups.

### Measured on P&L (not win rate — F-001's lesson)

| location | tune expR | hold expR | tune win% | **tune DD%** | hold DD% |
|---|---|---|---|---|---|
| normal 0.70 (shipped) | +0.339 | +0.254 | 44.6 | **12.80** | 10.16 |
| normal 0.35 | +0.428 | +0.283 | 46.9 | 8.34 | 10.94 |
| normal 0.00 (off) | +0.465 | +0.332 | 48.1 | 7.99 | 13.69 |
| inverted 0.35 | +0.570 | +0.403 | 51.3 | 9.00 | 11.93 |
| **inverted 0.70** | **+0.589** | **+0.503** | 51.8 | **7.15** | 10.10 |
| inverted 1.05 | +0.620 | +0.503 | 53.9 | 6.61 | 10.00 |

Monotone across the entire sweep, on both tapes. Expectancy roughly doubles
held out (+0.254 → +0.503) **and drawdown falls** (12.80% → 7.15% tuning).

### Why this is not F-001
F-001 improved one metric while drawdown rose — the signature of a risk/reward
trade dressed as an edge. Here expectancy and drawdown improve **together**,
monotonically, on tuning and held-out tapes. That combination is very hard to
produce by fitting.

### Mechanism
`_location_score` rewarded **discount** — price below VWAP for a long — and
penalised chasing. That is a **mean-reversion** premise.

Icarus trades a failed liquidity sweep plus a structure break. After a low is
raided and reclaimed, price is *supposed* to be pushing away from value. The
filter was penalising exactly the setups where the move had already started.
A mean-reversion location filter was bolted onto a momentum-continuation
strategy.

### Before this ships
1. Multi-timeframe confirmation (2m/5m/10m) — running.
2. Do **not** ship `1 - f(x)`: a pure inversion also flips the over-extension
   rolloff, turning "too stretched to chase" into "reward the most stretched".
   A correctly-premised function is being validated against the pure inversion.
3. Permutation null under the new premise.

### Transferable
A component can be **worse than useless** — actively anti-predictive — while
looking reasonable in code review. Score every confluence layer against a
correctly-labelled outcome before trusting its weight. The sign of a layer is
an empirical question, not a design decision.

---

## V-001 · pulse.py survives the permutation null — CONFIRMED, but my reading of WHY was wrong

**Status:** validated. p = 0.0164 on this session's synthetic MNQ tape.
**Date:** 2026-09-20

### The setup
Astra's `icarus_engine/strategy/pulse.py` driven through this session's
`shuffle_bars` permutation null (`tools/validate_pulse.py`), so both engines meet
the same tape and the same surrogates. 2,400 x 20m MNQ bars, neutral HTF/LTF
context, sessions off (the tape runs on a 24/7 UTC clock).

### One input changed the entire result

| | `Fixed Points` | `ATR-Based` |
|---|---|---|
| mean hold | **0.1 bars** | **15.2 bars** |
| win rate | 50.0% | **83.6%** |
| per-trade | −$87 | **+$5,457** |
| trades | 24 | 55 |
| net | −$2,097 | **+$300,111** |

`Fixed Points` ships NQ-sized distances — tp1 15, tp2 30, **sl 45 points**. On a
20-minute MNQ tape that stop sits **inside one bar's range**, so the trade is
decided on its own entry bar. It is not a strategy result at all; it is a
sizing artefact.

### The null, resolved

| runs | observed | null median | best surrogate | p |
|---|---|---|---|---|
| 12 | +$300,111 | −$13,661 | +$100,845 | 0.0769 |
| 60 | +$300,111 | −$3,435 | +$100,845 | **0.0164** |

Both p-values are exactly `1/(runs+1)` — **zero surrogates beat the observed
result in either run.** The first number was the test running out of
resolution, not a weak result, and reading it as "does not separate" was wrong.
The true p is bounded above by 0.0164 and may be lower.


### ⚠ CORRECTION (same day) — the tape was the problem, not the preset

I wrote above that "Fixed Points ships NQ-sized distances ... that stop sits
inside one bar's range", and concluded pulse.py was mis-sized. **That conclusion
was wrong, and the error was mine.**

Two mistakes, compounding:

**1. I benchmarked against `Inputs()` defaults, not the shipped preset.** The
defaults are tp1 15 / tp2 30 / sl 45. The preset the script actually ships with
— revealed by `test_shipped_presets_load`, which was failing in CI at the time —
is **tp1 100 / sl 80**. I never tested the real configuration.

**2. My synthetic tape is roughly 5x too volatile for NQ.** Measured on the
tape every result in this log was produced from:

| | my synthetic 20m tape | real NQ 20m (typical) |
|---|---|---|
| index level | ~29,960 | ~similar |
| median ATR(14) | **403.9 pts (1.35%/bar)** | ~60–90 pts (~0.25%/bar) |

So the shipped 80-point stop is **0.20 ATR on my tape** and roughly **1.0 ATR on
real NQ**. It is not a tight stop. My generator made it look like one.

Re-run with the real preset values, all three on the same tape:

| config | n | hold | win% | per-trade |
|---|---|---|---|---|
| `Inputs()` defaults 15/30/45 | 46 | 0.4 bars | 47.8% | −$24 |
| **shipped preset 100/80** | 50 | **0.6 bars** | 42.0% | +$90 |
| ATR-Based | 55 | 15.2 bars | 83.6% | +$5,457 |

The shipped preset also exits same-bar **on this tape** — because 0.20 ATR is
inside one bar either way. That is a statement about my generator, not about
pulse.py.

### What survives the correction
- ATR-scaled sizing beat fixed-point sizing **on this tape**, p = 0.0164 with
  zero of 60 surrogates beating it. That comparison is still valid: both
  configurations met the identical tape and surrogates.
- The general principle stands: a stop inside one bar's expected range makes the
  trade a coin flip on its own entry bar.

### What does NOT survive
- **The "two engines, same defect" claim is withdrawn.** My engine's 1.0–1.2 ATR
  median stop was genuinely tight in its own ATR terms. Astra's 80-point stop is
  ~1.0 ATR on the instrument it was tuned for. Those are not the same finding,
  and pairing them was flattering to my own diagnosis.
- Any conclusion in this log that depends on an **absolute price distance** is
  suspect until the generator is recalibrated. Relative comparisons between
  variants are unaffected — every variant met the same tape.

### Do not repeat
- **Benchmark against the shipped configuration, not the library defaults.** A
  dataclass default is not what the system runs.
- **Calibrate the synthetic generator against the real instrument's ATR before
  drawing any conclusion involving a price distance.** Checking one number —
  median ATR as a percentage of price — would have caught this before it
  produced a published finding.
- A failing test can carry the information that invalidates your result. These
  parameters came out of a CI failure I had already triaged as "just a missing
  file".


### FOLLOW-UP — root cause found, tape fixed, finding re-run

The 5x volatility was not a design flaw in the generator. It was a bug in
`synthetic_for`:

`_SYNTHETIC_CALIBRATION["micro_futures"]` sets `base_vol = 0.0011` for
**10-minute** bars. Every sweep in this project called
`synthetic_for(..., minutes=2)`, which overrode the bar size **and kept the 10m
volatility**. A 2m bar should carry `0.0011 / sqrt(5) ~= 0.00049`, so the base
tape ran 2.2x hot. The generator's regime runs are mildly trending — measured
ATR scaling exponent **0.57**, against 0.50 for a driftless random walk — so the
error compounded on resampling to ~3.5x by the 20m timeframe.

`synthetic_for` now rescales `base_vol` by `sqrt(requested / native)` whenever
`minutes` is overridden. Four tests pin it.

| timeframe | before | after | real NQ |
|---|---|---|---|
| 2m | 0.262% | **0.114%** | ~0.08–0.12% |
| 10m | 0.676% | **0.297%** | ~0.18–0.25% |
| 20m | 0.979% | **0.432%** | ~0.25–0.35% |

Still ~1.3x hot at the slow end, down from ~3.5x. The residual is the trending
regimes, and real intraday markets are mildly super-diffusive too, so it is
defensible rather than a bug.

**Re-run on the corrected tape** (6,000 x 20m bars, ~140 trades per config —
a far better sample than the original 24):

| config | n | hold | win% | per-trade |
|---|---|---|---|---|
| `Inputs()` defaults 15/30/45 | 126 | 0.2 bars | 59.5% | −$19 |
| shipped preset 100/200/80 | 138 | 1.1 bars | 58.7% | **+$254** |
| **ATR-Based** | 151 | **14.2 bars** | **86.8%** | **+$2,364** |

The shipped preset is **profitable, not broken** — my original "mis-sized" call
was wrong and stays withdrawn. But ATR-scaled sizing still beats it by ~9x on
expectancy with a 13-bar longer hold, on a tape that is now honestly calibrated.
`sl_pts = 80` is 0.50 ATR here and would be ~0.89 ATR on real NQ.

**The actionable version:** testing `tpsl_mode = "ATR-Based"` against the shipped
`Fixed Points` preset on real NQ data is worth doing. That is a one-input
change, and it is the only claim from this entry that survived contact with a
corrected tape.

### Why this matters beyond one script

**Two engines, built independently, carried the same defect.**

| | this session's engine | Astra's pulse.py |
|---|---|---|
| symptom | 8–21% of trades died on the entry bar | 0.1-bar mean hold |
| measured stop | 1.0–1.2 ATR median | 45 fixed points, narrower than a bar |
| fix | floor the stop in ATR terms (F-001 work) | `tpsl_mode = ATR-Based` |

The shared root cause: **a stop closer than one bar of expected range makes the
trade a coin flip on its own entry bar**, and no amount of signal quality
upstream can survive it. Arriving at the same conclusion twice, from two
codebases that share no lineage, is the strongest cross-validated finding in
this project.

### Do not over-read this
- Synthetic tape from one generator. Not evidence about real MNQ.
- HTF/LTF context was held neutral, which **disables the MTF vote** and likely
  understates pulse.py rather than flattering it.
- 55 trades is a modest sample.
- The 83.6% win rate clears the 80% target, but on a tape that owes its
  structure to a random-number generator.

---

## Methodology traps this project has already hit

1. **Upper-bound arithmetic ignores the cost side.** (F-001)
2. **A defect in the ruler reproduces on held-out data.** (F-002)
3. **Sample size masquerading as edge.** A ~24-trade sample read +0.159R
   expectancy; the same configuration over ~36 trades read −0.367R. Nothing
   under ~150 trades should be quoted at all.
4. **Selection over configurations.** The reference chart carried four
   instances of the same script with different parameter sets. Reporting the
   best of N without correcting for N is the most common way a backtest lies.
5. **A confluence layer can be anti-predictive.** `c_location` shipped at
   weight 0.70 with the wrong sign for the strategy it serves. Design
   intent is not evidence; score every layer against labelled outcomes.
6. **A p-value pinned at `1/(runs+1)` is a resolution limit, not a result.**
   A first pass read p = 0.0769 and was reported as "does not separate".
   Zero of twelve surrogates had beaten it — the test had simply run out of
   runs. At 60 surrogates the same result reads p = 0.0164. Always check
   whether p equals its own floor before concluding anything.
7. **A mis-calibrated synthetic generator invalidates absolute results.**
   The MNQ tape ran ~5x real NQ volatility (1.35% vs ~0.25% per 20m bar),
   which made a correctly-sized 80-point stop look like a 0.20 ATR coin
   flip. Relative comparisons survived; the causal story did not. Check
   median ATR as a percent of price against the real instrument first.
8. **Score-0 rows polluting a decile study.** 80% of exported rows carry
   `score = 0` because a hard gate vetoed before scoring. Including them made
   the confluence score look predictive when the deciles were mostly noise.
   Restrict any score study to actually-scored setups.

---

## F-003 — Hold-time duration bands (NEGATIVE, circular)

**The observation.** Bucketing closed trades by how long they were held showed
win rate climbing monotonically on every timeframe, flipping sign at ~32 bars
regardless of whether that meant two hours or twenty-one:

| tf | 16–32 bars | 32–64 | 64–128 | 128+ |
|----|-----------|-------|--------|------|
| 5m | 39.7% | 64.9% | 72.4% | 88.2% |
| 10m | 40.4% | 55.4% | 69.2% | 80.0% |
| 20m | 48.3% | 62.0% | 80.0% | — |

Seven clean bands, no reversal, consistent across timeframes, and the top band
was the first thing in this project to touch 80% on real data. It looked like
the find of the search.

**Why it is circular.** A trade survives to 64 bars BECAUSE it never hit its
stop. Losers are terminated early by construction, so the long bands are
pre-selected winners and the short bands are where the losses were sent. The
table cannot distinguish "long holds win" from "holding longer causes winning";
it is close to a tautology dressed as a discovery.

**The falsifiable version.** `tools/time_stop.py` states the claim as rules a
live chart could follow — `min_hold` withholds the profit target until the
trade is old enough (stop stays live throughout), `max_hold` forces flat at N
bars. These change behaviour rather than filtering outcomes.

**The verdict, 5m ATR-Based, real MNQ:**

```
              TUNE         HOLD
min_hold  0   +$1,704    +$19,689
min_hold 32     +$425    +$33,574
min_hold 64   +$5,605    +$18,947
max_hold 32  -$13,702    +$30,653
max_hold128     -$560    +$15,462
```

Two independent reasons this is noise:

1. TUNE is flat-to-negative at **every** setting while HOLD shows large
   positives. No setting has both spans agreeing.
2. **Opposite rules produce the same improvement.** Forcing trades to stay in
   longer (min_hold 32) gives +$33,574; forcing them out sooner (max_hold 32)
   gives +$30,653. A genuine duration effect cannot be improved by both
   lengthening and shortening holds. That is the same span-specific noise
   reached from two directions.

**What not to do next time.** Never rank a strategy by a statistic computed on
the trade's own survival. Duration, MFE, MAE and bars-to-target are all
outcome-conditioned: slicing by them always produces a monotone-looking
gradient because the stop already removed the counterexamples. If a claim about
hold time matters, express it as a rule that changes what the engine does, run
it on both spans, and check that opposite versions of the rule do not both
"work".

**What survived.** The hold-time *metrics* are worth keeping — `overnight_rate`
and `overnight_net_share` caught a configuration whose entire profit was
overnight carry, which no other number in the report exposed. Measuring hold
time was right. Ranking by it was not.

---

## N-002 — Cross-asset context (INCONCLUSIVE, mostly noise)

Pulled QQQ, NVDA, TLT and NDX cash, aligned causally to the MNQ grid
(`tools/cross_asset.py`). Split the overlap window into two adjacent six-week
halves and measured each feature's tercile spread against MNQ's forward 4h
return. **Seven of nine features reversed sign between the halves**, including
the largest apparent effect (NVDA leading the index, −14.42 → +8.59 points).
Only realised volatility held its sign (+8.77 → +15.43), and three months is
far too short to call even that.

Not a refutation of cross-asset data — the sample is too small — but a
refutation of trusting any of these features on one window. `spread_test` now
gates every candidate feature before it reaches the confluence layer.

**Note on fundamentals.** Company financials are the wrong family for this
horizon: they are constant across the life of a 25-bar trade, so they have no
variance at the decision frequency and cannot discriminate between setups.
Dealer gamma, opex and rebalance flow, and auction imbalance are the families
that actually move intraday index price.

---

## N-003 — HTF capture from the LTF (structurally confirmed, not yet profitable)

**The idea, from the operator:** stop predicting at the higher timeframe. Let
the HTF define *what* the move is and use the LTF to define *where* to enter
and exit. This is a capture question, not a prediction question, and the two
failure modes are unrelated -- a signal can carry no directional edge while the
market still hands over large, reachable moves.

**Structure (HTF 60m, LTF 5m, real MNQ):**

| | TUNE | HOLD |
|---|---|---|
| directionality, big bars | 0.59 | 0.58 |
| concentration, big bars | 0.17 | 0.17 |
| big bars where one 5m bar carried >60% of travel | 0/1204 | 0/1139 |

Large HTF moves are genuinely directional and **not one a single print** --
zero out of 2,343 big bars across both spans arrived in one LTF bar. They
develop progressively, so they are structurally reachable from below. This is
the operator's hypothesis, confirmed, and it is stable on held-out data.

**Volatility conditioning does not help.** MFE/MAE sits at 0.86-1.02 across
every prior-volatility quintile on both spans. Knowing volatility will be high
predicts a BIGGER move, but MFE and MAE scale together and the ratio is
invariant. Volatility predicts magnitude, and magnitude is symmetric.

**The blocker is entry price, and it is measurable.** With a commitment trigger
at 0.5 ATR from the window open:

```
stop  target   target-first   stop-first
0.50    0.50        5.1%         94.8%
0.50    1.50        2.5%         96.8%
1.00    1.00       45.5%         50.7%
```

Entering ON commitment buys the local extreme of the move that just printed,
then places a tight stop beneath it. The adverse excursion arrives first 95% of
the time. Widening the stop converges to the coin flip an efficient market
predicts. This is not the market refusing to trend; it is the entry paying the
worst available price.

**Pullback entry moves in the right direction but does not clear zero.**
Waiting for a retracement after commitment, with the stop behind the leg's
origin rather than under the spike, improves monotonically with retracement
depth -- expectancy -0.312R to -0.127R, win rate 34% to 44%, TUNE and HOLD
agreeing throughout. Still negative. Deeper retracements and structure-based
stops are the open thread.

**Status: open, not refuted.** The geometry is confirmed; the entry price is
not solved.

---

## Methodology trap 8 — a biased comparison defeats every statistical gate

Two versions of the premise estimator shipped a broken control group and both
produced cells surviving false-discovery-rate control across 1,692 tests, with
p-values to 0.00002 and effects of 1.4 ATR.

The first used `set(directions)`, collapsing a bucket of 90 long sweeps and 10
short into a 50/50 control mix, so on a trending tape the sweeps kept the drift
the controls averaged away. The second fixed that per bar but still POOLED both
groups before comparing, which compares a morning-heavy treated mean against an
all-day control mean whenever the strata hold different proportions of each.

What exposed it was not statistics but shape: IWM reported +1.39 ATR and SPY
-1.51 ATR -- equal and opposite, same asset class, over windows where one rose
and the other fell. An expected move of 1.4 ATR would be the most profitable
signal in finance.

FDR control, matched samples and two-span agreement all assume the comparison
is sound. None can see a biased one. Only a synthetic tape where the answer is
known by construction can, and it needs BOTH directions: tests that drift is
removed, and a test that a planted effect still survives -- a control that
erases everything is as useless as one that erases nothing.

---

## F-004 — The sweep premise does not replicate (NEGATIVE, cross-asset)

The engine's founding thesis is that a liquidity sweep -- price taking out a
prior extreme and reclaiming it -- is followed by a move in the REVERSAL
direction. Tested directly, with no confluence layer, no ML gate, no exit
policy and nothing to fit: 1,692 cells across 10 markets in five asset classes,
each market split into two halves, effects estimated within time-of-day and
volatility strata, Benjamini-Hochberg applied across the whole grid.

**The estimator fix mattered more than the result.** Three versions:

| control construction | FDR survivors | IWM +1.3 ATR cells |
|---|---|---|
| `set(directions)`, pooled | 9 | present |
| per-bar direction mix, pooled | 11 | present |
| **stratified** | **4** | **gone** |

The IWM cells that looked like the find of the search -- +1.39 ATR, p=0.00002,
surviving FDR across 1,692 tests -- disappeared entirely once the comparison
was made within strata. They were drift.

**What remains does not support the premise.** All four survivors are from one
span, at the longest lookback (40) and longest horizon (48), and all four are
NEGATIVE -- continuation, not reversal. Three are SPY in a window where SPY
fell (its cells are 16% positive in the late half against 49% in the early
half); a structural effect would appear in both.

**Sign agreement between halves, per market:** 33, 43, 46, 54, 56, 56, 58, 59,
69, 73 percent. Pooled 54.5% over 846 cells. The pooled z of +2.61 is NOT
reported as significant: the cells within a market are heavily dependent
(overlapping sweeps, nested lookbacks, overlapping horizons), so the
independence the z-score assumes does not hold. USO at z=-3.23 -- systematic
*anti*-agreement -- is the proof, because noise does not produce that either.

**The one consistent signal points the other way.** MNQ at 10m has the most
stable sign in the panel (73% agreement) and its effects are NEGATIVE in both
halves (30% and 17% of cells positive). On that tape, sweeps CONTINUE rather
than reverse. This is the second time continuation has beaten reversal here:
the location-score work found the same thing on the synthetic tape, where a
continuation reading of location outscored the shipped mean-reversion reading.

**Verdict.** The premise is not supported. The strongest consistent effect in
ten markets points opposite to the thesis the engine is built on. That is
consistent with the permutation null on the finished strategy (p=0.377
held-out): an entry signal indistinguishable from random is what a false
premise produces downstream.

**Next thread, not a conclusion.** Continuation has now appeared twice from
independent directions. It is a hypothesis to test properly -- with the same
stratified controls, both spans and FDR -- not a result to act on.

---

## F-005 — H-LOC, the location sign, on real data (NEGATIVE; the synthetic tape was wrong)

The synthetic tape said `_location_score` was signed for the wrong strategy:
inverting it lifted 2m expectancy from +0.339R to +0.589R, with the sign
agreeing across two seeds. Re-tested on real MNQ as a continuous coefficient
L, where L=+1 is shipped behaviour and L=-1 is full inversion.

**Transfer to pulse.py, ATR-Based, best held-out L per timeframe:**

| tf | best HOLD L | HOLD net | L=+1 HOLD net | TUNE agrees? |
|----|------------|----------|---------------|--------------|
| 5m | **+1.00** | +$19,689 | +$19,689 | yes, +$1,704 |
| 20m | **+1.00** | +$14,487 | +$14,487 | yes, +$27,076 |
| 10m | -0.50 | +$23,513 | +$8,009 | **no** -- TUNE -$21,780 |
| 30m | +0.75 | +$4,500 | -$3,689 | TUNE +$34,524 |

At 5m and 20m the best held-out value IS the shipped one. The synthetic result
does not transfer; it inverted the conclusion, exactly as the session-only tape
did elsewhere.

**The one case that looked like a win was nulled properly.** 30m, L*=+0.75,
+$8,188 better than shipped on held-out data. Against 60 surrogates:

```
ABSOLUTE   null median $-4,246   best $+61,928   p = 0.3770
PAIRED     delta median $+2,681  best $+17,443   p = 0.1639   (floor 0.0164)
```

The paired test is the right one -- it asks whether L*=+0.75 beats L=+1 by more
than shuffling would produce -- and it fails at p=0.16.

**Verdict: H-LOC is refuted on real data.** The location term's shipped sign is
correct at the timeframes where both spans agree. The synthetic evidence that
launched this hypothesis (a -0.16 feature spread agreeing across two seeds) was
a property of `synthetic_for`, not of markets.

**What this cost and what it bought.** Four separate results from the synthetic
tape have now inverted on real data: the 83.6% win rate, the location sign, the
hold-time gradient, and the cross-asset breadth features. The tape is not a
weak proxy for the market; it is an unrelated process that happens to look like
one. Nothing measured on it should be carried forward without re-testing.

---

## F-004 (closed) — 16-market replication refutes the premise, and the continuation lead with it

F-004 left two things open: whether the sweep premise replicates, and whether
the CONTINUATION signal at MNQ 10m (73% half-to-half sign agreement, negative
both halves) was real. Six more markets were added -- volatility, an energy
sector, silver, intermediate rates, the dollar, emerging -- bringing the panel
to 16 markets across nine asset classes, 2,772 cells.

**Adding independent markets REDUCED the apparent signal:**

| panel | cells | raw p<0.05 | expected by chance | survive FDR |
|---|---|---|---|---|
| 10 markets | 1,692 | 176 | ~85 | 4 |
| **16 markets** | **2,772** | **245** | **~139** | **1** |

The lone survivor is the same SPY cell as before: one span, longest lookback,
longest horizon, in a window where SPY fell. If a real effect existed, more
markets would sharpen it. Fewer survivors on more data is what multiple-testing
noise does when the correction is applied honestly.

**Sign agreement is BELOW chance:**

```
pooled          46.5%  over 1,386 paired cells   (chance 50%, z = -2.60)
median market   50.0%  -- exactly chance
below 50%       8 of 16 markets
```

Systematic *dis*agreement between halves is not noise and not a real effect.
It is drift: each half carries its own directional tilt, and the sweep effect
reads it with opposite sign in each. The swings are enormous -- IEF goes from
13% positive cells to 83% (+70pp), EEM 90% to 27% (-63pp), VXX 77% to 26%.

**The continuation lead was an order statistic.** MNQ 10m's 73% agreement is
the MAXIMUM of sixteen draws whose median is exactly 50%. Nothing about it
survives being placed next to fifteen siblings. It was logged as a thread to
test rather than a result, and testing it is what killed it.

**Verdict.** The liquidity-sweep premise -- reversal OR continuation -- is not
supported in any market on the panel. This is consistent with everything
downstream: a permutation null on the finished strategy at p=0.377 held-out is
what an entry signal built on a false premise produces.

**What this does not say.** It does not say the engine is worthless or that no
intraday edge exists. It says that THIS trigger, taking out a prior extreme and
reclaiming it, carries no directional information at these horizons. The
structural result in N-003 still stands on held-out data: large HTF moves
develop progressively and are reachable from a lower timeframe. That problem is
an execution problem, and it is untouched by this.

---

## N-004 — Time of day (NEGATIVE), and the conditioning search closes

Time of day was the last conditioner worth trying, and the only one known with
certainty in advance: it is not forecast, it is the clock. Intraday
seasonality is among the most durable regularities in equity markets, so if
the commitment trigger carried direction anywhere, the open or the close were
the places to look.

Commitment entry at 0.5 ATR, HTF 60m, sliced into 23 ET hourly buckets, both
spans:

```
buckets positive on BOTH spans:   2   (04:00 and 11:00)
expected by chance:             5.75   (23 x 0.25)
```

Fewer than chance, and both survivors are hollow -- 11:00 is +0.000R on the
tuning span, and 04:00 reads +0.046R against +0.292R, a six-fold discrepancy
that is not a stable effect. Bucket means are predominantly negative
throughout, which is what a trigger that enters at a local extreme and pays
the spread produces.

**The conditioning search is now complete:**

| conditioner | tested on | result |
|---|---|---|
| sweep structure | 16 markets, 2,772 cells | no directional information (F-004) |
| prior volatility | 5 quintiles, both spans | MFE/MAE invariant at ~0.90 |
| cross-asset breadth | 9 features, two halves | 7 of 9 reverse sign (N-002) |
| time of day | 23 buckets, both spans | fewer both-span positives than chance |

**What this says, precisely.** At 5-to-60-minute horizons on MNQ, the direction
of the next move is not predictable from any of: the sweep trigger, the
volatility regime, related instruments, or the clock. That is what market
efficiency looks like at this resolution, and it is consistent with the
permutation null on the finished strategy (p=0.377 held-out).

**What it does not say.** It does not say no edge exists. It says none of the
PRICE-DERIVED conditioners tested carry direction. Three things remain
genuinely untested rather than refuted:

1. **True order flow.** Aggressor-side volume is the one input that is causal
   to price formation rather than derived from it. Astra's
   `icarus_engine/microstructure.py` is built and correct and waiting on a tick
   feed this plan does not entitle.
2. **Options positioning.** Dealer hedging is mechanical, published, and
   largely ignored by retail. Per-strike aggregates ARE entitled; open
   interest is not, so only a volume-weighted proxy is reachable.
3. **Cross-sectional lead-lag.** N-002 tested cross-asset features against
   MNQ. It did not test lead-lag STRUCTURE across the thirteen-market panel,
   which is a different question and is now cheap to ask.

The structural result in N-003 also stands untouched: large HTF moves develop
progressively and are reachable from a lower timeframe, on held-out data. What
is missing is direction, not geometry.

---

## N-005 — Cross-sectional lead-lag (NEGATIVE in aggregate; what replicates is not tradeable)

The last untested price-derived idea. N-002 asked whether cross-asset features
predict MNQ; this asks whether any market in the thirteen-market panel leads
any other, which is a different question.

The test subtracts the lagging market's OWN past return from both the predictor
and the target before measuring. Without that, a raw cross-correlation between
two co-moving assets is mostly contemporaneous overlap plus each one's own
autocorrelation, and reports "leads" that are neither predictive nor tradeable.
Every ordered pair is split at the median of its own shared timestamps, because
the panel's coverage is heterogeneous -- QQQ and NVDA sit in 2024 while most
markets sit in 2026, so one calendar split leaves most pairs with no early half.

**Aggregate: chance.**

```
lag 15min   60/116 pairs hold sign   52%   z = +0.37
lag 30min   65/116 pairs hold sign   56%   z = +1.30
lag 60min   55/116 pairs hold sign   47%   z = -0.56
```

**What replicates is the same exposure in two wrappers:**

```
TLT -> IEF   +0.092 / +0.098    both Treasury ETFs
USO -> XLE   +0.104 / +0.078    oil -> oil companies
SLV -> GLD   +0.056 / +0.068    silver -> gold
```

These are not leads. They are one piece of information arriving at two closely
linked instruments at slightly different speeds, which is what the residual
control cannot remove because the instruments genuinely share an underlying.
Magnitudes of 0.05-0.10 residual correlation do not survive costs.

The only cross-complex pair to hold was TLT -> IWM (+0.059 / +0.102 at 60min),
rates leading small caps -- economically sensible, still far too small to
trade, and IWM is not the instrument in question.

**Verdict.** No tradeable lead-lag structure in the panel. With this, every
price-derived conditioner has been tested and none carries usable direction at
intraday horizons.
