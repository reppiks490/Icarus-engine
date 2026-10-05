# CL pre-registration R5: backward out-of-sample test on 14 years of NQ

CL (Claude, Anthropic). Registered 2026-10-04, **before any of this data has been downloaded**. The data comes from the CL lane on the 4th Databento key (`cl_lab/feeds/databento_history.py`). Every rule, threshold and window below is fixed now. A change gets a new version id and counts as new trials.

## Data
- Continuous `NQ.v.0` and `ES.v.0` 1-minute OHLCV, resampled to 5 minutes, covering 2010-06-07 to 2024-09-01. No CL rule has ever been evaluated on this span. Every CL family so far ran on MNQ from 2024-09-20 onward, or on crypto.
- Roll handling follows cl-data-2 (`cl_lab/integrity.py`): the NQ − FRED NASDAQ-100 basis detects each switch, followed by a Panama back-adjustment, with `instrument_id` changes as a cross-check. ES uses its `instrument_id` switches and bar jumps, because no free daily S&P 500 index series covers the whole span.
- Costs use `costs.NQ` and its stress version. The metric is points.

## Families (ids unchanged)
- **cl-g1:** 492 rules.
- **cl-r1:** 3 rules.
- **cl-r2 R2-A:** 4 end-of-day reversal rules.
- **cl-ml1:** 3 NQ decision times. VIX and VIX9D come from the cached Cboe series, and sessions without VIX9D (before 2011) are unavailable rows.
- **Excluded:**
  - R2-C, because the verified FOMC calendar covers only 2024–2026.
  - R2-D, because it uses crypto taker flow.
  - The explorer, because its sample is random per day and not a fixed family.

## Protocol `cl-boos1`
For each family, on the full 2010-06 → 2024-08 window:
1. Compute the one-sided Newey–West p of daily net P&L at base cost. Apply Benjamini–Yekutieli at q = 0.05 within the family. BY is valid under any dependence.
2. Require DSR ≥ 0.95, with N = the Li–Ji effective number of trials in the family and the Sharpe variance measured across the family.
3. Stability: NW t > 0 in both halves (2010-06 → 2017-07 and 2017-07 → 2024-08), and a positive mean at stress cost.
4. Passing all three gives **`BOOS_CONFIRMED`**. Otherwise the result is `BOOS_REJECTED`.
5. `BOOS_CONFIRMED` never creates a champion on its own. A rule that also failed on the 2024–2026 tape is labelled regime-dependent and moves to forward watch: at least 60 FORWARD trades with NW t ≥ 1.65. A rule that passes both samples is the strongest evidence this lab can produce, and it still needs forward confirmation.

## Reporting
- Every family's full table goes in the run output, rejections included.
- Results are appended to this file after the run. The specification above is never edited.

## R6 megacap-breadth conditioners (registered 2026-10-04, before the data exists)
Breadth comes from the external data fabric's cached Tiingo daily closes (read-only; no API calls). On each date it is the fraction of NVDA, AAPL, MSFT, AVGO, AMZN, META, GOOGL and TSLA that closed up, using only names with a price on both days and requiring at least 5 of them. A session uses the last value dated strictly before it.

The family is `cl-r6`, 4 trials:
- The base rule is either cl-r1 unconditional end-of-day momentum or its mirror, R2-A A1 reversal.
- The filter is either previous-day breadth ≥ 0.75 (`high`) or ≤ 0.25 (`low`).

Evaluation uses only `cl-boos1` on NQ 2010-06 → 2024-09, its own family with its own BY and DSR. It is not evaluated on the 2024–2026 MNQ tape, where the unconditional reversal's HOLD was already seen.

Earnings-event conditioners are deferred. The fabric's FMP earnings calendar holds only upcoming dates, so historical megacap earnings dates need a separate, budgeted FMP pull before any such hypothesis can be tested.
