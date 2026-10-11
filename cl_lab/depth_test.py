# CL lane — 2026-10-10 — pre-registered test D1 (docs/DEPTH_PREREG_D1.md): does real order flow confirm a failed sweep?
"""Runs D1-A (refill speed after a multi-level sweep -> 5-minute move) and D1-B (10-level book imbalance ->
15-minute move) on every NQ MBP-10 day in the depth cache. Thresholds, horizons, nulls and gates are fixed
by the registration; nothing here may be tuned. Output is aggregate statistics only; no vendor rows."""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

PROTOCOL = "depth-d1"
FAST, SLOW = 1.0, 0.5
MIN_DAYS, MIN_EVENTS = 20, 100
PERMS = 5000
TICKS_COST = 5.4                 # MNQ $2.70 round turn / $0.50 per tick
ALPHA = 0.05
PRIMARY_MOVE, SECONDARY_MOVES = "move_300s", ("move_30s", "move_60s")
PRIMARY_H, SECONDARY_H = 15, (5, 30)


def _day_files(cache: str, kind: str) -> dict[str, str]:
    pattern = {"resilience": os.path.join(cache, "resilience", "*", "nq", "*.csv.gz"),
               "features": os.path.join(cache, "features", "*", "mbp10", "nq", "*.csv.gz")}[kind]
    out: dict[str, str] = {}
    for p in sorted(glob.glob(pattern)):
        out.setdefault(os.path.basename(p)[:10], p)        # a day held by two accounts counts once
    return out


def _holm(ps: dict[str, float]) -> dict[str, float]:
    order = sorted(ps, key=ps.get)
    adj, run = {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, (len(order) - i) * ps[k]))
        adj[k] = run
    return adj


def _day_weighted(values: np.ndarray, days: np.ndarray) -> float:
    s = pd.Series(values).groupby(days).mean()
    return float(s.mean()) if len(s) else float("nan")


def sweep_effect(ev: pd.DataFrame, move: str, rng: np.random.Generator, perms: int = PERMS) -> dict:
    """D1-A: SLOW minus FAST, day-weighted, against within-day label shuffles."""
    e = ev[(ev["levels_swept"] >= 2) & ev["refill_5s"].notna() & ev[move].notna()]
    e = e[(e["refill_5s"] >= FAST) | (e["refill_5s"] < SLOW)]
    slow = (e["refill_5s"] < SLOW).to_numpy()
    y, days = e[move].to_numpy(float), e["day"].to_numpy()
    out = dict(n_fast=int((~slow).sum()), n_slow=int(slow.sum()), days=int(len(set(days))))
    if out["n_fast"] == 0 or out["n_slow"] == 0:
        return dict(out, effect=None, p=None)

    def stat(lab):
        return _day_weighted(y[lab], days[lab]) - _day_weighted(y[~lab], days[~lab])

    obs = stat(slow)
    groups = [np.flatnonzero(days == d) for d in np.unique(days)]
    hits = 0
    for _ in range(perms):
        lab = slow.copy()
        for idx in groups:
            lab[idx] = rng.permutation(lab[idx])
        hits += stat(lab) >= obs
    half_fx = []
    for h in _halves(days):
        m = np.isin(days, h)
        lab, yy, dd = slow[m], y[m], days[m]
        if lab.any() and (~lab).any():
            half_fx.append(_day_weighted(yy[lab], dd[lab]) - _day_weighted(yy[~lab], dd[~lab]))
        else:
            half_fx.append(None)
    return dict(out, effect=round(float(obs), 4), p=(hits + 1) / (perms + 1), halves=half_fx)


