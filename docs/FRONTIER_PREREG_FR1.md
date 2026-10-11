# FR-1 — Win-rate frontier: pre-registration

Package `R01-C2` (Claude; reviewer Codex). Registered 2026-10-11, before any frontier statistic was
computed. Nothing in this document may change after its data is seen; any change is a new registration
with a new ID and counts as new trials.

## 1. Question

The owner's targets (`ICARUS_STATE.md` §1) are setups with win rate ≥ 82 %, positive expectancy after
costs, and an average hold of about 2 h or less on 5-minute charts. A high win rate is mechanically easy
with a small take-profit and a wide stop, so a high win rate alone proves nothing. FR-1 asks:

> For each pre-declared entry rule, is there a fixed take-profit / stop / time-stop geometry that meets
> the targets on TUNE **and** beats random entries traded with the same geometry; and does the single
> selected geometry hold on HOLD?

## 2. Data and windows

- **Instrument and tape:** MNQ, 5-minute RTH bars, 78 slots a day. The tape is `data/mnq_5m_full.csv`
  extended through Databento via `cl_lab.run.load_asset`, back-adjusted at rolls (`cl-data-2`,
  `cl-data-3`).
- **ATR:** `atr14` is the daily ATR of the 14 sessions before the trading day, known at the open.
- **Windows:**
  - TUNE: before 2025-10-01.
  - HOLD: 2025-10-01 to 2026-10-04.
  - FORWARD: from 2026-10-12, the day after registration.
  - Sessions from 2026-10-05 to 2026-10-11 are in no window: they came after HOLD but before
    registration, so they are neither held out nor forward.
- **Prior exposure, stated honestly:**
  - HOLD is **not untouched**. CL R2, R3 and R5 families and the cl-boos1 runs already computed
    statistics on it, so a pass on HOLD here is weaker evidence than a first look would be.
  - The two entry rules were chosen from NQ 2013–2024 data, which overlaps TUNE but not HOLD.
  - Only FORWARD evidence qualifies a setup (§7).

## 3. Entry sources (complete family)

Two sources, from `automation_intelligence/cl_lab/boos_latest.json`, family `cl-g1` (`NoiseBoundary`):

| Source | id | Parameters |
|---|---|---|
| S1 | `005e61b86b3d` | check 30, lookback 10, mult 1.0, regime all |
| S2 | `c00aeb927f0b` | check 30, lookback 14, mult 1.0, regime all |

- **Entries and direction:** taken exactly as the family generates them, at the next bar's open after
  the signal bar closes. Each family's own trailing exit is replaced by the bracket in §4.
- **Excluded on purpose:**
  - liquidity-sweep entries: the sweep premise is dead (F-004, 16 markets);
  - THE PULSE OF ICARUS entries: no edge on real fills.

## 4. Exit grid (complete family)

- Take-profit TP ∈ {0.01, 0.02, 0.035, 0.05, 0.08} × atr14.
- Stop SL ∈ {0.05, 0.10, 0.20, 0.35} × atr14.
- Time stop ∈ {60, 120, 240} minutes.
- Every position is flat by the last RTH bar.

That is 60 geometries per source and **120 configurations** in all.

## 5. Fills and costs (conservative, real prices only)

- **Entry:** the open of the bar after the signal.
- **Take-profit:** fills only if the bar trades **through** the target by at least one tick (0.25 point),
  and then at the target price. A touch is not a fill. The current `cl_lab/backtest.py` fills on touch,
  so FR-1 uses its own fill function, tested in §9.
- **Stop:** fills at the stop price, or at the open if the bar gaps through it.
- **Both hit in one bar:** a bar that reaches both counts as the stop.
- **Time stop:** the open of the first bar after the limit.
- **End of day:** the last RTH bar's close.
- **Costs:** base $2.70 per MNQ round turn (5.4 ticks); stress is double that (`cl_lab/costs.py`
  `MNQ`, `MNQ_STRESS`). Prices are never Heikin-Ashi.

## 6. Statistics

**Per configuration and window:**

