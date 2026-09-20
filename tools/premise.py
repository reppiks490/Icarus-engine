"""Test the premise the whole engine rests on: do liquidity sweeps reverse?

Everything in this repo so far has been parameter search over a fixed
hypothesis -- tune the sweep strategy, measure, repeat. That can only ever find
the best version of the hypothesis it was handed. It cannot tell you the
hypothesis is false, and a permutation null on the finished strategy said
exactly that (p=0.377 held-out): the entry signal is not distinguishable from
random. Tuning a false premise harder does not make it true.

So this tests the foundation directly, with no confluence layer, no ML gate, no
exit policy and no thresholds to fit. A sweep is defined structurally: price
trades beyond a prior reference extreme and then closes back inside within a
few bars. If the premise holds, forward returns after a reclaim should favour
the reversal direction by more than chance.

Three disciplines that earlier work in this repo lacked:

  MATCHED CONTROLS   A sweep is not compared against zero. It is compared
                     against bars at the same time of day and in the same
                     volatility regime that did NOT sweep. Intraday returns
                     have strong time-of-day and regime structure; without
                     matching, a "sweep edge" can be nothing but the fact that
                     sweeps cluster at the open.

  TWO SPANS          Every variant is measured on the tuning span and the
                     held-out span separately, and a sign flip between them is
                     reported as the failure it is.

  MULTIPLE TESTING   The grid below is ~200 variants. At p<0.05, ten of them
                     are expected to look significant with no edge present at
                     all -- which is how every result in this project's history
                     was born. Benjamini-Hochberg controls the false discovery
                     rate across the whole grid, so a survivor means something.
"""

from __future__ import annotations

import math
import statistics as st
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Sweep detection -- structural, not tuned
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Sweep:
    index: int          # bar on which the reclaim completed
    direction: int      # +1 expects up (a low was swept), -1 expects down
    reference: float    # the level that was taken out
    atr: float          # volatility at the time, for control matching
    minute: int         # minutes since ET midnight, for time-of-day matching


class Tape:
    """A tape with its per-bar ATR and ET minute computed once.

    The grid runs a few hundred variants over the same bars; recomputing a
    rolling ATR inside each one turns a minute of work into an hour.
    """

    __slots__ = ("bars", "atr", "minute", "n")

    def __init__(self, bars, window: int = 14) -> None:
        self.bars = bars
        self.n = len(bars)
        trs = [0.0] * self.n
        for i in range(1, self.n):
            b, prev = bars[i], bars[i - 1]
            trs[i] = max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close))
        self.atr = [0.0] * self.n
        running = 0.0
        for i in range(1, self.n):
            running += trs[i]
            if i > window:
                running -= trs[i - window]
            self.atr[i] = running / min(i, window)
        self.minute = [_et_minute(b) for b in bars]


def _atr(bars, i: int, window: int = 14) -> float:
    lo = max(1, i - window + 1)
    trs = [max(b.high - b.low,
               abs(b.high - p.close),
               abs(b.low - p.close))
           for p, b in zip(bars[lo - 1:i], bars[lo:i + 1])]
    return st.fmean(trs) if trs else 0.0


def find_sweeps(tape, *, lookback: int, reclaim_bars: int,
                min_penetration_atr: float = 0.0) -> list[Sweep]:
    """Penetration of an N-bar extreme, followed by a close back inside.

    Deliberately the plainest reading of the idea. No confluence, no order-flow
    confirmation, no score threshold -- if the premise is real it has to be
    visible in the raw structure before any of that is layered on.
    """
    bars = tape.bars
    out: list[Sweep] = []
    for i in range(lookback + 1, len(bars) - 1):
        window = bars[i - lookback:i]
        prior_high = max(b.high for b in window)
        prior_low = min(b.low for b in window)
        atr = tape.atr[i]
        if atr <= 0:
            continue

        for direction, level, took_out, reclaimed in (
            (+1, prior_low, bars[i].low < prior_low, lambda b: b.close > prior_low),
            (-1, prior_high, bars[i].high > prior_high, lambda b: b.close < prior_high),
        ):
            if not took_out:
                continue
            penetration = abs(bars[i].low - level if direction > 0 else bars[i].high - level)
            if penetration < min_penetration_atr * atr:
                continue
            # The reclaim must happen soon, or it is not a sweep -- it is a break.
            for k in range(0, reclaim_bars + 1):
                j = i + k
                if j >= len(bars) - 1:
                    break
                if reclaimed(bars[j]):
                    out.append(Sweep(j, direction, level, atr, tape.minute[j]))
                    break
    return out


def _et_minute(bar) -> int:
    from datetime import date, timedelta
    utc = bar.ts
    dst = any(lo <= utc.date() <= hi for lo, hi in (
        (date(2024, 3, 10), date(2024, 11, 2)),
        (date(2025, 3, 9), date(2025, 11, 1)),
        (date(2026, 3, 8), date(2026, 10, 31)),
    ))
    et = utc - timedelta(hours=4 if dst else 5)
    return et.hour * 60 + et.minute


