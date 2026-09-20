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

## Methodology traps this project has already hit

1. **Upper-bound arithmetic ignores the cost side.** (F-001)
2. **A defect in the ruler reproduces on held-out data.** (F-002)
3. **Sample size masquerading as edge.** A ~24-trade sample read +0.159R
   expectancy; the same configuration over ~36 trades read −0.367R. Nothing
   under ~150 trades should be quoted at all.
4. **Selection over configurations.** The reference chart carried four
   instances of the same script with different parameter sets. Reporting the
   best of N without correcting for N is the most common way a backtest lies.
5. **Score-0 rows polluting a decile study.** 80% of exported rows carry
   `score = 0` because a hard gate vetoed before scoring. Including them made
   the confluence score look predictive when the deciles were mostly noise.
   Restrict any score study to actually-scored setups.
