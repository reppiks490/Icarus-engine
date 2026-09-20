# Icarus — Top 20 Variants

Produced by `tools/run_sweep.py`: 1400 randomly sampled configurations across
2m/3m/5m/10m/15m/30m, screened on 83 days, confirmed on a 416-day tuning tape,
then validated on a **416-day held-out tape generated from a different seed**
that the variants were never selected on.

Funnel: **1400 → 341 → 195 → 176** positive on held-out data.

Ranked on the **worse** of the two tapes. A variant is only as good as its
weakest tape; ranking on the better one just picks the luckier draw.

## ⚠ What these numbers are and are not

Both tapes come from the same synthetic generator with different seeds. That
176 of 195 stayed positive out of sample (binomial z = 11.2 against a coin-flip
null) proves the variants are **not fitted to one seed**. It does **not** prove
they work on real MNQ — they may all be fitted to this generator's
regime-switching structure. Real validation needs real bars. Nothing here
should size a live position.

## The variants

| # | tf | location | trades/day | hold | win% | **held-out expR** | PF | maxDD% | n |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2m | continuation | 0.73 | 128m | 57.4 | **+1.121R** | 3.72 | 16.32 | 305 |
| 2 | 2m | invert | 0.74 | 128m | 56.0 | **+1.114R** | 3.59 | 23.19 | 309 |
| 3 | 2m | invert | 0.72 | 117m | 64.1 | **+1.023R** | 3.73 | 11.09 | 301 |
| 4 | 2m | invert | 0.42 | 90m | 66.7 | **+0.892R** | 3.70 | 7.65 | 174 |
| 5 | 3m | invert | 0.22 | 112m | 56.0 | **+0.888R** | 3.08 | 3.92 | 91 |
| 6 | 2m | continuation | 0.29 | 102m | 52.5 | **+0.885R** | 2.90 | 6.08 | 122 |
| 7 | 3m | continuation | 0.12 | 154m | 66.7 | **+1.308R** | 5.08 | 1.81 | 48 |
| 8 | 3m | continuation | 0.21 | 107m | 60.9 | **+0.874R** | 3.27 | 7.19 | 87 |
| 9 | 2m | invert | 0.83 | 86m | 52.0 | **+0.873R** | 2.92 | 23.96 | 344 |
| 10 | 2m | continuation | 0.32 | 110m | 59.3 | **+1.187R** | 4.00 | 7.33 | 135 |
| 11 | 2m | invert | 0.09 | 132m | 59.5 | **+1.729R** | 5.57 | 2.88 | 37 |
| 12 | 3m | invert | 0.20 | 133m | 58.5 | **+1.330R** | 4.08 | 4.64 | 82 |
| 13 | 3m | invert | 0.37 | 135m | 58.8 | **+0.837R** | 3.55 | 4.38 | 153 |
| 14 | 2m | continuation | 0.55 | 87m | 56.8 | **+0.811R** | 3.08 | 7.73 | 229 |
| 15 | 2m | invert | 0.35 | 140m | 52.4 | **+0.784R** | 2.98 | 7.29 | 145 |
| 16 | 2m | normal | 0.25 | 70m | 60.0 | **+0.770R** | 2.84 | 5.58 | 105 |
| 17 | 2m | continuation | 0.19 | 114m | 58.0 | **+0.777R** | 3.00 | 5.23 | 81 |
| 18 | 3m | invert | 0.64 | 93m | 48.1 | **+0.764R** | 2.46 | 10.26 | 266 |
| 19 | 2m | continuation | 0.43 | 84m | 58.3 | **+0.763R** | 2.92 | 5.82 | 180 |
| 20 | 2m | continuation | 0.60 | 63m | 59.8 | **+0.812R** | 3.21 | 11.81 | 249 |

## Against your stated criteria

| criterion | asked | found |
|---|---|---|
| trades/day | 0–2 | **0.09–0.83** ✓ |
| holds long intraday trends | yes | **median 111 min (~1.9h)** ✓ |
| win rate ≥80% | ≥80% | **ceiling 79.2%** ✗ |
| loss kept minimal | yes | worst single trade −1.0R across all 20 ✓ |

### On the 80% target

No configuration in 1400 reached 80% held-out. The ceiling was **79.2%**, and
that variant is genuinely good: +0.401R expectancy, PF 3.05, 0.35 trades/day.

The data also shows *why* chasing the number further is a trap:

| held-out win% | expectancy | PF | avg win | avg loss |
|---|---|---|---|---|
| 79.2% | +0.401R | 3.05 | +0.74R | −0.90R |
| 76.9% | **+0.158R** | 1.75 | **+0.49R** | −0.94R |
| 76.3% | +0.580R | 3.42 | +1.05R | −0.93R |

The 76.9% variant wins more often than #3 and earns a quarter as much,
because its wins are half the size while its losses stay full. Win rate is
purchasable with small targets; expectancy is not.

## Where the edge concentrated

| timeframe | survivors | median held-out expR |
|---|---|---|
| 2m | 107 | +0.441 |
| 3m | 58 | +0.385 |
| 5m | 10 | +0.117 |
| 10m | 1 | +0.025 |

Nothing survived at 15m or 30m. The edge sits on **fine bars** — but the
**trades are long**, a median of 1.9 hours on a 10-hour session. Fine bars buy
entry precision; the exit layer supplies the duration.

| location premise | survivors | median held-out expR |
|---|---|---|
| invert | 60 | +0.428 |
| continuation | 86 | +0.412 |
| normal (shipped default) | 30 | +0.247 |

**N-001 confirmed at scale**: 146 of 176 survivors use a corrected location
premise, and the corrected premises carry ~70% more median expectancy than the
one currently shipped. See `docs/RESEARCH_LOG.md`.

Full parameters for each: `docs/variants_top20.json`.