# ---------------------------------------------------------------------------
# Outcome measurement
# ---------------------------------------------------------------------------

def forward_return(tape, i: int, horizon: int, direction: int) -> float | None:
    """Signed forward move in ATR units, so regimes are comparable."""
    j = i + horizon
    if j >= tape.n:
        return None
    atr = tape.atr[i]
    if atr <= 0:
        return None
    return direction * (tape.bars[j].close - tape.bars[i].close) / atr


def stratified_effect(tape, sweeps: list[Sweep], horizon: int,
                      *, minute_bucket: int = 30, atr_deciles: int = 5):
    """Effect estimated WITHIN strata, then pooled by sweep weight.

    Matching each control bar to a stratum is not enough. Comparing a pooled
    sweep mean against a pooled control mean still compares different mixtures
    whenever the strata hold different proportions of the two groups: if most
    sweeps land in the opening half hour and most control bars land at midday,
    the pooled difference is mostly the difference between morning and midday.

    Two earlier versions of this function missed that. Both reported IWM at
    +1.39 ATR and SPY at -1.51 ATR over windows where one instrument rose and
    the other fell -- equal and opposite, in the same asset class, which is the
    signature of measuring drift rather than structure. An expected move of
    1.4 ATR would also be the most profitable signal in finance.

    So the effect is computed inside each stratum, where conditions genuinely
    are alike, then averaged across strata weighted by how many SWEEPS each
    contributed. Values are returned re-centred on their stratum's control
    mean, so a t-test over the pooled lists tests the stratified quantity
    rather than the raw mixture.
    """
    if not sweeps:
        return 0.0, [], []
    swept = {s.index for s in sweeps}

    live = [tape.atr[i] for i in range(20, tape.n - horizon) if tape.atr[i] > 0]
    if not live:
        return 0.0, [], []
    live.sort()
    edges = [live[min(int(k * len(live) / atr_deciles), len(live) - 1)]
             for k in range(1, atr_deciles)]

    def vol_bucket(atr: float) -> int:
        for k, edge in enumerate(edges):
            if atr <= edge:
                return k
        return atr_deciles - 1

    def key_of(minute: int, atr: float):
        return (minute // minute_bucket, vol_bucket(atr))

    treated: dict[tuple[int, int], list[float]] = {}
    lean: dict[tuple[int, int], list[int]] = {}
    for s in sweeps:
        value = forward_return(tape, s.index, horizon, s.direction)
        if value is None:
            continue
        key = key_of(s.minute, s.atr)
        treated.setdefault(key, []).append(value)
        counts = lean.setdefault(key, [0, 0])
        counts[0 if s.direction > 0 else 1] += 1

    controls: dict[tuple[int, int], list[float]] = {}
    for i in range(20, tape.n - horizon):
        if i in swept or tape.atr[i] <= 0:
            continue
        key = key_of(tape.minute[i], tape.atr[i])
        counts = lean.get(key)
        if not counts:
            continue
        longs, shorts = counts
        total = longs + shorts
        forward = forward_return(tape, i, horizon, +1)
        if forward is not None and total:
            # A short's forward return is the negative of a long's, so the
            # mix-weighted control is the long return scaled by this stratum's
            # net directional lean.
            controls.setdefault(key, []).append(forward * (longs - shorts) / total)

    effect = 0.0
    weight = 0
    treated_c: list[float] = []
    control_c: list[float] = []
    for key, values in treated.items():
        matched = controls.get(key)
        if not matched or len(matched) < 5:
            continue
        control_mean = sum(matched) / len(matched)
        effect += (sum(values) / len(values) - control_mean) * len(values)
        weight += len(values)
        treated_c.extend(v - control_mean for v in values)
        control_c.extend(v - control_mean for v in matched)

    if not weight:
        return 0.0, [], []
    return effect / weight, treated_c, control_c


def welch_t(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's t and a normal-approximation two-sided p. Unequal variances."""
    if len(a) < 8 or len(b) < 8:
        return 0.0, 1.0
    ma, mb = st.fmean(a), st.fmean(b)
    va, vb = st.pvariance(a), st.pvariance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se <= 0:
        return 0.0, 1.0
    t = (ma - mb) / se
    p = 2.0 * (1.0 - _norm_cdf(abs(t)))
    return t, p


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """Control the false discovery rate across the whole grid.

    Testing ~200 variants at p<0.05 yields ~10 apparent discoveries when
    nothing is there. Every "edge" in this project's history was born that way,
    so the correction is not optional.
    """
    n = len(pvalues)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvalues[i])
    keep = [False] * n
    largest = -1
    for rank, idx in enumerate(order, start=1):
        if pvalues[idx] <= alpha * rank / n:
            largest = rank
    for rank, idx in enumerate(order, start=1):
        if rank <= largest:
            keep[idx] = True
    return keep
