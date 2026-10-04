# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.stats: validation statistics for the CL lab
"""Validation statistics for the CL lab.

Selection-bias-aware Sharpe statistics (PSR, DSR, MinBTL), the Probability of
Backtest Overfitting via CSCV, multiple-testing corrections (BH, BY, Holm),
stationary-bootstrap inference, data-snooping tests (White's Reality Check,
Hansen's SPA, Romano-Wolf stepdown) and effective-number-of-trials estimators.

Conventions
-----------
* numpy arrays in; plain Python floats/ints, dicts or small named tuples out.
* 1-D series functions drop NaN observations. Matrix functions (rows = time,
  columns = strategies / trials) require all-finite input (``ValueError``).
* Sharpe ratios are per period (mean / std, ddof=1) unless annualized.
* Randomized functions take ``rng``: an ``np.random.Generator``, an int seed or
  ``None`` (fresh OS entropy, NumPy convention). A seed reproduces the result.
* Bootstrap p-values are plain Monte Carlo fractions (resolution 1/n_boot), as
  in White (2000) and Hansen (2005); 0.0 means "below 1/n_boot".
"""
from __future__ import annotations

import itertools
import math
from typing import Callable, NamedTuple, Optional

import numpy as np
from scipy import stats
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform

__all__ = [
    "EULER_GAMMA",
    "MultipleTestResult",
    "ClusterResult",
    "sharpe",
    "psr",
    "expected_max_sharpe",
    "dsr",
    "min_backtest_length",
    "pbo_cscv",
    "bh_fdr",
    "by_fdr",
    "holm",
    "stationary_bootstrap_indices",
    "optimal_block_length",
    "bootstrap_mean_ci",
    "ttest_mean",
    "newey_west_t",
    "whites_reality_check",
    "hansen_spa",
    "romano_wolf_stepdown",
    "effective_number_of_trials",
    "cluster_trials",
    "sharpe_variance_across_trials",
]

EULER_GAMMA = 0.5772156649  # Euler-Mascheroni constant, as used by Bailey & Lopez de Prado

_REL_TOL = 1e-12  # dispersion below this fraction of max|x| counts as "zero std"
_MAX_ELEMS = 4_000_000  # memory guard for chunked bootstrap / FFT work
_PBO_CHUNK = 32_768  # CSCV combinations evaluated per vectorized batch


class MultipleTestResult(NamedTuple):
    """Result of a multiple-testing correction; unpacks as ``reject, p_adjusted``."""

    reject: np.ndarray
    p_adjusted: np.ndarray


class ClusterResult(NamedTuple):
    """Result of :func:`cluster_trials`; unpacks as ``n_clusters, labels``."""

    n_clusters: int
    labels: np.ndarray


# --------------------------------------------------------------------------- helpers


def _as_1d(x, name: str = "x") -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim > 1:
        if sum(s > 1 for s in a.shape) > 1:
            raise ValueError(f"{name} must be 1-D, got shape {a.shape}")
        a = a.ravel()
    a = np.atleast_1d(a)
    return a[~np.isnan(a)]


def _as_2d(m, name: str = "M") -> np.ndarray:
    a = np.asarray(m, dtype=float)
    if a.ndim == 1:
        a = a[:, None]
    if a.ndim != 2 or a.size == 0:
        raise ValueError(f"{name} must be a non-empty 2-D array (rows = time), got shape {a.shape}")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must be finite (no NaN/inf)")
    return a


def _rng(rng) -> np.random.Generator:
    if isinstance(rng, np.random.Generator):
        return rng
    return np.random.default_rng(rng)


def _pos_int(v, name: str) -> int:
    iv = int(v)
    if iv != v or iv < 1:
        raise ValueError(f"{name} must be a positive integer, got {v!r}")
    return iv


def _block_arg(mean_block, name: str = "mean_block") -> float:
    mb = float(mean_block)
    if not (np.isfinite(mb) and mb >= 1.0):
        raise ValueError(f"{name} must be a finite number >= 1, got {mean_block!r}")
    return mb


def _zero_dispersion(sd, scale) -> np.ndarray:
    """True where a standard deviation is zero up to floating-point noise."""
    sd = np.asarray(sd, dtype=float)
    return ~(sd > _REL_TOL * np.asarray(scale, dtype=float))


def _std_moments(a: np.ndarray):
    """Sample (biased, plug-in) skewness and NON-excess kurtosis."""
    e = a - a.mean()
    m2 = float(np.mean(e * e))
    if not m2 > 0:
        return math.nan, math.nan
    return float(np.mean(e**3) / m2**1.5), float(np.mean(e**4) / m2**2)


def _psr_value(sr, n, skew, kurt, sr_benchmark) -> float:
    if n < 2 or not all(np.isfinite(v) for v in (sr, skew, kurt, sr_benchmark)):
        return math.nan
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if not (np.isfinite(denom) and denom > 0):
        return math.nan
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom)
    return float(stats.norm.cdf(z))


