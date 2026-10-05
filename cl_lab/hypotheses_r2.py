# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.hypotheses_r2: pre-registered family cl-r2 (docs/CL_PREREG_R2.md)
"""R2-A end-of-day reversal (MNQ, HOLD-confirmation protocol cl-hc1), R2-B month-end
rebalancing (B1 daily NASDAQ-100 + DGS10 since 1986; B2 MNQ execution twin), R2-C
pre-FOMC drift (MNQ event study) and R2-D crypto aggressive-flow imbalance. Every rule,
threshold and variant is fixed by the pre-registration; ids are frozen in prereg_r2.json."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import backtest, conditions, events, hypotheses, multisession, stats, validate
from .backtest import bracket_trade
from .sessions import slot_of

R2_VERSION = "cl-r2"
HC_VERSION = "cl-hc1"
HC = dict(hold_t=1.65, holm_alpha=0.05, min_hold_trades=30)
B_COST_BP, B_STRESS_BP = 1.0, 3.0


@dataclass(frozen=True)
class QCandidate:
    family: str
    params: tuple

    @property
    def id(self) -> str:
        blob = json.dumps([R2_VERSION, self.family, [list(p) for p in self.params]], sort_keys=True)
        return "q" + hashlib.sha1(blob.encode()).hexdigest()[:11]

    def spec(self) -> dict:
        return dict(id=self.id, family=self.family, version=R2_VERSION, params=dict(self.params))


def _windows(sess, forward_start):
    d = pd.to_datetime(pd.Series(sess.dates))
    tune = (d < pd.Timestamp(validate.TUNE_END)).to_numpy()
    hold = ~tune & (d < pd.Timestamp(forward_start)).to_numpy()
    return tune, hold


def _nw(x):
    if len(x) < 3 or np.std(x) == 0:
        return dict(t=None, p=1.0)
    r = stats.newey_west_t(x)
    return dict(t=float(r["t"]), p=float(r["p_one_greater"]))


def _r(x, n=6):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


# ---------------- R2-A: end-of-day reversal ----------------
A_VARIANTS = ("unconditional", "r_top_tercile", "rv_open_top_tercile", "vix_low")
A_CANDIDATES = [QCandidate("eodrev", (("variant", v),)) for v in A_VARIANTS]


def eodrev_trades(sess, variant):
    trades = hypotheses.eod_trades(sess, "unconditional" if variant == "vix_low" else variant)
    if variant == "vix_low":
        m = conditions.mask(sess, "vix_low")
        trades = [t for t in trades if m[t.day]]
    return [dataclasses.replace(t, direction=-t.direction) for t in trades]


def run_a(c, sess, cost):
    return backtest.to_result(eodrev_trades(sess, dict(c.params)["variant"]), sess, cost)


def hold_confirm(sess, cands, cost, stress_cost, run_fn, forward_start, metric="points"):
    """cl-hc1: a TUNE-derived hypothesis is decided on HOLD only (Holm across the family)."""
    key = "daily_net_ret" if metric == "returns" else "daily_net_pts"
    tune, hold = _windows(sess, forward_start)
    rec, ps, cols, trades = {}, [], [], {}
    for c in cands:
        res, sr = run_fn(c, sess, cost), run_fn(c, sess, stress_cost)
        x, xs = getattr(res, key), getattr(sr, key)
        t = res.trades
        n_hold = int(t["day"].map(lambda d: bool(hold[d])).sum()) if len(t) else 0
        n_tune = int(t["day"].map(lambda d: bool(tune[d])).sum()) if len(t) else 0
        h, tt = _nw(x[hold]), _nw(x[tune])
        ps.append(h["p"])
        cols.append(x)
        trades[c.id] = t
        rec[c.id] = dict(id=c.id, family=c.family, params=dict(c.params), protocol=HC_VERSION,
                         tune_trades=n_tune, tune_t=_r(tt["t"], 3), tune_mean=_r(x[tune].mean(), 6),
                         hold_trades=n_hold, hold_t=_r(h["t"], 3), hold_p=_r(h["p"], 6),
                         hold_mean=_r(x[hold].mean(), 6), hold_total=_r(x[hold].sum(), 4),
                         hold_mean_stress=_r(xs[hold].mean(), 6))
    adj = np.asarray(stats.holm(ps, alpha=HC["holm_alpha"])[1]) if ps else []
    for (rid, r), a in zip(rec.items(), adj):
        r["hold_holm_p"] = _r(a, 6)
        ok = (r["hold_t"] or -9) >= HC["hold_t"] and a <= HC["holm_alpha"] and r["hold_trades"] >= HC["min_hold_trades"] \
            and (r["hold_mean_stress"] or -1) > 0
        r["status"] = "HOLD_CONFIRMED" if ok else "REJECTED"
    diag = dict(protocol=HC_VERSION, thresholds=HC, hold_sessions=int(hold.sum()), tune_sessions=int(tune.sum()),
                candidates=len(cands))
    ctx = dict(ids=[c.id for c in cands], M=np.column_stack(cols) if cols else np.zeros((sess.D, 0)),
               dates=pd.to_datetime(pd.Series(sess.dates)), trades=trades)
    return rec, diag, ctx


# ---------------- R2-D: crypto aggressive-flow imbalance ----------------
D_WINDOWS = {"open30": "10:00", "morning": "12:00"}
D_CANDIDATES = [QCandidate("flow", (("window", w), ("direction", d))) for w in D_WINDOWS for d in ("cont", "rev")]


def flow_imbalance(sess, window):
    key = ("r2", "imb", window)
    if key in sess.cache:
        return sess.cache[key]
    TB = sess.cache.get("TB")
    if TB is None:
        return None
    k = slot_of(D_WINDOWS[window])
    v, tb = sess.V[:, :k], TB[:, :k]
    with np.errstate(invalid="ignore", divide="ignore"):
        den = np.nansum(v, axis=1)
        imb = np.where(den > 0, np.nansum(2 * tb - v, axis=1) / np.where(den > 0, den, 1.0), np.nan)
    imb[~sess.complete] = np.nan
    sess.cache[key] = imb
    return imb


def flow_trades(sess, window, direction):
    imb = flow_imbalance(sess, window)
    if imb is None:
        return []
    thr = sess.trailing_stat(f"r2|flow_abs_{window}", np.abs(imb), lambda w: np.quantile(w, 2 / 3), 250, 60)
    with np.errstate(invalid="ignore"):
        gate = sess.complete & np.isfinite(imb) & np.isfinite(thr) & (np.abs(imb) >= thr)
    k = slot_of(D_WINDOWS[window])
    out = []
    for d in np.nonzero(gate)[0]:
        s = int(np.sign(imb[d]))
        if s:
            out.append(bracket_trade(sess, d, k, s if direction == "cont" else -s))
    return out


def run_d(c, sess, cost):
    p = dict(c.params)
    return backtest.to_result(flow_trades(sess, p["window"], p["direction"]), sess, cost)


# ---------------- R2-C: pre-FOMC drift (event study) ----------------
C_CANDIDATE = QCandidate("prefomc", (("window", "14:00>13:55"),))


def pre_fomc_trades(sess):
    pos = {d: i for i, d in enumerate(sess.dates)}
    out, skipped = [], []
    for ev in events.fomc_events():
        i1, i0 = pos.get(ev["decision"]), pos.get(ev["first_day"])
        if i1 is None or i0 is None or i0 != i1 - 1:
            if sess.dates[0] <= ev["decision"] <= sess.dates[-1]:
                skipped.append(str(ev["decision"]))
            continue
        t = multisession.hold_trade(sess, i0, slot_of("14:00"), i1, slot_of("13:55"), +1, "fomc")
        (out.append(t) if t else skipped.append(str(ev["decision"])))
    return out, skipped


def event_study(sess, cost, forward_start, seed=20261004):
    from scipy.stats import binomtest
    trades, skipped = pre_fomc_trades(sess)
    res = multisession.to_result(trades, sess, cost)
    t = res.trades
    tune, hold = _windows(sess, forward_start)
    out = dict(id=C_CANDIDATE.id, family="prefomc", version=R2_VERSION, events=len(t), skipped=skipped,
               status="INSUFFICIENT_SAMPLE", reason="G1 needs 60 events; FOMC gives about 8 a year")
    if len(t):
        bp = (1e4 * t["net_pts"] / t["entry_px"]).to_numpy()
        k = int((t["net_pts"] > 0).sum())
        ci = stats.bootstrap_mean_ci(bp, alpha=0.10, n_boot=2000, rng=np.random.default_rng(seed)) if len(bp) >= 5 else {}
        out.update(mean_bp=_r(bp.mean(), 2), median_bp=_r(np.median(bp), 2), t=_r(stats.ttest_mean(bp)["t"], 3) if len(bp) > 2 else None,
                   positive=k, sign_p=_r(binomtest(k, len(bp), 0.5, alternative="greater").pvalue, 4),
                   ci90_bp=[_r(ci.get("lo"), 2), _r(ci.get("hi"), 2)], total_net_usd=_r(t["net_usd"].sum(), 2),
                   tune_events=int(sum(tune[d] for d in t["day"])), hold_events=int(sum(hold[d] for d in t["day"])),
                   per_event=[dict(decision=str(sess.dates[r.exit_day]), net_pts=_r(r.net_pts, 2), bp=_r(b, 1))
                              for r, b in zip(t.itertuples(), bp)])
    return out


# ---------------- R2-B: month-end rebalancing ----------------
B_VARIANTS = ("window5_z1", "next1_z1", "window5_linear")


def bond_daily_returns(dgs10: pd.Series) -> pd.Series:
    y = dgs10.dropna().astype(float)
    yl = y.shift(1)
    dur = (1 - (1 + yl / 200) ** -20) / (yl / 100)
    return (-dur * y.diff() / 100 + yl / 100 / 252).dropna()


def month_end_signals(ndx: pd.Series, dgs10: pd.Series) -> list[dict]:
    px = ndx.dropna().astype(float).sort_index()
    dates = list(pd.to_datetime(px.index))
    req = px.pct_change()
    rb = bond_daily_returns(dgs10)
    rb.index = pd.to_datetime(rb.index)
    out = []
    for m in events.month_ends([d.date() for d in dates]):
        m0, t = m["m0"], m["t"]
        e6, e7 = t - 6, t - 7
        if e7 <= m0 or e7 - 59 < 1:
            continue
        r_eq = px.iloc[e6] / px.iloc[m0] - 1
        sel = rb[(rb.index > dates[m0]) & (rb.index <= dates[e7])]
        r_bd = float(np.prod(1 + sel.to_numpy()) - 1) if len(sel) else 0.0
        wd = dates[e7 - 59:e7 + 1]
        rel = (req.reindex(wd) - rb.reindex(wd)).dropna()
        if len(rel) < 40:
            continue
        sig = float(rel.std(ddof=1))
        n = e6 - m0
        z = (r_eq - r_bd) / (sig * np.sqrt(n)) if sig > 0 else np.nan
        out.append(dict(month=m["month"], m0=m0, t=t, entry=t - 5, z=float(z), r_eq=float(r_eq), r_bd=r_bd,
                        entry_date=str(dates[t - 5].date()), exit_date=str(dates[t].date())))
    return out


def month_end_daily(ndx: pd.Series, dgs10: pd.Series, forward_start):
    px = ndx.dropna().astype(float).sort_index()
    dates = pd.to_datetime(px.index)
    ret = px.pct_change().to_numpy()
    sigs = [s for s in month_end_signals(ndx, dgs10) if np.isfinite(s["z"])]
    N = len(px)
    series, counts, stress, weights = {}, {}, {}, {}
    for v in B_VARIANTS:
        w, cnt = np.zeros(N), np.zeros(N, int)
        for s in sigs:
            z, t = s["z"], s["t"]
            if v == "window5_linear":
                a = -float(np.clip(z / 2, -1, 1))
                span = slice(t - 4, t + 1)
            else:
                if abs(z) <= 1:
                    continue
                a = -float(np.sign(z))
                span = slice(t - 4, t + 1) if v == "window5_z1" else slice(t - 4, t - 3)
            if a != 0:
                w[span] = a
                cnt[t - 5] += 1
        series[v] = multisession.daily_weights(ret, w, B_COST_BP)
        stress[v] = multisession.daily_weights(ret, w, B_STRESS_BP)
        counts[v], weights[v] = cnt, w
    tune = (dates < pd.Timestamp(validate.TUNE_END))
    M = np.column_stack([series[v][tune] for v in B_VARIANTS])
    var_sr = float(stats.sharpe_variance_across_trials(M))
    rec = validate.evaluate_external([d.date() for d in dates], series, counts, stress, set(B_VARIANTS),
                                     len(B_VARIANTS), var_sr, forward_start=forward_start)
    periods = {"1986-1996": ("1986-01-01", "1997-01-01"), "1997-2023 (paper sample)": ("1997-01-01", "2024-01-01"),
               "2024-": ("2024-01-01", "2100-01-01")}
    for v in B_VARIANTS:
        sub = {}
        for name, (a, b) in periods.items():
            m = (dates >= pd.Timestamp(a)) & (dates < pd.Timestamp(b))
            x = series[v][m]
            sub[name] = dict(trades=int(counts[v][m].sum()), mean_daily_bp=_r(1e4 * x.mean(), 3) if len(x) else None,
                             total_bp=_r(1e4 * x.sum(), 1), nw_t=_r(_nw(x)["t"], 3))
        rec[v]["subsamples"] = sub
        rec[v]["id"] = QCandidate("monthend", (("variant", v),)).id
    diag = dict(signals=len(sigs), first_signal=sigs[0]["month"] if sigs else None, last_signal=sigs[-1]["month"] if sigs else None,
                var_sr=_r(var_sr, 10), cost_bp_rt=B_COST_BP, stress_bp_rt=B_STRESS_BP, n_trials=len(B_VARIANTS),
                trading_days=N, first=str(dates[0].date()), last=str(dates[-1].date()))
    return rec, diag, sigs


def month_end_twin(sess, sigs, cost) -> dict:
    """B2: the B1a signal executed on the MNQ tape, 16:00 close of T-5 to 16:00 close of T (descriptive)."""
    pos = {d: i for i, d in enumerate(sess.dates)}
    trades = []
    for s in sigs:
        if abs(s["z"]) <= 1:
            continue
        i0 = pos.get(pd.Timestamp(s["entry_date"]).date())
        i1 = pos.get(pd.Timestamp(s["exit_date"]).date())
        if i0 is not None and i1 is not None:
            t = multisession.hold_trade(sess, i0, multisession.CLOSE, i1, multisession.CLOSE, -int(np.sign(s["z"])), "monthend")
            if t:
                trades.append(t)
    res = multisession.to_result(trades, sess, cost)
    t = res.trades
    return dict(id=QCandidate("monthend_mnq", (("variant", "window5_z1"),)).id, status="DESCRIPTIVE", trades=len(t),
                total_net_usd=_r(t["net_usd"].sum(), 2) if len(t) else 0.0,
                per_trade=[dict(entry=str(r.date), direction=int(r.direction), net_pts=_r(r.net_pts, 2)) for r in t.itertuples()])


R3_HOLD_CONFIRM = {"ETHUSDT": ("qce1276a5f9b",)}   # R3-1, registered after R2 TUNE, before its HOLD statistic


FORWARD_WATCH = {"ETHUSDT": ("qce1276a5f9b",)}   # R4-1: forward-only monitoring, decided at >= 60 FORWARD trades
FORWARD_RULE = dict(min_trades=60, nw_t=1.65)


def forward_watch(ctx, ids, forward_start):
    """FORWARD evidence for watched rules (sessions on/after forward_start only)."""
    out = []
    mask = (ctx["dates"] >= pd.Timestamp(forward_start)).to_numpy()
    for rid in ids:
        if rid not in ctx["ids"]:
            continue
        k = ctx["ids"].index(rid)
        x = ctx["M"][mask, k]
        t = ctx["trades"][rid]
        n = int(t["day"].map(lambda d: bool(mask[d])).sum()) if len(t) else 0
        nw = _nw(x)
        status = "WATCHING"
        if n >= FORWARD_RULE["min_trades"]:
            status = "FORWARD_CONFIRMED" if (nw["t"] or -9) >= FORWARD_RULE["nw_t"] else "FORWARD_REJECTED"
        out.append(dict(id=rid, protocol="R4-1", after=str(forward_start), sessions=int(mask.sum()), trades=n,
                        mean=_r(x.mean(), 8) if len(x) else None, nw_t=_r(nw["t"], 3), status=status, rule=FORWARD_RULE))
    return out


def prereg_manifest() -> dict:
    return dict(version=R2_VERSION,
                eodrev=[c.id for c in A_CANDIDATES], flow=[c.id for c in D_CANDIDATES],
                monthend=[QCandidate("monthend", (("variant", v),)).id for v in B_VARIANTS],
                monthend_mnq=QCandidate("monthend_mnq", (("variant", "window5_z1"),)).id, prefomc=C_CANDIDATE.id)
