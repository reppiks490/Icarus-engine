# D1 — Does real order-book data confirm a failed sweep? (pre-registration)

Registered 2026-10-10, before any vaulted NQ MBP-10 day exists. Nothing below has been evaluated. The
specification is frozen; results are appended under **Results** and never edit it. Runner:
`cl_lab/depth_test.py` (`depth-d1`), executed by `depth-vault.yml` after every seal.

## Why

Every price-only conditioner tried for direction has failed (RESEARCH_LOG N-002 to N-005, F-004, F-005; the
CL lab's 492 rules and 2,160 explorer attempts). N-003 confirmed the capture geometry but left direction
open. The one input class never tested is real order flow. ICARUS's premise is that a raid on resting
liquidity **fails**. At the microstructure level, failing means the swept side's liquidity comes back fast
and price reverts. MBP-10 records exactly that.

## Data

- NQ `NQ.v.0` MBP-10, regular session 09:15–16:15 New York, bought by `cl-depth-sweep` and restored from
  `data/depth_vault/`. The 18 days lost to cache eviction on 2026-10-10 are not recoverable and are not
  part of this test.
- Event rows: `cl_lab.depth_resilience` (one row per touch-clearing aggressive order). Minute rows:
  `databento_depth_acquire.summarize_store`.
- All accounts' NQ days are pooled; a day held twice is counted once.

## Hypotheses (2 primary, Holm across them, one-sided α = 0.05)

**D1-A, failed sweep.** Universe: events with `levels_swept >= 2` (a sweep through at least two price
levels). Groups, fixed: FAST = `refill_5s >= 1.0` (swept-side top-5 depth fully back within 5 s), SLOW =
`refill_5s < 0.5`. Outcome: `move_300s` (ticks, signed positive in the aggressor's direction).
Prediction: mean(SLOW) − mean(FAST) > 0. Fast refill means the raid failed, so price reverts; slow refill
means it continues. Statistic: the difference of day-weighted means. Null: 5,000 permutations shuffling
FAST/SLOW labels **within each day**. Each day's mix is preserved, so day-level drift cannot create the
effect (trap 8).

**D1-B, book imbalance.** Universe: every minute with depth. `DI = (depth10_bid_mean − depth10_ask_mean) /
(depth10_bid_mean + depth10_ask_mean)` at minute t. Outcome: the midrange change from minute t+1 to minute
t+15. Midrange is `(price_min + price_max) / 2`. Starting at t+1 keeps the feature minute out of the
outcome. Prediction: the mean daily Spearman IC between DI and the outcome is > 0. Null: 5,000 random
circular shifts of DI within each day.

Secondary, reported but never gating: D1-A with `move_30s` and `move_60s`; D1-B at t+5 and t+30.

## Gates

1. Sample: at least 20 distinct days. D1-A also needs at least 100 events in each group. Below that the
   status is `INSUFFICIENT_DATA`, and nothing is inferred.
2. Holm-adjusted permutation p ≤ 0.05 for the hypothesis.
3. Positive in both chronological halves of the days.
4. Tradeable: for D1-A, the SLOW − FAST spread must exceed 5.4 ticks. That is MNQ's $2.70 round turn at
   $0.50 a tick. An effect smaller than the friction is `SIGNIFICANT_NOT_TRADEABLE`.

Passing 1–4 gives `D1_CONFIRMED`. That never authorizes execution. It admits the feature as a
candidate input to the engine's confluence layer. The candidate must then pass the engine's own
TUNE/HOLD protocol on new days.

## Results

None yet.
