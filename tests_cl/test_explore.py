# CL (Claude, Anthropic) — 2026-10-04 — tests for cl_lab.explore and cl_lab.conditions (causality + accounting)
import numpy as np
import pandas as pd
import pytest

from cl_lab import causality, conditions, explore


@pytest.fixture(scope="module")
def frame():
    return causality.synth_frame()


def _vix(sess):
    idx = pd.bdate_range("2024-01-01", "2025-12-31")
    vals = 15 + np.cumsum(np.random.default_rng(5).normal(0, 0.5, len(idx)))
    sess.cache[("ext", "VIX_close")] = pd.Series(vals, index=idx)
    sess.cache[("ext", "VIX9D_close")] = pd.Series(vals + np.random.default_rng(6).normal(0, 1, len(idx)), index=idx)


def test_sampling_is_deterministic_and_skips_explored():
    a = explore.sample("MNQ", "2026-10-05", set())
    assert [c.id for c in a] == [c.id for c in explore.sample("MNQ", "2026-10-05", set())]
    b = explore.sample("MNQ", "2026-10-05", {c.id for c in a})
    assert not {c.id for c in a} & {c.id for c in b} and len(a) == len(b) == explore.EXPLORE_PER_RUN
    assert len({c.id for c in explore.space()}) == len(explore.space()) > 10_000


def test_every_conditioner_is_causal(frame):
    for cond in conditions.CONDITIONS:
        c = explore.XCandidate("vwap", tuple(sorted(dict(check=30, side="both", start="10:00", regime="all",
                                                          cond=cond).items())))
        fn = lambda s, c=c: explore.run_x_trades(c, s)
        assert causality.prefix_violations(frame, fn, prepare=_vix) == [], cond
        assert causality.intraday_violations(frame, fn, [(70, 5), (100, 40)], prepare=_vix) == [], cond


def test_sampled_explorer_candidates_are_causal(frame):
    for c in explore.sample("TEST", "2026-10-05", set(), k=12):
        fn = lambda s, c=c: explore.run_x_trades(c, s)
        assert causality.prefix_violations(frame, fn, cuts=(100,), prepare=_vix) == [], c.spec()
        assert causality.intraday_violations(frame, fn, [(90, 11), (120, 60)], prepare=_vix) == [], c.spec()


def test_leaky_conditioner_is_caught(frame):
    def leaky(s):
        from cl_lab.backtest import bracket_trade
        return [bracket_trade(s, d, 0, 1) for d in range(s.D) if s.complete[d] and s.C[d, 77] > s.O[d, 0]]
    assert causality.intraday_violations(frame, leaky, [(60, 0), (80, 11), (100, 23)])


def test_ledger_roundtrip(tmp_path):
    p = tmp_path / "l.jsonl"
    explore.append_ledger(str(p), [dict(asset="MNQ", id="x1", p=0.5)])
    explore.append_ledger(str(p), [dict(asset="MNQ", id="x2", p=0.2)])
    assert [r["id"] for r in explore.load_ledger(str(p))] == ["x1", "x2"]
