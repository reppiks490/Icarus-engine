# FR-1 — Win-rate frontier: pre-registration

Package `R01-C2` (Claude; reviewer Codex).

- **Revision 2, registered 2026-10-11.** It applies Codex's review (PR #137, comment 6110009014).
- No FR-1 statistic has been computed, under either revision.
- Nothing here may change after its data is seen. Any later change is a new registration with a new ID
  and counts as new trials.

## 1. Question

The owner's targets (`ICARUS_STATE.md` §1) are setups with a win rate of at least 82 %, positive
expectancy after costs, and an average hold of about 2 hours or less on 5-minute charts. A small target
with a wide stop gives a high win rate mechanically, so a high win rate alone proves nothing. FR-1 asks:

> For each pre-declared entry rule, is there a fixed take-profit, stop and time-stop geometry that meets
> the targets on TUNE **and** beats random entries traded the same way? Does the single geometry
> selected on TUNE hold on HOLD? And does it then earn the targets on FORWARD?

## 2. Data, windows and causal preprocessing

**Data:**

- **Instrument:** MNQ, 5-minute RTH bars, 78 slots a day.
- **Tape:** `data/mnq_5m_full.csv`, extended through Databento via `cl_lab.run.load_asset`.
- **Roll switches:**
  - `instrument_id` changes where the tape carries it (`cl-data-3`);
  - the NASDAQ-100 basis jump elsewhere (`cl-data-2`).

  Each switch is identified from data available at that switch.

**As-of adjustment.** The full-tape back-adjustment would apply a roll's price delta to prices from
before it. The noise band and the ATR are not invariant to that shift, because they use ratios and the
previous close. So FR-1 never uses the full-tape back-adjustment. For each trading day *d*:

- every earlier session in the history window is shifted by the sum of the roll deltas of the switches
  that fall after that session and on or before *d*. This puts it in day *d*'s contract prices;
- day *d*'s own bars are **raw** (shift 0). Every entry, target, stop and fill uses real contract prices,
  on the 0.25-point grid;
- the noise band, `prev_close` and `atr14` for day *d* are computed from that as-of view;
- no switch after *d* can change anything about day *d*.

**`atr14`** is the mean true range of the 14 sessions before *d* in the as-of view; on the first session,
the high minus the low. This is `cl_lab.sessions` applied to the as-of view.

**Windows:**

- TUNE: before 2025-10-01.
- HOLD: 2025-10-01 to 2026-10-04.
- FORWARD: from 2026-10-12, the day after registration.
- Sessions from 2026-10-05 to 2026-10-11 are in no window: after HOLD, before registration.

**Prior exposure, stated honestly:**

- HOLD is **not untouched**. CL R2, R3 and R5 and cl-boos1 already computed statistics on it, so a pass on
  HOLD here is weaker evidence than a first look would be.
- The two entry rules were chosen from NQ 2013–2024 data, which overlaps TUNE but not HOLD.
- Only FORWARD evidence can qualify a setup (§7).

## 3. Entry sources and entry extraction (complete family)

Two sources from `automation_intelligence/cl_lab/boos_latest.json`, family `cl-g1`, `NoiseBoundary`
(`cl_lab/grammar.py`):

| Source | id | Registered parameters |
|---|---|---|
| S1 | `005e61b86b3d` | check 30, lookback 10, mult 1.0, trail band_vwap, regime all |
| S2 | `c00aeb927f0b` | check 30, lookback 14, mult 1.0, trail band_vwap, regime all |

`trail` identifies the registered rule. FR-1 does not use it, because the bracket in §4 replaces the
exit.

**Raw signal.** On day *d*, at each check bar *j* (bar indices 5–76 where `((j+1)·5) mod 30 == 0`), the
signal is:

- **+1** when the close `C[d,j]` is above `max(open[d,0], prev_close[d]) · (1 + mult·σ[d,j])`;
- **−1** when the close is below `min(open[d,0], prev_close[d]) · (1 − mult·σ[d,j])`;
- **0** otherwise.

σ is the mean of `|C/O₀ − 1|` at that time of day over the previous `lookback` complete sessions, in the
as-of view. This is exactly the band in `NoiseBoundary.trades`. FR-1 uses the signal, not that
function's trade list, because the trade list depends on the original trailing exit.

**Entries and occupancy:**

- **One position at a time.** When FR-1 holds no position at check *j* and the signal is ±1, it enters
  in that direction at the open of bar *j+1*.
- While a position is open, every signal is ignored, including an opposite one. There are no reversals
  and no stacking.
- After an exit in bar *k*, the next eligible check is the first *j > k*. Re-entry in either direction
  is then allowed whenever the signal is ±1, with no daily cap. The occupancy rule alone bounds the count.
