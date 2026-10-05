# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.ml: walk-forward ML family cl-ml1 (docs/CL_PREREG_R2.md section 3)
"""One pre-registered strategy per (asset, decision time): an L2 logistic regression on ten
causal features, refit every 21 sessions on an expanding window with a 1-session embargo,
trading the sign of the 16:00 close versus the decision bar's open when the predicted
probability leaves a +/-0.02 band. Every prediction is out-of-sample, in TUNE as in HOLD; the
candidates still pass through the full cl-gates-1 stack. ``qualify`` adds the
qualification report (Brier, log loss, AUC, calibration slope, coefficient stability,
baselines, label-permutation control)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import backtest, conditions, multisession, stats, validate
from .backtest import bracket_trade
from .sessions import slot_of

ML_VERSION = "cl-ml1"
ALPHA, BAND, REFIT, MIN_TRAIN, EMBARGO = 0.1, 0.02, 21, 120, 1
DECISIONS = ("10:00", "12:00", "15:30")
FEATURES = ("ret_prev_close", "ret_open", "gap", "rv_so_far", "range_atr", "vwap_dist_atr", "rel_volume",
            "prev_day_ret", "f9", "f10")
PERMUTATION_SEED, PERMUTATION_FLAG_T = 20261004, 3.0


@dataclass(frozen=True)
class MCandidate:
    family: str
    params: tuple

    @property
    def id(self) -> str:
        blob = json.dumps([ML_VERSION, self.family, [list(p) for p in self.params]], sort_keys=True)
        return "m" + hashlib.sha1(blob.encode()).hexdigest()[:11]


CANDIDATES = [MCandidate("mlwf", (("decision", h),)) for h in DECISIONS]


def _imb(V, TB):
    with np.errstate(invalid="ignore", divide="ignore"):
        den = np.nansum(V, axis=1)
        return np.where(den > 0, np.nansum(2 * TB - V, axis=1) / np.where(den > 0, den, 1.0), np.nan)


def features(sess, k: int, leak: bool = False):
    """(D x 10 matrix, availability note). Row d uses bars of session d that closed before slot k
    opened and sessions < d only. ``leak`` swaps in the session's own 16:00 close (test control)."""
    kind = sess.cache.get("ml_kind", "futures")
    lc = multisession.last_close(sess)
    prev, prev2 = np.r_[np.nan, lc[:-1]], np.r_[np.nan, np.nan, lc[:-2]]
    C, O, H, L, V = sess.C, sess.O, sess.H, sess.L, sess.V
    with np.errstate(invalid="ignore", divide="ignore"):
        f = [C[:, k - 1] / prev - 1, C[:, k - 1] / O[:, 0] - 1, O[:, 0] / prev - 1,
             np.std(np.diff(np.log(C[:, :k]), axis=1), axis=1),
             (np.nanmax(H[:, :k], axis=1) - np.nanmin(L[:, :k], axis=1)) / sess.atr14,
             (C[:, k - 1] - sess.vwap[:, k - 1]) / sess.atr14]
        cumv = np.nansum(V[:, :k], axis=1)
        f.append(cumv / sess.trailing_stat(f"ml|cumv|{k}", cumv, np.mean, 20, 20))
        f.append(prev / prev2 - 1)
        if kind == "crypto":
            TB = sess.cache.get("TB")
            if TB is None:
                return None, "taker_buy_volume unavailable"
            full = _imb(V, TB)
            f += [_imb(V[:, :k], TB[:, :k]), np.r_[np.nan, full[:-1]]]
        else:
            vix, v9 = conditions._prev_ext(sess, "VIX_close"), conditions._prev_ext(sess, "VIX9D_close")
            if vix is None or v9 is None:
                return None, "Cboe VIX/VIX9D unavailable"
            f += [np.log(vix), v9 / vix - 1]
    F = np.column_stack(f)
    if leak:
        F[:, 0] = C[:, -1] / O[:, k] - 1
    return F, "ok"


def labels(sess, k):
    with np.errstate(invalid="ignore"):
        return (sess.C[:, -1] > sess.O[:, k]).astype(float)


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def fit_logistic(X, y, alpha=ALPHA, iters=25, tol=1e-8):
    """argmin mean log loss + alpha/2 * ||w||^2 (intercept unpenalized), Newton-IRLS."""
    n, p = X.shape
    Xa = np.c_[np.ones(n), X]
    beta = np.zeros(p + 1)
    pen = np.r_[0.0, np.full(p, alpha)]
    for _ in range(iters):
        mu = sigmoid(Xa @ beta)
        g = Xa.T @ (mu - y) / n + pen * beta
        Hm = (Xa.T * (mu * (1 - mu))) @ Xa / n + np.diag(pen) + 1e-12 * np.eye(p + 1)
        step = np.linalg.solve(Hm, g)
        beta -= step
        if np.max(np.abs(step)) < tol:
            break
    return beta


def walk_forward(F, y, ok, permute=False, seed=PERMUTATION_SEED):
    """Out-of-sample probabilities (NaN where no model existed), per-refit coefficients, base rates."""
    D = len(y)
    rows = ok & np.isfinite(F).all(axis=1) & np.isfinite(y)
    p, base = np.full(D, np.nan), np.full(D, np.nan)
    coefs = []
    rng = np.random.default_rng(seed)
    csum = np.cumsum(rows)
    starts = [b for b in range(EMBARGO + 1, D) if csum[b - EMBARGO - 1] >= MIN_TRAIN]
    if not starts:
        return p, coefs, base
    for b in range(starts[0], D, REFIT):
        idx = np.nonzero(rows[: b - EMBARGO])[0]
        X, yy = F[idx], y[idx]
        if permute:
            yy = rng.permutation(yy)
        mu, sd = X.mean(axis=0), X.std(axis=0)
        sd[sd == 0] = 1.0
        beta = fit_logistic((X - mu) / sd, yy)
        te = np.arange(b, min(b + REFIT, D))
        te = te[rows[te]]
        if len(te):
            p[te] = sigmoid(beta[0] + ((F[te] - mu) / sd) @ beta[1:])
            base[te] = yy.mean()
        coefs.append(beta[1:])
    return p, coefs, base