def _halves(days) -> tuple[list, list]:
    u = sorted(set(days))
    return u[: len(u) // 2], u[len(u) // 2:]


def _ic(x: np.ndarray, y: np.ndarray) -> float:
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 30:
        return float("nan")
    return float(pd.Series(x[m]).rank().corr(pd.Series(y[m]).rank()))


def imbalance_ic(feats: dict[str, pd.DataFrame], h: int, rng: np.random.Generator, perms: int = PERMS) -> dict:
    """D1-B: mean daily Spearman IC of DI(t) vs midrange(t+h) - midrange(t+1), against circular shifts."""
    per_day = {}
    for day, f in feats.items():
        di = ((f["depth10_bid_mean"] - f["depth10_ask_mean"]) /
              (f["depth10_bid_mean"] + f["depth10_ask_mean"])).to_numpy(float)
        mid = ((f["price_min"] + f["price_max"]) / 2).to_numpy(float)
        fwd = np.full(len(mid), np.nan)
        if len(mid) > h:
            fwd[: len(mid) - h] = mid[h:] - mid[1: len(mid) - h + 1]
        per_day[day] = (di, fwd)
    ics = {d: _ic(*v) for d, v in per_day.items()}
    ics = {d: v for d, v in ics.items() if np.isfinite(v)}
    if not ics:
        return dict(days=0, ic=None, p=None)
    obs = float(np.mean(list(ics.values())))
    hits = 0
    for _ in range(perms):
        null = []
        for d in ics:
            di, fwd = per_day[d]
            null.append(_ic(np.roll(di, int(rng.integers(1, max(2, len(di))))), fwd))
        hits += np.nanmean(null) >= obs
    halves = _halves(list(ics))
    return dict(days=len(ics), ic=round(obs, 5), p=(hits + 1) / (perms + 1),
                halves=[round(float(np.mean([ics[d] for d in h])), 5) if h else None for h in halves])


def load(cache: str) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    evs = []
    for day, p in _day_files(cache, "resilience").items():
        e = pd.read_csv(p)
        if len(e):
            evs.append(e.assign(day=day))
    ev = pd.concat(evs, ignore_index=True) if evs else pd.DataFrame(columns=["day", "levels_swept", "refill_5s"])
    feats = {}
    for day, p in _day_files(cache, "features").items():
        f = pd.read_csv(p, index_col=0)
        need = {"depth10_bid_mean", "depth10_ask_mean", "price_min", "price_max"}
        if need <= set(f.columns):
            feats[day] = f.sort_index()
    return ev, feats


def run(cache: str, seed: int = 20261010, perms: int = PERMS) -> dict:
    rng = np.random.default_rng(seed)
    ev, feats = load(cache)
    out = dict(schema="cl_lab.depth_d1/1", protocol=PROTOCOL, registration="docs/DEPTH_PREREG_D1.md",
               execution_authorized=False, production_decision_authorized=False,
               event_days=int(ev["day"].nunique()) if len(ev) else 0, feature_days=len(feats))
    a = sweep_effect(ev, PRIMARY_MOVE, rng, perms) if len(ev) else dict(effect=None, p=None, n_fast=0, n_slow=0, days=0)
    b = imbalance_ic(feats, PRIMARY_H, rng, perms) if feats else dict(days=0, ic=None, p=None)
    out["secondary"] = dict(
        **{f"D1-A_{m}": sweep_effect(ev, m, rng, perms) for m in SECONDARY_MOVES if len(ev) and m in ev},
        **{f"D1-B_h{h}": imbalance_ic(feats, h, rng, perms) for h in SECONDARY_H if feats})
    enough_a = a["days"] >= MIN_DAYS and a["n_fast"] >= MIN_EVENTS and a["n_slow"] >= MIN_EVENTS
    enough_b = b["days"] >= MIN_DAYS
    raw = {k: v["p"] for k, v in (("D1-A", a), ("D1-B", b)) if v.get("p") is not None}
    adj = _holm(raw) if raw else {}
    for name, res, enough, size in (("D1-A", a, enough_a, a.get("effect")), ("D1-B", b, enough_b, b.get("ic"))):
        if not enough:
            res["status"] = "INSUFFICIENT_DATA"
        elif adj.get(name, 1.0) > ALPHA or not size or size <= 0:
            res["status"] = "REJECTED"
        elif any(h is None or h <= 0 for h in res.get("halves", [])):
            res["status"] = "REJECTED_UNSTABLE"
        elif name == "D1-A" and size <= TICKS_COST:
            res["status"] = "SIGNIFICANT_NOT_TRADEABLE"
        else:
            res["status"] = "D1_CONFIRMED"
        res["p_holm"] = adj.get(name)
    out["D1-A"], out["D1-B"] = a, b
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", action="append", required=True, help="depth cache dir(s) holding NQ MBP-10 days")
    ap.add_argument("--out", required=True)
    ap.add_argument("--perms", type=int, default=PERMS)
    a = ap.parse_args(argv)
    if len(a.cache) == 1:
        res = run(a.cache[0], perms=a.perms)
    else:                                   # merge caches into one view without copying vendor rows anywhere
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as tmp:
            for c in a.cache:
                for kind in ("resilience", "features"):
                    src = os.path.join(c, kind)
                    if os.path.isdir(src):
                        shutil.copytree(src, os.path.join(tmp, kind), dirs_exist_ok=True)
            res = run(tmp, perms=a.perms)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, sort_keys=True, default=str)
        f.write("\n")
    print(json.dumps({k: res[k].get("status") for k in ("D1-A", "D1-B")} | {"days": res["event_days"]}))


if __name__ == "__main__":
    main()