- An entry can be no later than bar 77, and everything is flat at bar 77's close.

## 4. Exit grid (complete family)

- Take-profit TP ∈ {0.01, 0.02, 0.035, 0.05, 0.08} × atr14.
- Stop SL ∈ {0.05, 0.10, 0.20, 0.35} × atr14.
- Time stop T ∈ {60, 120, 240} minutes.

That is 60 geometries per source and **120 configurations** in all.

**Tick rounding.** Distances are rounded **up** to whole 0.25-point ticks, with a minimum of 1 tick:

- `tp_ticks = max(1, ceil(TP·atr14 / 0.25))`;
- `sl_ticks = max(1, ceil(SL·atr14 / 0.25))`.

The target is entry ± `tp_ticks`·0.25 and the stop is entry ∓ `sl_ticks`·0.25. The same rule applies to
real and null trades.

## 5. Fills, hold time and costs (conservative, real prices only)

**Fills:**

- **Entry:** the open of the bar after the signal bar.
- **Take-profit:** fills only if the bar trades **through** the target by at least one tick (a long
  needs the high ≥ target + 0.25). The fill is at the target price, even when the bar opens beyond it.
  A touch is not a fill.
- **Stop:** fills at the stop price, or at the bar's open when the bar opens through it.
- **Both in one bar:** a bar that reaches both counts as the stop.
- **Time stop:** at the open of bar *e + T/5*, where *e* is the entry bar.
- **End of day:** at bar 77's close.

The current `cl_lab/backtest.py` fills on touch, so FR-1 uses its own fill function, tested in §9.

**Hold time:**

| Exit | Hold |
|---|---|
| Inside bar *k* (target or stop) | 5·(k − e + 1) minutes |
| Time stop at the open of bar *k* | 5·(k − e) minutes |
| End of day | 5·(78 − e) minutes |

**Costs:**

- Base: $2.70 per MNQ round turn (5.4 ticks). Stress: $5.40 (`cl_lab/costs.py` `MNQ`, `MNQ_STRESS`).
- A **win** is a trade whose net P&L at base cost is above zero.

## 6. Statistics and the null

**Per configuration and window:**

- number of trades;
- win rate, with its Wilson lower bound (95 % two-sided, z = 1.96);
- net expectancy in points and dollars at base and stress cost;
- mean and median hold;
- longest winning and losing streaks;
- Newey–West t of **daily** net P&L.

The daily series covers every RTH session in the window, with zero on days without trades. The lag is
`floor(4·(T/100)^(2/9))` for T sessions, and t is tested one-sided.

**Matched random-entry null:**

- 200 independent null sets. Each replays all of the configuration's real trades in time order.
- For each real trade entering on day *d* in RTH hour bucket *h*:
  - buckets are slots 0–11, 12–23, …, 72–77;
  - the null draws an entry bar uniformly from that day's bucket-*h* bars at which **its own set** holds
    no open position (one position at a time, as in §3);
  - the direction is uniform ±1;
  - the geometry, tick rounding, fills and costs are the same.
- If no bar is free, that null trade is skipped, and the number skipped is reported.
- Draws are without replacement within a set's day and independent across sets. The seed is the SHA-256
  of `fr-1`, the source id, the geometry and the set index.
- **Null p-value** = (b + 1) / (200 + 1), where b counts null sets whose net expectancy is **≥** the real
  one (ties count against the rule). The gate p ≤ 0.05 therefore needs b ≤ 9. The plain fraction b/200 is
  reported as description only.

## 7. Decision rules

**TUNE selection, per source.** A configuration is eligible if all of these hold:

- win rate ≥ 0.82;
- net expectancy > 0 at base cost;
- mean hold ≤ 120 min;
- at least 100 trades;
- null p ≤ 0.05.

Among eligible configurations, the one with the highest NW t is selected. Ties go to the smaller stop,
then the smaller target, then the shorter time stop. With none eligible, the source ends as `NO_REGION`.
Hold time is a declared constraint (the owner's target), never a ranking key (`ICARUS_STATE.md` §4,
rule 5).

**HOLD test, the selected configuration only, frozen.** Pass needs all of:

- at least 30 trades;
- one-sided NW t whose Holm-adjusted p ≤ 0.05 across the sources that reached HOLD;
- win rate ≥ 0.80, with a Wilson lower bound ≥ 0.72;
- null p ≤ 0.05;
- net expectancy > 0 at stress cost.

A pass is `HOLD_CONFIRMED`: forward watch only (R01-P1). A failure is `REJECTED`. HOLD is never used to
choose another configuration or to change a threshold.

**FORWARD qualification:** the only route to a champion.