def _emax_z(n_trials) -> float:
    """(1-g) Phi^-1(1-1/N) + g Phi^-1(1-1/(N e)), floored at 0 (its N=1 value)."""
    n = float(n_trials)
    if not (np.isfinite(n) and n >= 1.0):
        raise ValueError(f"n_trials must be a finite number >= 1, got {n_trials!r}")
    if n == 1.0:
        return 0.0
    z = (1.0 - EULER_GAMMA) * stats.norm.isf(1.0 / n) + EULER_GAMMA * stats.norm.isf(1.0 / (n * math.e))
    # The asymptotic approximation turns negative for 1 < N < ~1.28 (possible for a
    # fractional effective N); the expected maximum of N >= 1 draws is never below
    # the N=1 value, so floor at 0.
    return max(0.0, float(z))


# --------------------------------------------------------------------------- Sharpe family


def sharpe(x, periods_per_year=None) -> float:
    """Per-period Sharpe ratio mean/std (ddof=1); times sqrt(periods_per_year) if given.

    Sharpe (1966, J. Business; 1994, J. Portfolio Mgmt). Square-root-of-time
    annualization assumes i.i.d. returns (Lo, 2002, Financial Analysts J.).
    Returns nan for fewer than 2 observations or zero standard deviation.
    """
    a = _as_1d(x)
    if a.size < 2:
        return math.nan
    sd = float(a.std(ddof=1))
    if _zero_dispersion(sd, np.max(np.abs(a))):
        return math.nan
    sr = float(a.mean()) / sd
    if periods_per_year is not None:
        ppy = float(periods_per_year)
        if not (np.isfinite(ppy) and ppy > 0):
            raise ValueError(f"periods_per_year must be > 0, got {periods_per_year!r}")
        sr *= math.sqrt(ppy)
    return float(sr)