- number of trades;
- win rate and its Wilson 95 % lower bound;
- net expectancy in points and dollars at base and stress cost;
- Newey–West t of daily net P&L;
- mean and median hold in minutes;
- longest winning and losing streaks.

**Matched random-entry null:**

- Each real trade is paired with a random entry on the same day, in the same RTH hour, with random
  direction, using the same geometry and fills.
- Draw 200 such sets with a fixed seed: the SHA-256 of `fr-1`, the source id and the geometry.
- Report the excess win rate (real minus null mean) and the null p-value of net expectancy (the share
  of null sets with expectancy ≥ the real one).

## 7. Decision rules

**TUNE selection, per source:**

- A configuration is eligible if all of these hold:
  - win rate ≥ 0.82;
  - net expectancy > 0 at base cost;
  - mean hold ≤ 120 min;
  - at least 100 trades;
  - null p ≤ 0.05.
- Among eligible configurations, select the one with the highest NW t. Break ties by the smaller stop,
  then the smaller take-profit, then the shorter time stop.
- No eligible configuration: the source ends as `NO_REGION`.

Hold time is a pre-declared constraint, the owner's target, not a ranking key. Ranking uses NW t only
(rule 5 of `ICARUS_STATE.md` §4).

**HOLD test, the selected configuration only, frozen.** Pass needs all of:

- at least 30 trades;
- one-sided NW t ≥ 1.65, with Holm adjustment across the sources that reached HOLD (one-sided
  p ≤ 0.05 after adjustment);
- win rate ≥ 0.80, with a Wilson lower bound ≥ 0.72;
- null p ≤ 0.05;
- net expectancy > 0 at stress cost.

A pass makes the configuration `HOLD_CONFIRMED`, which means forward watch (R01-P1) only. A failure
makes it `REJECTED`. HOLD is never used to choose another configuration.

**FORWARD qualification:** the only route to a champion.

- At least 220 forward trades. That is the sample needed to tell 82 % from 75 % (`ICARUS_STATE.md` §1).
- The one-sided 95 % lower bound of the win rate is above 0.75.
- Net expectancy > 0 at stress cost.
- Forward NW t ≥ 1.65.

Nothing in FR-1 grants execution authority.

## 8. Trials and multiple testing

- **Trial count:** 120 TUNE configurations plus up to 2 HOLD tests. Every one is appended to
  `automation_intelligence/research/trial_ledger.jsonl`, created by this package, and counts toward
  the global trial count shared by all AIs.
- **Deflated Sharpe:** reported for each selected configuration using the global count at run time.
- **Write-up:** results go in `docs/RESEARCH_LOG.md` with TUNE and HOLD numbers side by side, including
  `NO_REGION` and `REJECTED` outcomes.

## 9. Leakage checklist and required tests (before any real run)

`tests_cl/test_frontier.py` must show all of these:

1. **Causality:**
   - signals use closed bars only;
   - `atr14` uses prior sessions only;
   - truncating the tape after day *d* leaves every result up to day *d* unchanged.
2. **Fill rules:**
   - a touch without trade-through is not a take-profit;
   - a gap through the stop fills at the open;
   - a bar that reaches both counts as the stop;
   - the time stop and end of day fill as in §5.
3. **Planted edge detected:** on a synthetic tape with an injected drift after the signal, the
   selection finds an eligible configuration and the null p is small.
4. **No edge, no confirmation:** with random entries as the "source", HOLD confirmation fails.
5. **Determinism:** the same inputs give the same null draws and results.
6. **Trial ledger:** every configuration is written exactly once per run.

## 10. Delivery

- **Code and tests:** `cl_lab/frontier.py`, `tests_cl/test_frontier.py`.
- **Results:** `automation_intelligence/cl_lab/frontier_latest.json` (aggregates only, no vendor rows)
  and `automation_intelligence/research/trial_ledger.jsonl`.
- **Run:** on GitHub Actions in the CL lane.
- **Review:** this document merges after Codex's review. The code merges after a second review that
  covers leakage, the null, costs and fills.
