# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.boos: backward out-of-sample protocol cl-boos1 (docs/CL_PREREG_R5.md)
"""Every family already evaluated on the 2024-2026 MNQ tape is re-run, ids unchanged, on continuous NQ
2010-06-07 -> 2024-09-01, a span no CL rule has seen. Per family: one-sided Newey-West p of daily net
P&L at base cost -> Benjamini-Yekutieli q <= 0.05 -> DSR >= 0.95 with Li-Ji effective trials and the
family's Sharpe dispersion -> NW t > 0 in both halves -> positive mean at stress cost. Pass =
BOOS_CONFIRMED (forward watch; never a champion by itself)."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import conditions, hypotheses, stats

BOOS_VERSION = "cl-boos1"
WINDOW = (pd.Timestamp("2010-06-07"), pd.Timestamp("2024-09-01"))
SPLIT = pd.Timestamp("2017-07-01")
Q, DSR_MIN = 0.05, 0.95


def _nw(x):
    if len(x) < 10 or np.std(x) == 0:
        return None, 1.0
    r = stats.newey_west_t(x)
    return float(r["t"]), float(r["p_one_greater"])


def _r(x, n=4):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def evaluate(sess, cands, run_fn, cost, stress_cost, family, metric="points"):
    key = "daily_net_ret" if metric == "returns" else "daily_net_pts"
    d = pd.to_datetime(pd.Series(sess.dates))
    win = ((d >= WINDOW[0]) & (d < WINDOW[1])).to_numpy()
    first = win & (d < SPLIT).to_numpy()
    second = win & (d >= SPLIT).to_numpy()
    res = {c.id: run_fn(c, sess, cost) for c in cands}
    M = np.column_stack([getattr(res[c.id], key)[win] for c in cands]) if cands else np.zeros((0, 0))
    ts, ps = zip(*[_nw(M[:, k]) for k in range(M.shape[1])]) if cands else ((), ())
    rej = np.asarray(stats.by_fdr(list(ps), q=Q)[0]) if cands else np.array([])
    m_eff = float(stats.effective_number_of_trials(M)) if M.shape[0] > 2 and M.shape[1] > 1 else float(len(cands))
    var_sr = float(stats.sharpe_variance_across_trials(M)) if M.shape[1] > 1 else 0.0
    out = []
    for k, c in enumerate(cands):
        x = M[:, k]
        full = getattr(res[c.id], key)
        dsr = stats.dsr(x, n_trials=max(1, int(round(m_eff))), var_sr=var_sr)["dsr"] if np.std(x) > 0 else 0.0
        t1, _ = _nw(full[first])
        t2, _ = _nw(full[second])
        t = res[c.id].trades
        r = dict(id=c.id, family=family, params=dict(c.params), protocol=BOOS_VERSION,
                 trades=int(t["day"].map(lambda i: bool(win[i])).sum()) if len(t) else 0,
                 mean=_r(x.mean(), 6), nw_t=_r(ts[k], 3), p=_r(ps[k], 6), by_reject=bool(rej[k]), dsr=_r(dsr),
                 t_first_half=_r(t1, 3), t_second_half=_r(t2, 3))
        ok = r["by_reject"] and (r["dsr"] or 0) >= DSR_MIN and (t1 or -1) > 0 and (t2 or -1) > 0
        if ok:
            s = getattr(run_fn(c, sess, stress_cost), key)[win]
            r["mean_stress"] = _r(s.mean(), 6)
            ok = s.mean() > 0
        r["status"] = "BOOS_CONFIRMED" if ok else "BOOS_REJECTED"
        out.append(r)
    diag = dict(family=family, candidates=len(cands), sessions=int(win.sum()), m_eff=_r(m_eff, 2),
                var_sr=_r(var_sr, 10), by_rejections=int(rej.sum()) if len(rej) else 0,
                confirmed=sum(r["status"] == "BOOS_CONFIRMED" for r in out))
    return out, diag


# ---------------- R6: megacap-breadth conditioned end-of-day rules (registered before the data exists) ----
@dataclass(frozen=True)
class R6Candidate:
    family: str
    params: tuple

    @property
    def id(self) -> str:
        blob = json.dumps(["cl-r6", self.family, [list(p) for p in self.params]], sort_keys=True)
        return "b" + hashlib.sha1(blob.encode()).hexdigest()[:11]


R6_CANDIDATES = [R6Candidate("eodbreadth", (("base", b), ("breadth", s)))
                 for b in ("momentum", "reversal") for s in ("high", "low")]


def r6_trades(sess, base, side):
    up = conditions._prev_ext(sess, "MEGA8_UP_FRAC")       # last value dated strictly before the session
    if up is None:
        return []
    keep = (up >= 0.75) if side == "high" else (up <= 0.25)
    trades = hypotheses.eod_trades(sess, "unconditional")
    if base == "reversal":
        trades = [dataclasses.replace(t, direction=-t.direction) for t in trades]
    return [t for t in trades if keep[t.day]]


def run_r6(c, sess, cost):
    from . import backtest
    p = dict(c.params)
    return backtest.to_result(r6_trades(sess, p["base"], p["breadth"]), sess, cost)