def psr(x, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio, Bailey & Lopez de Prado (2012, J. of Risk 15(2)).

    PSR = Phi((SR - SR*) sqrt(n-1) / sqrt(1 - g3 SR + (g4 - 1)/4 SR^2)) with the
    per-period SR (ddof=1), plug-in sample skewness g3 and NON-excess kurtosis g4
    (normal = 3). ``sr_benchmark`` is per period too. nan when SR is undefined.
    """
    a = _as_1d(x)
    sr = sharpe(a)
    if not np.isfinite(sr):
        return math.nan
    skew, kurt = _std_moments(a)
    return _psr_value(sr, a.size, skew, kurt, float(sr_benchmark))


def expected_max_sharpe(n_trials, var_sr) -> float:
    """Expected maximum Sharpe of N zero-skill trials, Bailey & Lopez de Prado (2014, JPM 40(5)).

    E[max SR] ~= sqrt(var_sr) ((1-g) Phi^-1(1-1/N) + g Phi^-1(1-1/(N e))),
    g = Euler-Mascheroni. ``var_sr`` is the cross-trial variance of per-period
    Sharpe ratios; N may be fractional (an effective trial count). Returns 0.0
    for N == 1 (and for 1 < N < ~1.28, where the approximation turns negative).
    """
    z = _emax_z(n_trials)
    if z == 0.0:
        return 0.0
    v = float(var_sr)
    if math.isnan(v):
        return math.nan
    if v < 0:
        raise ValueError(f"var_sr must be >= 0, got {var_sr!r}")
    return float(math.sqrt(v) * z)


def dsr(x, n_trials, var_sr) -> dict:
    """Deflated Sharpe Ratio, Bailey & Lopez de Prado (2014, J. Portfolio Mgmt 40(5)).

    DSR = PSR(SR* = expected_max_sharpe(n_trials, var_sr)). Returns
    dict(dsr, sr, sr0, n, skew, kurt) with per-period sr/sr0 and NON-excess kurt.
    """
    a = _as_1d(x)
    n = int(a.size)
    sr = sharpe(a)
    skew, kurt = _std_moments(a) if n >= 2 else (math.nan, math.nan)
    sr0 = expected_max_sharpe(n_trials, var_sr)
    return {
        "dsr": _psr_value(sr, n, skew, kurt, sr0),
        "sr": float(sr),
        "sr0": float(sr0),
        "n": n,
        "skew": float(skew),
        "kurt": float(kurt),
    }


def min_backtest_length(n_trials, target_sr_annual) -> float:
    """Minimum Backtest Length in years, Bailey, Borwein, Lopez de Prado & Zhu (2014, Notices AMS 61(5)).

    MinBTL ~= ((1-g) Phi^-1(1-1/N) + g Phi^-1(1-1/(N e)))^2 / SR^2, the years of
    data needed so that the best of N independent zero-skill configurations is not
    expected to reach the ANNUALIZED Sharpe ``target_sr_annual`` (< 2 ln N / SR^2).
    Returns 0.0 for N == 1 (no selection).
    """
    sr = float(target_sr_annual)
    if not (np.isfinite(sr) and sr > 0):
        raise ValueError(f"target_sr_annual must be > 0, got {target_sr_annual!r}")
    z = _emax_z(n_trials)
    return float(z * z / (sr * sr))


# --------------------------------------------------------------------------- PBO / CSCV


def _sharpe_from_sums(s1, s2, n, mu, var_floor):
    """Sharpe per column from centred block sums (s1 = sum, s2 = sum of squares)."""
    var = (s2 - s1 * s1 / n) / (n - 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sr = (s1 / n + mu) / np.sqrt(var)
    return np.where(var > var_floor, sr, -np.inf)


def _metric_vector(metric, sub, n_cols) -> np.ndarray:
    v = np.asarray(metric(sub), dtype=float).reshape(-1)
    if v.size != n_cols:
        raise ValueError(f"metric must map a (rows, {n_cols}) array to {n_cols} values, got {v.size}")
    return v


def _pbo_select_rank(is_m, oos_m):
    """argmax-IS selection and its average OOS rank / (N + 1), one row per combination."""
    is_m = np.where(np.isnan(is_m), -np.inf, is_m)
    oos_m = np.where(np.isnan(oos_m), -np.inf, oos_m)
    rows = np.arange(is_m.shape[0])
    nstar = np.argmax(is_m, axis=1)
    is_best = is_m[rows, nstar]
    oos_best = oos_m[rows, nstar]
    less = (oos_m < oos_best[:, None]).sum(axis=1)
    ties = (oos_m == oos_best[:, None]).sum(axis=1)  # includes n* itself
    omega = (less + 0.5 * (ties + 1)) / (is_m.shape[1] + 1)
    return is_best, oos_best, omega


def pbo_cscv(M, n_splits: int = 16, metric: Optional[Callable] = None) -> dict:
    """Probability of Backtest Overfitting via CSCV, Bailey, Borwein, Lopez de Prado & Zhu (2017, J. Comput. Finance 20(4)).

    ``M`` is T x N (rows = time, columns = candidate strategies' per-period
    returns). Rows are cut into ``n_splits`` (S, even) contiguous blocks, the
    T mod S trailing rows dropped; every one of the C(S, S/2) block subsets is
    the in-sample half (blocks joined in time order) and its complement the
    out-of-sample half. Per combination: n* = argmax IS metric,
    w = average OOS rank of n* / (N + 1), logit = ln(w / (1 - w)).

    ``metric(R) -> N values`` scores the columns of a (rows x N) array; default
    per-period Sharpe (ddof=1) with zero-variance columns scored -inf (IS and
    OOS alike, so a strategy that goes flat OOS ranks last; NaN scores are
    treated as -inf). Combinations whose IS scores are all -inf are undefined:
    their logit is NaN and they are excluded from the summary statistics.

    Returns dict(pbo = fraction of logits <= 0, logits, n_combinations,
    perf_degradation_slope = OLS slope of OOS on IS metric of n* (finite pairs),
    prob_oos_loss = fraction of combinations with OOS metric of n* < 0).
    """
    R = _as_2d(M, "M")
    T, N = R.shape
    if int(n_splits) != n_splits or int(n_splits) < 2 or int(n_splits) % 2:
        raise ValueError(f"n_splits must be an even integer >= 2, got {n_splits!r}")
    S = int(n_splits)
    if N < 2:
        raise ValueError("M needs at least 2 columns (candidate strategies)")
    if T < S:
        raise ValueError(f"M has T={T} rows < n_splits={S}")
    b = T // S
    R = R[: S * b]
    half = S // 2
    n_half = half * b
    if metric is None and n_half < 2:
        raise ValueError("each half-sample needs >= 2 rows for the default Sharpe metric")

    n_comb = math.comb(S, half)
    is_best = np.empty(n_comb)
    oos_best = np.empty(n_comb)
    omega = np.empty(n_comb)
    combos = itertools.combinations(range(S), half)
    pos = 0

    if metric is None:
        mu = R.mean(axis=0)
        Xb = (R - mu).reshape(S, b, N)  # centring keeps the sum-of-squares formula well conditioned
        s1 = Xb.sum(axis=1)
        s2 = np.einsum("sbn,sbn->sn", Xb, Xb)
        tot1, tot2 = s1.sum(axis=0), s2.sum(axis=0)
        # "zero variance" = below 1e-9 of the column's full-sample variance (rounding floor)
        var_floor = 1e-9 * R.var(axis=0, ddof=1)
        while True:
            chunk = list(itertools.islice(combos, _PBO_CHUNK))
            if not chunk:
                break
            ind = np.zeros((len(chunk), S))
            ind[np.arange(len(chunk))[:, None], np.asarray(chunk)] = 1.0
            is1, is2 = ind @ s1, ind @ s2
            is_m = _sharpe_from_sums(is1, is2, n_half, mu, var_floor)
            oos_m = _sharpe_from_sums(tot1 - is1, tot2 - is2, n_half, mu, var_floor)
            sl = slice(pos, pos + len(chunk))
            is_best[sl], oos_best[sl], omega[sl] = _pbo_select_rank(is_m, oos_m)
            pos += len(chunk)
    else:
        Rb = R.reshape(S, b, N)
        blocks = np.arange(S)
        batch = max(1, min(4096, _MAX_ELEMS // N))
        while True:
            chunk = list(itertools.islice(combos, batch))
            if not chunk:
                break
            is_m = np.empty((len(chunk), N))
            oos_m = np.empty((len(chunk), N))
            for r, combo in enumerate(chunk):
                in_idx = np.asarray(combo)
                out_idx = np.setdiff1d(blocks, in_idx)  # sorted: time order preserved
                is_m[r] = _metric_vector(metric, Rb[in_idx].reshape(-1, N), N)
                oos_m[r] = _metric_vector(metric, Rb[out_idx].reshape(-1, N), N)
            sl = slice(pos, pos + len(chunk))
            is_best[sl], oos_best[sl], omega[sl] = _pbo_select_rank(is_m, oos_m)
            pos += len(chunk)

    valid = is_best > -np.inf
    logits = np.full(n_comb, np.nan)
    logits[valid] = np.log(omega[valid] / (1.0 - omega[valid]))
    if not valid.any():
        return {
            "pbo": math.nan,
            "logits": logits,
            "n_combinations": int(n_comb),
            "perf_degradation_slope": math.nan,
            "prob_oos_loss": math.nan,
        }
    x, y = is_best[valid], oos_best[valid]
    fin = np.isfinite(x) & np.isfinite(y)
    slope = math.nan
    if fin.sum() >= 2:
        xc = x[fin] - x[fin].mean()
        sxx = float(xc @ xc)
        if sxx > 0:
            slope = float(xc @ (y[fin] - y[fin].mean()) / sxx)
    return {
        "pbo": float(np.mean(logits[valid] <= 0.0)),
        "logits": logits,
        "n_combinations": int(n_comb),
        "perf_degradation_slope": slope,
        "prob_oos_loss": float(np.mean(y < 0.0)),
    }


# --------------------------------------------------------------------------- multiple testing


def _prep_pvals(pvals):
    p = np.asarray(pvals, dtype=float)
    flat = p.ravel()
    valid = ~np.isnan(flat)
    if np.any((flat[valid] < 0.0) | (flat[valid] > 1.0)):
        raise ValueError("p-values must lie in [0, 1] (NaN allowed)")
    return flat, valid, p.shape


def _level_arg(v, name: str) -> float:
    fv = float(v)
    if not (0.0 < fv <= 1.0):
        raise ValueError(f"{name} must be in (0, 1], got {v!r}")
    return fv


def _step_up(pvals, q, c_m) -> MultipleTestResult:
    flat, valid, shape = _prep_pvals(pvals)
    adj = np.full(flat.shape, np.nan)
    rej = np.zeros(flat.shape, dtype=bool)
    pv = flat[valid]
    m = pv.size
    if m:
        order = np.argsort(pv, kind="mergesort")
        a = pv[order] * (m * c_m(m)) / np.arange(1, m + 1)
        a = np.minimum(np.minimum.accumulate(a[::-1])[::-1], 1.0)
        out = np.empty(m)
        out[order] = a
        adj[valid] = out
        rej[valid] = out <= q
    return MultipleTestResult(rej.reshape(shape), adj.reshape(shape))


def bh_fdr(pvals, q: float = 0.10) -> MultipleTestResult:
    """Benjamini-Hochberg (1995, JRSS-B 57(1)) step-up FDR control at level q.

    Returns ``(reject, p_adjusted)`` with p_adj(i) = min_{k>=i} m p(k)/k (capped
    at 1); reject = p_adjusted <= q. NaN p-values are never rejected, keep NaN
    adjusted values and do not count toward m (as R's ``p.adjust``).
    """
    return _step_up(pvals, _level_arg(q, "q"), lambda m: 1.0)


def by_fdr(pvals, q: float = 0.10) -> MultipleTestResult:
    """Benjamini-Yekutieli (2001, Ann. Statist. 29(4)) FDR control under arbitrary dependence.

    BH with m replaced by m c(m), c(m) = sum_{i=1}^m 1/i. Returns
    ``(reject, p_adjusted)``; NaN handling as :func:`bh_fdr`.
    """
    return _step_up(pvals, _level_arg(q, "q"), lambda m: float(np.sum(1.0 / np.arange(1, m + 1))))


def holm(pvals, alpha: float = 0.05) -> MultipleTestResult:
    """Holm (1979, Scand. J. Statist. 6(2)) step-down FWER control.

    Returns ``(reject, p_adjusted)`` with p_adj(i) = max_{j<=i} min(1, (m-j+1) p(j));
    reject = p_adjusted <= alpha. NaN handling as :func:`bh_fdr`.
    """
    a_lvl = _level_arg(alpha, "alpha")
    flat, valid, shape = _prep_pvals(pvals)
    adj = np.full(flat.shape, np.nan)
    rej = np.zeros(flat.shape, dtype=bool)
    pv = flat[valid]
    m = pv.size
    if m:
        order = np.argsort(pv, kind="mergesort")
        a = pv[order] * (m - np.arange(m))
        a = np.minimum(np.maximum.accumulate(a), 1.0)
        out = np.empty(m)
        out[order] = a
        adj[valid] = out
        rej[valid] = out <= a_lvl
    return MultipleTestResult(rej.reshape(shape), adj.reshape(shape))


# --------------------------------------------------------------------------- bootstrap


def stationary_bootstrap_indices(n, mean_block, n_boot, rng=None) -> np.ndarray:
    """Stationary-bootstrap resample indices, Politis & Romano (1994, JASA 89(428)).

    Each of the ``n_boot`` rows is built from blocks with uniform random starts and
    geometric lengths (p = 1/mean_block, mean = mean_block), wrapping around the
    end of the series. Returns an int array of shape (n_boot, n) with values in
    [0, n). ``mean_block == 1`` is the i.i.d. bootstrap.
    """
    n = _pos_int(n, "n")
    n_boot = _pos_int(n_boot, "n_boot")
    p = 1.0 / _block_arg(mean_block)
    g = _rng(rng)
    starts = g.integers(0, n, size=(n_boot, n))
    if p >= 1.0 or n == 1:
        return starts
    new_block = g.random((n_boot, n)) < p
    new_block[:, 0] = True
    t = np.arange(n)
    last = np.where(new_block, t, 0)
    np.maximum.accumulate(last, axis=1, out=last)  # start position of the current block
    idx = np.take_along_axis(starts, last, axis=1)
    idx += t - last
    idx %= n
    return idx


def _flat_top(u: np.ndarray) -> np.ndarray:
    u = np.abs(u)
    return np.where(u <= 0.5, 1.0, np.where(u <= 1.0, 2.0 * (1.0 - u), 0.0))


def optimal_block_length(x) -> float:
    """Automatic mean block length for the STATIONARY bootstrap.

    Politis & White (2004, Econometric Rev. 23(1)) with the Patton, Politis &
    White (2009, Econometric Rev. 28(4)) correction D_SB = 2 g(0)^2:
    b = (2 G^2 / D_SB)^(1/3) n^(1/3), G and g(0) estimated with the flat-top lag
    window at bandwidth M = 2 m_hat (Politis 2003 rule: c = 2, K_N = 5), capped
    at ceil(min(3 sqrt(n), n/3)). Returns a float >= 1; falls back to n^(1/3)
    when the estimate degenerates (short/constant series, g(0) <= 0).
    """
    a = _as_1d(x)
    n = a.size
    fallback = max(1.0, n ** (1.0 / 3.0)) if n else 1.0
    if n < 10:
        return float(fallback)
    e = a - a.mean()
    if _zero_dispersion(np.sqrt(np.mean(e * e)), np.max(np.abs(a))):
        return float(fallback)
    k_n = max(5, int(math.ceil(math.sqrt(math.log10(n)))))
    m_max = min(int(math.ceil(math.sqrt(n))) + k_n, n - 1)
    b_max = math.ceil(min(3.0 * math.sqrt(n), n / 3.0))
    acov = np.array([e[k:] @ e[: n - k] / n for k in range(m_max + 1)])
    if not acov[0] > 0:
        return float(fallback)
    insig = np.abs(acov[1:] / acov[0]) < 2.0 * math.sqrt(math.log10(n) / n)  # lags 1..m_max
    m_hat = None
    for j in range(1, m_max - k_n + 2):  # first run of K_N insignificant lags starts at j
        if insig[j - 1 : j - 1 + k_n].all():
            m_hat = j - 1
            break
    big_m = m_max if m_hat is None else min(2 * max(m_hat, 1), m_max)
    k = np.arange(1, big_m + 1)
    lam = _flat_top(k / big_m)
    g0 = acov[0] + 2.0 * float(np.sum(lam * acov[1 : big_m + 1]))
    big_g = 2.0 * float(np.sum(lam * k * acov[1 : big_m + 1]))
    d_sb = 2.0 * g0 * g0
    if not (np.isfinite(g0) and g0 > 0 and np.isfinite(big_g) and d_sb > 0):
        return float(fallback)
    b_opt = (2.0 * big_g * big_g / d_sb) ** (1.0 / 3.0) * n ** (1.0 / 3.0)
    if not np.isfinite(b_opt):
        return float(fallback)
    return float(min(max(b_opt, 1.0), float(b_max)))


def _boot_means(d: np.ndarray, n_boot: int, mean_block: float, rng) -> np.ndarray:
    """(n_boot, K) stationary-bootstrap column means of the T x K matrix d (chunked)."""
    T, K = d.shape
    g = _rng(rng)
    out = np.empty((n_boot, K))
    chunk = max(1, min(n_boot, _MAX_ELEMS // T))
    for s in range(0, n_boot, chunk):
        m = min(chunk, n_boot - s)
        idx = stationary_bootstrap_indices(T, mean_block, m, g)
        flat = (np.arange(m)[:, None] * T + idx).ravel()
        counts = np.bincount(flat, minlength=m * T).reshape(m, T).astype(float)
        out[s : s + m] = counts @ d
    out /= T
    return out


def _sb_long_run_variance(d: np.ndarray, mean_block: float) -> np.ndarray:
    """Var*(sqrt(T) mean*) under the stationary bootstrap, per column (exact, no Monte Carlo).

    Politis & Romano (1994, Lemma 1), the omega_k^2 of Hansen (2005):
    gamma_0 + 2 sum_{i=1}^{T-1} kappa(T, i) gamma_i,
    kappa(T, i) = (1 - i/T)(1-q)^i + (i/T)(1-q)^(T-i), q = 1/mean_block.
    """
    T, K = d.shape
    e = d - d.mean(axis=0)
    nfft = 1 << max(1, int(math.ceil(math.log2(2 * T))))
    acov = np.empty((T, K))
    step = max(1, _MAX_ELEMS // nfft)
    for c0 in range(0, K, step):
        f = np.fft.rfft(e[:, c0 : c0 + step], n=nfft, axis=0)
        acov[:, c0 : c0 + step] = np.fft.irfft(np.abs(f) ** 2, n=nfft, axis=0)[:T] / T
    lrv = acov[0].copy()
    if T > 1:
        q = 1.0 / mean_block
        i = np.arange(1, T, dtype=float)
        kappa = (1.0 - i / T) * (1.0 - q) ** i + (i / T) * (1.0 - q) ** (T - i)
        lrv += 2.0 * (kappa @ acov[1:])
    return np.maximum(lrv, 0.0)


def bootstrap_mean_ci(x, alpha: float = 0.05, n_boot: int = 2000, mean_block=None, rng=None) -> dict:
    """Stationary-bootstrap percentile CI for the mean, Politis & Romano (1994, JASA 89(428)).

    Percentile interval (Efron & Tibshirani 1993) of ``n_boot`` stationary-bootstrap
    means; ``mean_block`` defaults to :func:`optimal_block_length`. Returns
    dict(mean, lo, hi, p_le_zero = fraction of bootstrap means <= 0).
    """
    a = _as_1d(x)
    lvl = float(alpha)
    if not (0.0 < lvl < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    n_boot = _pos_int(n_boot, "n_boot")
    n = a.size
    mean = float(a.mean()) if n else math.nan
    if n < 2:
        return {"mean": mean, "lo": math.nan, "hi": math.nan, "p_le_zero": math.nan}
    mb = optimal_block_length(a) if mean_block is None else _block_arg(mean_block)
    bm = _boot_means(a[:, None], n_boot, mb, rng)[:, 0]
    lo, hi = np.quantile(bm, [lvl / 2.0, 1.0 - lvl / 2.0])
    return {"mean": mean, "lo": float(lo), "hi": float(hi), "p_le_zero": float(np.mean(bm <= 0.0))}


# --------------------------------------------------------------------------- t statistics


def ttest_mean(x) -> dict:
    """One-sample Student t-test of H0: mean = 0 (Student 1908), t with n-1 df.

    Returns dict(t, p_two, p_one_greater, n); nan statistics for n < 2 or zero std.
    """
    a = _as_1d(x)
    n = int(a.size)
    out = {"t": math.nan, "p_two": math.nan, "p_one_greater": math.nan, "n": n}
    if n < 2:
        return out
    sd = float(a.std(ddof=1))
    if _zero_dispersion(sd, np.max(np.abs(a))):
        return out
    t = float(a.mean()) / (sd / math.sqrt(n))
    out["t"] = t
    out["p_two"] = float(2.0 * stats.t.sf(abs(t), n - 1))
    out["p_one_greater"] = float(stats.t.sf(t, n - 1))
    return out


def newey_west_t(x, lags=None) -> dict:
    """HAC t-statistic of the mean, Newey & West (1987, Econometrica 55(3)), Bartlett kernel.

    Long-run variance gamma_0 + 2 sum_{l=1}^{L} (1 - l/(L+1)) gamma_l (gamma_l with
    1/n normalization); default L = floor(4 (n/100)^(2/9)) (Newey & West 1994,
    Rev. Econ. Stud. 61(4)). p_one_greater uses the asymptotic N(0,1).
    Returns dict(t, p_one_greater, lags).
    """
    a = _as_1d(x)
    n = a.size
    if lags is None:
        n_lags = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))) if n else 0
    else:
        n_lags = int(lags)
        if n_lags != lags or n_lags < 0:
            raise ValueError(f"lags must be a non-negative integer, got {lags!r}")
    n_lags = max(0, min(n_lags, n - 1))
    out = {"t": math.nan, "p_one_greater": math.nan, "lags": int(n_lags)}
    if n < 2:
        return out
    e = a - a.mean()
    if _zero_dispersion(np.sqrt(np.mean(e * e)), np.max(np.abs(a))):
        return out
    lrv = float(e @ e) / n
    for lag in range(1, n_lags + 1):
        lrv += 2.0 * (1.0 - lag / (n_lags + 1.0)) * float(e[lag:] @ e[:-lag]) / n
    if not lrv > 0:
        return out
    t = float(a.mean()) / math.sqrt(lrv / n)
    out["t"] = t
    out["p_one_greater"] = float(stats.norm.sf(t))
    return out


# --------------------------------------------------------------------------- data snooping


def _snoop_setup(d, n_boot, mean_block, rng):
    """Shared machinery for RC / SPA / Romano-Wolf: sample means, omega_k, bootstrap means."""
    D = _as_2d(d, "d")
    T, K = D.shape
    if T < 2:
        raise ValueError("d needs at least 2 rows (time periods)")
    n_boot = _pos_int(n_boot, "n_boot")
    scale = np.max(np.abs(D), axis=0)
    flat = _zero_dispersion(D.std(axis=0, ddof=1), scale)
    if mean_block is None:
        blocks = [optimal_block_length(D[:, k]) for k in range(K) if not flat[k]]
        mb = float(np.mean(blocks)) if blocks else max(1.0, T ** (1.0 / 3.0))
    else:
        mb = _block_arg(mean_block)
    dbar = D.mean(axis=0)
    omega = np.sqrt(_sb_long_run_variance(D, mb))
    degen = flat | _zero_dispersion(omega, scale)
    boot = _boot_means(D, n_boot, mb, rng)
    return T, dbar, omega, degen, scale, boot


def _studentized_stats(dbar, omega, degen, scale, T):
    """t_k = sqrt(T) dbar_k / omega_k; zero-variance columns get +inf / -inf / 0 by sign."""
    with np.errstate(divide="ignore", invalid="ignore"):
        t = math.sqrt(T) * dbar / omega
    sign = np.where(dbar > _REL_TOL * scale, np.inf, np.where(dbar < -_REL_TOL * scale, -np.inf, 0.0))
    return np.where(degen, sign, t)


def _studentized_boot(boot, center, omega, degen, T):
    with np.errstate(divide="ignore", invalid="ignore"):
        z = math.sqrt(T) * (boot - center) / omega
    return np.where(degen, 0.0, z)


def _studentized_bootstrap(d, n_boot=2000, mean_block=None, rng=None):
    """(t, t_boot): studentized statistics and their re-centred bootstrap draws (Romano-Wolf input)."""
    T, dbar, omega, degen, scale, boot = _snoop_setup(d, n_boot, mean_block, rng)
    t = _studentized_stats(dbar, omega, degen, scale, T)
    return t, _studentized_boot(boot, dbar, omega, degen, T)


def whites_reality_check(d, n_boot: int = 2000, mean_block=None, rng=None) -> float:
    """White's (2000, Econometrica 68(5)) Reality Check p-value for H0: max_k E[d_k] <= 0.

    ``d`` is T x K performance differentials vs the benchmark (here per-period
    strategy returns vs zero). V = max_k sqrt(T) mean_k; bootstrap
    V*_b = max_k sqrt(T)(mean*_{b,k} - mean_k) from the stationary bootstrap
    (``mean_block`` defaults to the average Politis-White estimate over columns).
    Returns p = fraction of V*_b > V.
    """
    T, dbar, _, _, _, boot = _snoop_setup(d, n_boot, mean_block, rng)
    v = math.sqrt(T) * float(np.max(dbar))
    v_star = math.sqrt(T) * np.max(boot - dbar, axis=1)
    return float(np.mean(v_star > v))


def hansen_spa(d, n_boot: int = 2000, mean_block=None, rng=None) -> dict:
    """Hansen's (2005, J. Bus. Econ. Statist. 23(4)) test for Superior Predictive Ability.

    T_SPA = max(0, max_k sqrt(T) mean_k / omega_k), omega_k^2 the exact
    stationary-bootstrap variance of sqrt(T) mean_k (Politis-Romano kernel, as in
    Hansen 2005). Bootstrap statistics max(0, max_k sqrt(T)(mean*_k - g(mean_k))/omega_k)
    use g_l(x) = max(x, 0), g_c(x) = x 1{x >= -sqrt((omega_k^2/T) 2 ln ln T)},
    g_u(x) = x; p = fraction of bootstrap statistics > T_SPA, so
    p_lower <= p_consistent <= p_upper. Returns dict(p_consistent, p_lower, p_upper, stat).
    """
    T, dbar, omega, degen, scale, boot = _snoop_setup(d, n_boot, mean_block, rng)
    stat = max(0.0, float(np.max(_studentized_stats(dbar, omega, degen, scale, T))))
    thresh = np.sqrt(omega**2 / T * 2.0 * max(math.log(math.log(T)), 0.0)) if T > 1 else 0.0
    centers = {
        "p_lower": np.maximum(dbar, 0.0),
        "p_consistent": dbar * (dbar >= -thresh),
        "p_upper": dbar,
    }
    out = {}
    for key, center in centers.items():
        z = _studentized_boot(boot, center, omega, degen, T)
        t_star = np.maximum(np.max(z, axis=1), 0.0)
        out[key] = float(np.mean(t_star > stat))
    return {"p_consistent": out["p_consistent"], "p_lower": out["p_lower"], "p_upper": out["p_upper"], "stat": stat}


def romano_wolf_stepdown(d, n_boot: int = 2000, mean_block=None, rng=None) -> np.ndarray:
    """Romano & Wolf (2005, Econometrica 73(4)) studentized stepdown, H0_k: E[d_k] <= 0.

    Statistics t_k = sqrt(T) mean_k / omega_k are ordered t_(1) >= ... >= t_(K);
    adjusted p_(j) = max(p_(j-1), #{b: max_{i>=j} t*_{b,(i)} >= t_(j)} / n_boot) with
    re-centred stationary-bootstrap draws t*_{b,k} = sqrt(T)(mean*_{b,k} - mean_k)/omega_k
    (adjusted p-value form of Romano & Wolf 2016, Stat. Probab. Lett. 113).
    Returns the adjusted p-values in the original column order.
    """
    t, t_star = _studentized_bootstrap(d, n_boot, mean_block, rng)
    order = np.argsort(-t, kind="mergesort")
    t_sorted = t[order]
    tail_max = np.maximum.accumulate(t_star[:, order][:, ::-1], axis=1)[:, ::-1]
    p_sorted = np.maximum.accumulate(np.mean(tail_max >= t_sorted[None, :], axis=0))
    p_adj = np.empty_like(p_sorted)
    p_adj[order] = p_sorted
    return p_adj


# --------------------------------------------------------------------------- number of trials


def _corr_matrix(R: np.ndarray):
    """Correlation matrix with zero-variance columns treated as uncorrelated."""
    N = R.shape[1]
    ok = ~_zero_dispersion(R.std(axis=0, ddof=1), np.max(np.abs(R), axis=0))
    C = np.eye(N)
    if ok.sum() >= 2:
        C[np.ix_(ok, ok)] = np.corrcoef(R[:, ok], rowvar=False)
    C = np.clip((C + C.T) / 2.0, -1.0, 1.0)
    np.fill_diagonal(C, 1.0)
    return C, ok


def effective_number_of_trials(R) -> float:
    """Effective number of independent trials, Li & Ji (2005, Heredity 95).

    M_eff = sum_i [I(|l_i| >= 1) + (|l_i| - floor(|l_i|))] over the eigenvalues
    l_i of the correlation matrix of the T x N return matrix ``R``. Zero-variance
    columns are excluded. Returned as a float clipped to [1, N].
    """
    X = _as_2d(R, "R")
    if X.shape[0] < 2:
        raise ValueError("R needs at least 2 rows")
    N = X.shape[1]
    C, ok = _corr_matrix(X)
    if ok.sum() < 2:
        return 1.0
    lam = np.abs(np.linalg.eigvalsh(C[np.ix_(ok, ok)]))
    near = np.round(lam)
    lam = np.where(np.abs(lam - near) < 1e-9, near, lam)  # e.g. 19.999999999999996 -> 20
    m_eff = float(np.sum((lam >= 1.0) + (lam - np.floor(lam))))
    return float(min(max(m_eff, 1.0), float(N)))


def cluster_trials(R, threshold: float = 0.5) -> ClusterResult:
    """Cluster trials by return correlation (Lopez de Prado & Lewis 2019, Quant. Finance 19(9)).

    Average-linkage hierarchical clustering (scipy.cluster.hierarchy) on the
    correlation distance sqrt(0.5 (1 - rho)) of Lopez de Prado (2016, JPM 42(4)),
    cut at distance ``threshold``. Zero-variance columns are uncorrelated with
    everything. Returns ``(n_clusters, labels)``, labels 1..n_clusters per column.
    """
    X = _as_2d(R, "R")
    if X.shape[0] < 2:
        raise ValueError("R needs at least 2 rows")
    N = X.shape[1]
    if N == 1:
        return ClusterResult(1, np.ones(1, dtype=int))
    C, _ = _corr_matrix(X)
    dist = np.sqrt(np.clip(0.5 * (1.0 - C), 0.0, None))
    np.fill_diagonal(dist, 0.0)
    Z = hierarchy.linkage(squareform(dist, checks=False), method="average")
    labels = hierarchy.fcluster(Z, t=float(threshold), criterion="distance").astype(int)
    return ClusterResult(int(np.unique(labels).size), labels)


def sharpe_variance_across_trials(R) -> float:
    """Cross-trial variance (ddof=1) of per-period Sharpe ratios: V[SR_n] for :func:`dsr`.

    Bailey & Lopez de Prado (2014, J. Portfolio Mgmt 40(5)). Columns with an
    undefined Sharpe (zero variance) are skipped; nan if fewer than 2 remain.
    """
    X = _as_2d(R, "R")
    srs = np.array([sharpe(X[:, j]) for j in range(X.shape[1])])
    srs = srs[np.isfinite(srs)]
    if srs.size < 2:
        return math.nan
    return float(np.var(srs, ddof=1))
