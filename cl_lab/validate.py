# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.validate: pre-registered gate stack that promotes candidates to champions
"""Gate stack (all thresholds pre-registered here; changing any of them requires a
GATES_VERSION bump, which is recorded in every run):

G1 sample      TUNE trades >= 60 on >= 40 distinct days
G2 tune edge   TUNE Newey-West t >= 2.0 on daily net P&L (after costs)
G3 fdr         Benjamini-Hochberg q <= 0.10 across EVERY candidate of the asset
G4 dsr         Deflated Sharpe >= 0.95 with N = Li-Ji effective number of trials
G5 hold        untouched HOLD window: NW t >= 1.65 and Holm-adjusted p <= 0.05
               across the candidates that reached HOLD
G6 stress      HOLD mean daily net > 0 with doubled costs
G7 stability   >= 60% of calendar quarters (TUNE+HOLD) net positive and
               >= 50% of one-parameter grid neighbours positive on TUNE
G8 snooping    asset-level Hansen SPA p <= 0.10 and CSCV PBO <= 0.25 on TUNE

CHAMPION = G1..G8; CHALLENGER = G1..G5; CANDIDATE = G1..G4; else REJECTED.
Forward evidence = sessions after the registry's first registration of a rule.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from . import backtest, stats

GATES_VERSION = "cl-gates-1"
TUNE_END = date(2025, 10, 1)
T = dict(min_trades=60, min_trade_days=40, tune_t=2.0, fdr_q=0.10, dsr_min=0.95, hold_t=1.65, holm_alpha=0.05,
         quarter_pos=0.60, neighbour_pos=0.50, spa_p_max=0.10, pbo_max=0.25, pbo_splits=16, n_boot=1000)


def _neighbours(cands):
    by_fam = {}
    for c in cands:
        by_fam.setdefault(c.family, []).append(c)
    out = {}
    for fam, cs in by_fam.items():
        for a in cs:
            pa = dict(a.params)
            out[a.id] = [b.id for b in cs if b.id != a.id and
                         sum(pa[k] != v for k, v in b.params) == 1]
    return out


def _r(x, n=6):
    if x is None:
        return None
    x = float(x)
    return None if not math.isfinite(x) else round(x, n)


def evaluate(sess, cands, cost, stress_cost, metric="points", forward_start=None, seed=20261003):
    """Run every candidate and the full gate stack on one asset's Sessions."""
    rng = np.random.default_rng(seed)
    dates = pd.to_datetime(pd.Series(sess.dates))
    tune = (dates < pd.Timestamp(TUNE_END)).to_numpy()
    fwd = np.zeros(sess.D, bool) if forward_start is None else (dates >= pd.Timestamp(forward_start)).to_numpy()
    hold = ~tune & ~fwd
    res = {c.id: backtest.run(c, sess, cost) for c in cands}
    key = "daily_net_ret" if metric == "returns" else "daily_net_pts"
    ids = [c.id for c in cands]
    M = np.column_stack([getattr(res[i], key) for i in ids])
    Xt, Xh = M[tune], M[hold]

    rec = {}
    p_tune = np.ones(len(ids))
    for k, c in enumerate(cands):
        t = res[c.id].trades
        tt = t[t["day"].map(lambda d: bool(tune[d]))] if len(t) else t
        nw = stats.newey_west_t(Xt[:, k]) if Xt[:, k].std() > 0 else {"t": float("nan"), "p_one_greater": 1.0}
        p_tune[k] = nw["p_one_greater"] if np.isfinite(nw["t"]) else 1.0
        rec[c.id] = dict(id=c.id, family=c.family, params=dict(c.params), tune_trades=int(len(tt)),
                         tune_trade_days=int(tt["day"].nunique()) if len(tt) else 0,
                         tune_mean=_r(Xt[:, k].mean(), 8), tune_t=_r(nw["t"], 3), tune_p=_r(p_tune[k], 6))
    bh = stats.bh_fdr(p_tune, q=T["fdr_q"])
    m_eff = float(stats.effective_number_of_trials(Xt)) if Xt.shape[0] > 2 else float(len(ids))
    var_sr = float(stats.sharpe_variance_across_trials(Xt))
    pbo = stats.pbo_cscv(Xt, n_splits=T["pbo_splits"]) if Xt.shape[0] >= T["pbo_splits"] * 2 else None
    spa = stats.hansen_spa(Xt, n_boot=T["n_boot"], rng=rng)
    nbr = _neighbours(cands)
    tune_mean = {i: rec[i]["tune_mean"] or 0.0 for i in ids}

    reached_hold = []
    for k, i in enumerate(ids):
        r = rec[i]
        r["g1_sample"] = r["tune_trades"] >= T["min_trades"] and r["tune_trade_days"] >= T["min_trade_days"]
        r["g2_tune_edge"] = (r["tune_t"] or -9) >= T["tune_t"]
        r["g3_fdr"] = bool(np.asarray(bh[0])[k])
        d = stats.dsr(Xt[:, k], n_trials=max(1, int(round(m_eff))), var_sr=var_sr) if Xt[:, k].std() > 0 else {"dsr": 0.0}
        r["dsr"] = _r(d["dsr"], 4)
        r["g4_dsr"] = (r["dsr"] or 0) >= T["dsr_min"]
        if r["g1_sample"] and r["g2_tune_edge"] and r["g3_fdr"] and r["g4_dsr"]:
            reached_hold.append(k)

    holm_p = {}
    if reached_hold:
        hp = []
        for k in reached_hold:
            nw = stats.newey_west_t(Xh[:, k]) if Xh[:, k].std() > 0 else {"t": float("nan"), "p_one_greater": 1.0}
            rec[ids[k]]["hold_mean"], rec[ids[k]]["hold_t"] = _r(Xh[:, k].mean(), 8), _r(nw["t"], 3)
            hp.append(nw["p_one_greater"] if np.isfinite(nw["t"]) else 1.0)
        adj = np.asarray(stats.holm(hp, alpha=T["holm_alpha"])[1])
        holm_p = {ids[k]: float(a) for k, a in zip(reached_hold, adj)}

    q_index = pd.PeriodIndex(dates, freq="Q")
    in_th = tune | hold
    for k, i in enumerate(ids):
        r = rec[i]
        r["g5_hold"] = i in holm_p and (r.get("hold_t") or -9) >= T["hold_t"] and holm_p[i] <= T["holm_alpha"]
        r["hold_holm_p"] = _r(holm_p.get(i), 6)
        r["g6_stress"] = r["g7_stability"] = False
        if r["g5_hold"]:
            sr = backtest.run(cands[k], sess, stress_cost)
            sx = (sr.daily_net_ret if metric == "returns" else sr.daily_net_pts)[hold]
            r["hold_mean_stress"] = _r(sx.mean(), 8)
            r["g6_stress"] = sx.mean() > 0
            qs = pd.Series(M[in_th, k]).groupby(q_index[in_th]).sum()
            r["quarters_positive"] = _r((qs > 0).mean(), 3)
            nb = nbr[i]
            r["neighbours_positive"] = _r(np.mean([tune_mean[j] > 0 for j in nb]), 3) if nb else None
            r["g7_stability"] = (r["quarters_positive"] or 0) >= T["quarter_pos"] and \
                (r["neighbours_positive"] or 0) >= T["neighbour_pos"]
        g8 = (spa["p_consistent"] <= T["spa_p_max"]) and pbo is not None and pbo["pbo"] <= T["pbo_max"]
        r["g8_snooping"] = bool(g8)
        if r["g1_sample"] and r["g2_tune_edge"] and r["g3_fdr"] and r["g4_dsr"]:
            if r["g5_hold"]:
                r["status"] = "CHAMPION" if (r["g6_stress"] and r["g7_stability"] and g8) else "CHALLENGER"
            else:
                r["status"] = "CANDIDATE"
        else:
            r["status"] = "REJECTED"
    diag = dict(candidates=len(ids), tune_sessions=int(tune.sum()), hold_sessions=int(hold.sum()),
                forward_sessions=int(fwd.sum()), m_eff=_r(m_eff, 2), var_sr=_r(var_sr, 8),
                pbo=_r(pbo["pbo"], 4) if pbo else None, spa_p=_r(spa["p_consistent"], 4),
                bh_rejections=int(np.asarray(bh[0]).sum()), reached_hold=len(reached_hold), metric=metric)
    ctx = dict(ids=ids, M=M, dates=dates, trades={i: res[i].trades for i in ids})
    return rec, diag, ctx


def forward_stats(ctx, rid, start):
    """Evidence strictly after a rule's registration: sessions dated > start (a date)."""
    k = ctx["ids"].index(rid)
    mask = (ctx["dates"] > pd.Timestamp(start)).to_numpy()
    t = ctx["trades"][rid]
    n_tr = int(t["day"].map(lambda d: bool(mask[d])).sum()) if len(t) else 0
    x = ctx["M"][mask, k]
    return dict(after=str(start), sessions=int(mask.sum()), trades=n_tr,
                mean=_r(x.mean(), 8) if len(x) else None, total=_r(x.sum(), 6) if len(x) else 0.0)
