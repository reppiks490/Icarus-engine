# CL (Claude, Anthropic) — 2026-10-04 — tests for cl-boos1, the external breadth loader and R6
import gzip
import json
import types

import numpy as np
import pandas as pd

from cl_lab import backtest, bars, boos, causality, costs, external, sessions


def _fake_sess(n=3700):
    d = pd.bdate_range("2010-06-07", periods=n)
    return types.SimpleNamespace(dates=np.array([x.date() for x in d], dtype=object), D=n)


def _cand(i):
    return boos.R6Candidate("fake", (("i", i),))


def test_boos_confirms_a_planted_edge_and_rejects_noise():
    s = _fake_sess()
    rng = np.random.default_rng(0)
    series = {i: rng.normal(0.0, 1.0, s.D) for i in range(8)}
    series[0] = rng.normal(0.25, 1.0, s.D)                       # planted: t ~ 15 over 3,700 days
    cands = [_cand(i) for i in range(8)]

    def run_fn(c, sess, cost):
        x = series[dict(c.params)["i"]] - (0.05 if cost is costs.NQ_STRESS else 0.0)
        t = pd.DataFrame(dict(day=np.arange(sess.D)))
        return backtest.Result(t, x, x * 20, sess.D, x / 1e4)

    recs, diag = boos.evaluate(s, cands, run_fn, costs.NQ, costs.NQ_STRESS, "fake")
    st = {r["params"]["i"]: r["status"] for r in recs}
    assert st[0] == "BOOS_CONFIRMED" and sum(v == "BOOS_CONFIRMED" for v in st.values()) == 1
    assert diag["sessions"] > 3500 and diag["confirmed"] == 1


def _write(root, sym, rows):
    p = root / "tiingo" / "eod"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{sym}.json.gz").write_bytes(gzip.compress(json.dumps(rows).encode()))


def test_breadth_counts_up_names_and_needs_five(tmp_path):
    days = ["2024-01-02", "2024-01-03", "2024-01-04"]
    for k, s in enumerate(external.MEGA8[:6]):
        px = [100, 101, 99] if k < 4 else [100, 99, 101]
        _write(tmp_path, s, [dict(date=d + "T00:00:00.000Z", adjClose=p) for d, p in zip(days, px)])
    b = external.breadth(external.tiingo_closes(str(tmp_path)))
    assert list(b.round(4)) == [round(4 / 6, 4), round(2 / 6, 4)]
    assert external.breadth(external.tiingo_closes(str(tmp_path), symbols=external.MEGA8[:3])).empty


def test_r6_uses_previous_day_breadth_only():
    f = causality.synth_frame(n_sessions=80)
    s = sessions.build_sessions(bars.annotate(f))
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(s.dates)))
    s.cache[("ext", "MEGA8_UP_FRAC")] = pd.Series(np.where(np.arange(len(idx)) % 2 == 0, 0.9, 0.1), index=idx)
    hi = boos.r6_trades(s, "momentum", "high")
    assert hi and all(np.arange(len(idx))[t.day - 1] % 2 == 0 for t in hi)   # prior session was high-breadth
    rev = boos.r6_trades(s, "reversal", "high")
    assert [(t.day, -t.direction) for t in hi] == [(t.day, t.direction) for t in rev]