- **One evaluation.** A `HOLD_CONFIRMED` configuration is evaluated once, at the first session close
  where its forward trade count reaches 220. That is the sample that separates 82 % from 75 %
  (`ICARUS_STATE.md` §1). Interim forward numbers may be displayed, but they are not tests and decide
  nothing.
- **Multiplicity:** Bonferroni across the k `HOLD_CONFIRMED` configurations (k ≤ 2), so α = 0.05/k,
  one-sided.
- **`TARGET_QUALIFIED`** needs all of:
  - **observed** forward win rate ≥ 0.82;
  - a one-sided Wilson lower bound (at α) above 0.75;
  - mean hold ≤ 120 min;
  - net expectancy > 0 at stress cost;
  - forward NW t significant at α.
- **`FORWARD_PASS_BELOW_TARGET`:** every statistical gate passes but the observed win rate or the mean
  hold misses the target. This is reported as such and is never called target-qualified.
- Anything less is `FORWARD_REJECTED`.

Nothing in FR-1 grants execution authority.

## 8. Trials, the global ledger and multiple testing

**Before any FR-1 statistic, the global trial ledger is initialized.**
`automation_intelligence/research/trial_ledger.jsonl` gets one record per historical trial, imported
idempotently:

- every CL-lab rule evaluation in `automation_intelligence/cl_lab/latest.json` and its run history;
- every row of `automation_intelligence/cl_lab/explore_ledger.jsonl` (2,232 rows on 2026-10-11);
- every cl-boos1 candidate in `boos_latest.json`;
- each Pulse variant in `pulse_latest.json`;
- each pre-registered D1 test that has run.

**Trial identities:**

- Each record carries a stable `trial_id`: the source name plus the source's own id, or the SHA-256 of
  the canonical source row where there is no id. It also carries the source path and the row's hash.
- Importing twice adds nothing.
- An FR-1 trial's id is the SHA-256 of (`fr-1`, the source id, the geometry and the data version).
  Re-evaluating an unchanged registration on unchanged inputs adds no trials. A new data version adds
  new trials.

**Frozen snapshot:** total, count per source, and the ledger's SHA-256. It is written into the FR-1
results **before** evaluation, and the deflated Sharpe of every selected configuration uses it.

**Blocked if:**

- any import source cannot be read;
- the imported counts fall below the totals recorded in `ICARUS_STATE.md` §2 (492 rules, 2,160 explorer
  attempts).

In either case FR-1 is `BLOCKED` and computes nothing.

**Trial count:** 120 TUNE configurations plus up to 2 HOLD tests, plus at most 2 forward evaluations.
Results, including `NO_REGION`, `REJECTED` and `BLOCKED`, go in `docs/RESEARCH_LOG.md` with TUNE and HOLD
side by side.

## 9. Leakage checklist and required tests (before any real run)

`tests_cl/test_frontier.py` must show all of these.

1. **Causality from raw input:**
   - Truncate the **raw** tape after day *d* and run the whole pipeline from the loader (switches, as-of
     view, signals, fills). Every result up to day *d* is identical.
   - A synthetic roll inserted after day *d* changes nothing about day *d*.
   - Signals use closed bars only.
2. **Fills:**
   - a touch without trade-through is not a target fill;
   - a stop gapped through fills at the open;
   - a favourable gap fills the target at the target price;
   - a bar that reaches both is the stop;
   - target and stop prices are on the 0.25 grid, rounded up;
   - the time stop, end of day and hold minutes follow §5.
3. **Occupancy:**
   - no overlapping positions;
   - opposite signals are ignored while a position is open;
   - re-entry starts at the first check after the exit bar;
   - the null obeys the same occupancy rule.
4. **Planted edge detected:** on a synthetic tape with an injected drift after the signal, selection finds
   an eligible configuration and the null p is small.
5. **No edge, no confirmation:** with random entries as the "source", HOLD confirmation fails.
6. **The null p-value** is (b+1)/(N+1), with ties counted against the rule, and is never 0.
7. **Ledger:**
   - importing twice adds nothing;
   - a re-run of unchanged inputs adds no FR-1 trials;
   - an unreadable source makes the run `BLOCKED`.
8. **Determinism:** the same inputs give the same null draws and results.

## 10. Delivery

- **Code and tests:** `cl_lab/frontier.py`, `cl_lab/trial_ledger.py`, `tests_cl/test_frontier.py`.
- **Results:** `automation_intelligence/cl_lab/frontier_latest.json` (aggregates only, no vendor rows)
  and `automation_intelligence/research/trial_ledger.jsonl`.
- **Run:** on GitHub Actions in the CL lane.
- **Review:** this document merges after Codex's review. The code merges after a second review that covers
  leakage, the null, costs, fills and the ledger.