def predictions(sess, k, permute=False, leak=False):
    key = ("ml", k, permute, leak)
    if key not in sess.cache:
        F, note = features(sess, k, leak=leak)
        if F is None:
            sess.cache[key] = (None, note, None, None, None)
        else:
            y = labels(sess, k)
            p, coefs, base = walk_forward(F, y, sess.complete.copy(), permute=permute)
            sess.cache[key] = (p, note, y, coefs, base)
    return sess.cache[key]


def ml_trades(sess, k, permute=False, leak=False):
    p = predictions(sess, k, permute, leak)[0]
    if p is None:
        return []
    out = []
    for d in np.nonzero(sess.complete & np.isfinite(p))[0]:
        if p[d] >= 0.5 + BAND:
            out.append(bracket_trade(sess, d, k, +1))
        elif p[d] <= 0.5 - BAND:
            out.append(bracket_trade(sess, d, k, -1))
    return out


def run_m(c, sess, cost):
    return backtest.to_result(ml_trades(sess, slot_of(dict(c.params)["decision"])), sess, cost)


def _auc(p, y):
    from scipy.stats import rankdata
    pos = y == 1
    n1, n0 = int(pos.sum()), int((~pos).sum())
    if n1 == 0 or n0 == 0:
        return None
    r = rankdata(p)
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _strategy_t(sess, trades, cost, mask, metric):
    res = backtest.to_result(trades, sess, cost)
    x = (res.daily_net_ret if metric == "returns" else res.daily_net_pts)[mask]
    nw = stats.newey_west_t(x) if len(x) > 2 and x.std() > 0 else {"t": float("nan")}
    return dict(trades=int(res.trades["day"].map(lambda d: bool(mask[d])).sum()) if res.n_trades else 0,
                mean=round(float(x.mean()), 8) if len(x) else None,
                nw_t=round(float(nw["t"]), 3) if np.isfinite(nw["t"]) else None)


def qualify(c, sess, cost, metric, forward_start) -> dict:
    k = slot_of(dict(c.params)["decision"])
    p, note, y, coefs, base = predictions(sess, k)
    if p is None:
        return dict(id=c.id, status="UNAVAILABLE", reason=note)
    d = pd.to_datetime(pd.Series(sess.dates))
    tune = (d < pd.Timestamp(validate.TUNE_END)).to_numpy()
    pre_fwd = (d < pd.Timestamp(forward_start)).to_numpy()
    hold = ~tune & pre_fwd
    out = dict(id=c.id, version=ML_VERSION, decision=dict(c.params)["decision"], refits=len(coefs))
    for name, m in (("oos_tune", tune), ("oos_hold", hold)):
        sel = m & np.isfinite(p)
        if sel.sum() < 10:
            out[name] = dict(rows=int(sel.sum()))
            continue
        pp, yy, bb = p[sel], y[sel], base[sel]
        z = np.log(pp / (1 - pp)).reshape(-1, 1)
        slope = fit_logistic(z, yy, alpha=0.0)[1]
        out[name] = dict(rows=int(sel.sum()), up_rate=round(float(yy.mean()), 4),
                         brier=round(float(np.mean((pp - yy) ** 2)), 5),
                         brier_climatology=round(float(np.mean((bb - yy) ** 2)), 5),
                         log_loss=round(float(-np.mean(yy * np.log(pp) + (1 - yy) * np.log(1 - pp))), 5),
                         auc=(round(a, 4) if (a := _auc(pp, yy)) is not None else None),
                         calibration_slope=round(float(slope), 3))
    if coefs:
        Bm = np.sign(np.vstack(coefs))
        maj = np.sign(Bm.sum(axis=0))
        out["coef_sign_stability"] = {f: round(float(np.mean(Bm[:, j] == maj[j])), 3) for j, f in enumerate(FEATURES)}
    elig = sess.complete & np.isfinite(p)
    long_tr = [bracket_trade(sess, dd, k, +1) for dd in np.nonzero(elig)[0]]
    F = features(sess, k)[0]
    mom_tr = [bracket_trade(sess, dd, k, int(np.sign(F[dd, 0]))) for dd in np.nonzero(elig & (np.sign(F[:, 0]) != 0))[0]]
    out["baselines"] = {"always_long": {w: _strategy_t(sess, long_tr, cost, m, metric) for w, m in (("tune", tune), ("hold", hold))},
                        "sign_ret_prev_close": {w: _strategy_t(sess, mom_tr, cost, m, metric) for w, m in (("tune", tune), ("hold", hold))}}
    perm = _strategy_t(sess, ml_trades(sess, k, permute=True), cost, tune, metric)
    out["permutation_control"] = dict(perm, seed=PERMUTATION_SEED,
                                      flag="HARNESS_SUSPECT" if (perm["nw_t"] is not None and abs(perm["nw_t"]) >= PERMUTATION_FLAG_T) else "OK")
    return out


def prereg_manifest() -> dict:
    return dict(version=ML_VERSION, ids=[c.id for c in CANDIDATES], decisions=list(DECISIONS),
                alpha=ALPHA, band=BAND, refit=REFIT, min_train=MIN_TRAIN, embargo=EMBARGO)
