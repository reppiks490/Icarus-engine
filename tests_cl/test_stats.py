# CL (Claude, Anthropic) — 2026-10-03 — tests for cl_lab.stats
"""Known-answer and property tests for the CL lab validation statistics."""
import math

import numpy as np
import pytest
from scipy import stats as sps

from cl_lab import stats as S


def _rng(seed=7):
    return np.random.default_rng(seed)


def test_psr_matches_closed_form_with_series_moments():
    x = _rng().normal(0.05, 1.0, 600)
    sr = x.mean() / x.std(ddof=1)
    g3 = sps.skew(x, bias=True)
    g4 = sps.kurtosis(x, fisher=False, bias=True)
    want = sps.norm.cdf(sr * math.sqrt(len(x) - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr * sr))
    assert S.psr(x) == pytest.approx(want, rel=1e-6, abs=1e-9)


def test_psr_increases_with_sample_size():
    base = _rng(1).normal(0.0, 1.0, 400)
    base = base - base.mean() + 0.08  # exact positive drift
    assert S.psr(np.tile(base, 3)) > S.psr(base) > 0.5


def test_expected_max_sharpe_and_dsr_monotone():
    assert S.expected_max_sharpe(1, 0.01) == 0.0
    e = [S.expected_max_sharpe(n, 0.01) for n in (2, 10, 100, 1000)]
    assert all(b > a for a, b in zip(e, e[1:]))
    x = _rng(2).normal(0.1, 1.0, 500)
    d = S.dsr(x, n_trials=100, var_sr=0.002)
    assert d["dsr"] <= S.psr(x)
    assert S.min_backtest_length(100, 1.0) > S.min_backtest_length(10, 1.0)


def test_pbo_dominant_strategy_is_not_overfit():
    r = _rng(3)
    M = r.normal(0.0, 1.0, (1600, 50))
    M[:, 0] += 0.5
    out = S.pbo_cscv(M, n_splits=16)
    assert out["n_combinations"] == math.comb(16, 8)
    assert out["pbo"] < 0.1


def test_pbo_pure_noise_is_coin_flip_on_average():
    vals = [S.pbo_cscv(_rng(10 + k).normal(0, 1, (800, 30)), n_splits=8)["pbo"] for k in range(6)]
    assert 0.25 < float(np.mean(vals)) < 0.75


def test_pbo_rejects_bad_split_args():
    with pytest.raises(ValueError):
        S.pbo_cscv(np.zeros((10, 3)), n_splits=16)
    with pytest.raises(ValueError):
        S.pbo_cscv(np.ones((100, 3)), n_splits=7)


BH_P = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
        0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.000]


def test_bh_classic_example_rejects_first_four():
    res = S.bh_fdr(BH_P, q=0.05)
    assert list(np.asarray(res[0], bool)) == [True] * 4 + [False] * 11


def test_holm_classic_example_rejects_first_three():
    # Holm thresholds 0.05/15, 0.05/14, 0.05/13, 0.05/12: 0.0095 > 0.05/12 = 0.004167 -> stop after 3.
    res = S.holm(BH_P, alpha=0.05)
    assert list(np.asarray(res[0], bool)) == [True] * 3 + [False] * 12


def test_stationary_bootstrap_indices_shape_range_and_block_length():
    idx = S.stationary_bootstrap_indices(500, 10, 200, _rng(4))
    assert idx.shape == (200, 500) and idx.min() >= 0 and idx.max() < 500
    breaks = (np.diff(idx, axis=1) != 1) & ~((idx[:, :-1] == 499) & (idx[:, 1:] == 0))
    mean_block = idx.size / (breaks.sum() + idx.shape[0])
    assert 9.0 < mean_block < 11.0


def test_snooping_tests_null_and_alternative():
    null = _rng(5).normal(0, 1, (500, 20))
    assert S.whites_reality_check(null, n_boot=500, rng=_rng(6)) > 0.05
    assert S.hansen_spa(null, n_boot=500, rng=_rng(6))["p_consistent"] > 0.05
    alt = null.copy()
    alt[:, 3] += 0.3
    assert S.whites_reality_check(alt, n_boot=500, rng=_rng(6)) < 0.01
    assert S.hansen_spa(alt, n_boot=500, rng=_rng(6))["p_consistent"] < 0.01
    rw = np.asarray(S.romano_wolf_stepdown(alt, n_boot=500, rng=_rng(6)))
    raw = np.array([S.ttest_mean(alt[:, k])["p_one_greater"] for k in range(alt.shape[1])])
    assert np.all(rw + 1.0 / 500 >= raw)  # stepdown never below raw, up to bootstrap resolution
    assert rw[3] < 0.01


def test_effective_number_of_trials_bounds():
    base = _rng(8).normal(0, 1, (2000, 1))
    assert S.effective_number_of_trials(np.repeat(base, 10, axis=1)) == pytest.approx(1.0, abs=0.5)
    assert S.effective_number_of_trials(_rng(9).normal(0, 1, (2000, 20))) > 12


def test_newey_west_close_to_ordinary_t_for_iid():
    x = _rng(11).normal(0.05, 1.0, 2000)
    assert S.newey_west_t(x)["t"] == pytest.approx(S.ttest_mean(x)["t"], rel=0.05)
