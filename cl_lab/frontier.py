# CL (Claude, Anthropic) — 2026-10-11 — cl_lab.frontier: FR-1, the win-rate frontier (docs/FRONTIER_PREREG_FR1.md rev. 2)
"""FR-1: for each pre-declared NoiseBoundary entry source, is there one fixed take-profit / stop / time-stop
geometry that meets the owner's targets on TUNE and beats matched random entries, and does it hold on HOLD
and then on FORWARD? Every number here is fixed by the registration; section numbers refer to it.

Causality (§2). The tape is raw (unadjusted). For trading day ``d`` the history is put into day ``d``'s
contract prices with only the roll switches identifiable from data available before day ``d``'s first RTH
bar opens: the raw tape up to that bar and index closes dated before ``d``. A switch shifts every earlier
bar by its delta (Panama, bar level); day ``d``'s own bars are never shifted. Nothing after that moment can
change anything about day ``d``.

Fills (§5): entry at the next bar's open; a target fills only when the bar trades through it by a tick;
a stop fills at its price or at a worse open; a bar that reaches both is the stop; time stop at an open;
end of day at bar 77's close. One position at a time (§3); the matched null obeys the same rule (§6).

Implementation choices the registration leaves open (stated for review, fixed before any data is seen):

- a switch is known for day ``d`` only if it is identifiable from data before ``d``'s first RTH bar, so a
  switch found by the RTH-close basis method applies from the next day; ``instrument_id`` switches, which
  sit in the overnight session, apply the same day;
- a day trades only if all 78 RTH bars exist (``complete``, as in ``NoiseBoundary``): early closes are
  calendar-known, and bar 77 is needed for the end-of-day exit;
- after any exit in bar ``k`` (target, stop, time stop at an open, or end of day) the next check is ``j > k``;
- a null set's free bars are its bucket's bars after its own last exit that day (the real trades are
  replayed in time order, so null positions never overlap);
- FR-1 trial ids carry a per-window data version; the frozen snapshot excludes FR-1's own records.

Nothing here grants execution authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats as sps

from . import bars, costs, extend, integrity, stats, store, trial_ledger
from .sessions import N_SLOTS, RTH_START_MIN, SLOT_MIN

REGISTRATION = dict(id="fr-1", doc="docs/FRONTIER_PREREG_FR1.md", revision=2)
SCHEMA = "cl_lab.frontier/1"
TICK = 0.25
COST = costs.MNQ                 # $2.70 per round turn = 1.35 points
STRESS = costs.MNQ_STRESS        # $5.40 = 2.70 points
SOURCES = {
    "S1": dict(id="005e61b86b3d", check=30, lookback=10, mult=1.0, trail="band_vwap", regime="all"),
    "S2": dict(id="c00aeb927f0b", check=30, lookback=14, mult=1.0, trail="band_vwap", regime="all"),
}
TP_GRID = (0.01, 0.02, 0.035, 0.05, 0.08)
SL_GRID = (0.05, 0.10, 0.20, 0.35)
T_GRID = (60, 120, 240)
TUNE_END = date(2025, 10, 1)                 # TUNE: sessions before this date
HOLD_START, HOLD_END = date(2025, 10, 1), date(2026, 10, 4)
FORWARD_START = date(2026, 10, 12)
N_NULL = 200
BUCKET = 12                                  # RTH hour buckets: slots 0-11, 12-23, ..., 72-77
SELECT = dict(min_wr=0.82, min_trades=100, max_hold=120.0, max_null_p=0.05)
HOLD_GATE = dict(min_trades=30, alpha=0.05, min_wr=0.80, min_wilson=0.72, max_null_p=0.05)
FORWARD_GATE = dict(n=220, min_wr=0.82, wilson_floor=0.75, max_hold=120.0, alpha=0.05)
LAST_BAR = N_SLOTS - 1


def geometries():
    """The 60 registered (tp, sl, T) geometries, in tie-break order (smaller stop, target, time first)."""
    return [dict(tp=tp, sl=sl, T=T) for sl in SL_GRID for tp in TP_GRID for T in T_GRID]


def ticks(distance: float) -> int:
    """Whole 0.25-point ticks, rounded UP, at least 1 (§4). Rounding to 1e-9 ticks first keeps an exact
    multiple (e.g. 1.0 point = 4 ticks) from becoming 5 through float error."""
    if not np.isfinite(distance):
        raise ValueError("distance must be finite")
    return max(1, int(math.ceil(round(distance / TICK, 9))))


def window_of(d: date) -> str | None:
    if d < TUNE_END:
        return "TUNE"
    if HOLD_START <= d <= HOLD_END:
        return "HOLD"
    if d >= FORWARD_START:
        return "FORWARD"
    return None


# --------------------------------------------------------------------------- raw tape and as-of context

@dataclass
class Tape:
    """Raw RTH session arrays plus the annotated raw frame used for causal roll detection."""
    adf: pd.DataFrame
    index_close: pd.Series | None
    dates: np.ndarray
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    P: np.ndarray                    # absolute bar position in ``adf`` of each RTH slot, -1 if missing
    rth_start: np.ndarray            # position of the first RTH bar of each session
    complete: np.ndarray
    cache: dict = field(default_factory=dict, repr=False)

    @property
    def D(self) -> int:
        return len(self.dates)


def build_tape(adf: pd.DataFrame, index_close: pd.Series | None = None) -> Tape:
    """``adf``: :func:`cl_lab.bars.annotate` frame of RAW bars in time order (optional ``instrument_id``)."""
    adf = adf.sort_index()
    rth_mask = adf["rth"].to_numpy(bool)
    pos_all = np.arange(len(adf))
    rth = adf[rth_mask]
    rpos = pos_all[rth_mask]
    dates = np.array(sorted(set(rth["session_date"])), dtype=object)
    di_map = {d: i for i, d in enumerate(dates)}
    D = len(dates)
    O, H, L, C = (np.full((D, N_SLOTS), np.nan) for _ in range(4))
    P = np.full((D, N_SLOTS), -1, dtype=np.int64)
    di = np.fromiter((di_map[d] for d in rth["session_date"]), dtype=np.int64, count=len(rth))
    sj = ((rth["minute_et"].to_numpy() - RTH_START_MIN) // SLOT_MIN).astype(np.int64)
    for arr, col in ((O, "open"), (H, "high"), (L, "low"), (C, "close")):
        arr[di, sj] = rth[col].to_numpy(float)
    P[di, sj] = rpos
    rth_start = np.full(D, -1, dtype=np.int64)
    for k in range(len(rth) - 1, -1, -1):
        rth_start[di[k]] = rpos[k]
    complete = np.isfinite(C).all(axis=1)
    if index_close is not None and len(index_close):
        ix = index_close.dropna()
        index_close = pd.Series(ix.to_numpy(float), index=pd.to_datetime(ix.index).date)
    return Tape(adf=adf, index_close=index_close, dates=dates, O=O, H=H, L=L, C=C, P=P,
                rth_start=rth_start, complete=complete)


def known_switches(tape: Tape, d: int) -> list[tuple[int, float]]:
    """Roll switches identifiable before day ``d``'s first RTH bar: (bar position, delta), sorted."""
    key = ("switches", d)
    if key in tape.cache:
        return tape.cache[key]
    cut = int(tape.rth_start[d])
    head = tape.adf.iloc[:cut]
    ic = None
    if tape.index_close is not None:
        ic = tape.index_close[[x < tape.dates[d] for x in tape.index_close.index]]
    rolls = integrity.detect_rolls(head, ic) if len(head) else []
    out = sorted((int(r["pos"]), float(r["delta"])) for r in rolls
                 if r.get("status") == "DETECTED" and r.get("pos") is not None and int(r["pos"]) <= cut)
    tape.cache[key] = out
    return out


def _shift(tape: Tape, rows: np.ndarray, sw: list[tuple[int, float]]) -> np.ndarray:
    """Panama shift of the RTH bars of sessions ``rows`` given switches ``sw``: bars before a switch move by
    its delta."""
    if not sw or len(rows) == 0:
        return np.zeros((len(rows), N_SLOTS))
    pos = np.array([p for p, _ in sw], dtype=np.int64)
    dl = np.array([x for _, x in sw], dtype=float)
    P = tape.P[rows]
    return ((P[:, :, None] >= 0) & (P[:, :, None] < pos[None, None, :])).astype(float) @ dl


def _last_finite(row: np.ndarray) -> float:
    f = np.flatnonzero(np.isfinite(row))
    return float(row[f[-1]]) if len(f) else math.nan


@dataclass
class Context:
    prev_close: np.ndarray           # D
    atr14: np.ndarray                # D
    sigma: dict                      # lookback -> D x 78
    switches_known: np.ndarray       # D: number of switches known before each day


def build_context(tape: Tape, lookbacks=(10, 14)) -> Context:
    """As-of ``prev_close``, ``atr14`` and the noise sigma for every day (§2, §3)."""
    D = tape.D
    pc = np.full(D, np.nan)
    atr = np.full(D, np.nan)
    sig = {lb: np.full((D, N_SLOTS), np.nan) for lb in lookbacks}
    nsw = np.zeros(D, dtype=np.int64)
    comp = np.flatnonzero(tape.complete)
    for d in range(D):
        if d == 0:
            continue
        sw = known_switches(tape, d)
        nsw[d] = len(sw)
        lo = max(0, d - 15)
        rows = np.arange(lo, d)
        sh = _shift(tape, rows, sw)
        H = tape.H[rows] + sh
        L = tape.L[rows] + sh
        C = tape.C[rows] + sh
        last = np.array([_last_finite(r) for r in C])
        pc[d] = last[-1]
        if d >= 14:
            hi, lw = np.nanmax(H, axis=1), np.nanmin(L, axis=1)
            prev = np.r_[np.nan, last[:-1]]
            tr = np.maximum(hi, prev) - np.minimum(lw, prev)
            if lo == 0:
                tr[0] = hi[0] - lw[0]                    # the tape's first session: high minus low
            w = tr[-14:]
            if len(w) == 14 and np.isfinite(w).all():
                atr[d] = float(w.mean())
        if not tape.complete[d]:
            continue
        i = int(np.searchsorted(comp, d))               # number of complete sessions strictly before d
        for lb in lookbacks:
            if i < lb:
                continue
            crow = comp[i - lb:i]
            sh2 = _shift(tape, crow, sw)
            Cs = tape.C[crow] + sh2
            O0 = tape.O[crow, 0] + sh2[:, 0]
            with np.errstate(invalid="ignore", divide="ignore"):
                sig[lb][d] = np.abs(Cs / O0[:, None] - 1.0).mean(axis=0)
    return Context(prev_close=pc, atr14=atr, sigma=sig, switches_known=nsw)


def check_bars(check: int) -> list[int]:
    return [j for j in range(5, LAST_BAR) if ((j + 1) * 5) % check == 0]


def signals(tape: Tape, ctx: Context, src: dict) -> np.ndarray:
    """D x 78 int8 raw NoiseBoundary signal at the check bars (§3); 0 elsewhere and on ineligible days."""
    sig = ctx.sigma[src["lookback"]]
    out = np.zeros((tape.D, N_SLOTS), dtype=np.int8)
    ok = tape.complete & np.isfinite(ctx.prev_close) & np.isfinite(ctx.atr14) & np.isfinite(sig[:, 0])
    js = np.array(check_bars(src["check"]))
    for d in np.flatnonzero(ok):
        o0, p = tape.O[d, 0], ctx.prev_close[d]
        up = max(o0, p) * (1.0 + src["mult"] * sig[d, js])
        dn = min(o0, p) * (1.0 - src["mult"] * sig[d, js])
        c = tape.C[d, js]
        out[d, js] = np.where(c > up, 1, np.where(c < dn, -1, 0))
    return out


# --------------------------------------------------------------------------- fills (§5)

def simulate(tape: Tape, d, e, dirn, tp_t, sl_t, nb):
    """Vectorised bracket exits. All arguments are equal-length arrays. Returns a dict of arrays:
    entry, exit, k (exit bar), reason (0 target, 1 stop, 2 time, 3 eod), hold (minutes), gross (points)."""
    d = np.asarray(d, dtype=np.int64)
    e = np.asarray(e, dtype=np.int64)
    dirn = np.asarray(dirn, dtype=np.int64)
    tp_t = np.asarray(tp_t, dtype=np.int64)
    sl_t = np.asarray(sl_t, dtype=np.int64)
    nb = np.asarray(nb, dtype=np.int64)
    M = len(d)
    if M == 0:
        z = np.zeros(0)
        return dict(entry=z, exit=z, k=z.astype(np.int64), reason=z.astype(np.int64), hold=z, gross=z)
    O, H, L, C = tape.O[d], tape.H[d], tape.L[d], tape.C[d]
    rows = np.arange(M)
    entry = O[rows, e]
    tp_px = entry + dirn * tp_t * TICK
    sl_px = entry - dirn * sl_t * TICK
    last = np.minimum(e + nb - 1, LAST_BAR)
    bars_ = np.arange(N_SLOTS)[None, :]
    active = (bars_ >= e[:, None]) & (bars_ <= last[:, None])
    lng = (dirn == 1)[:, None]
    stop_hit = active & np.where(lng, L <= sl_px[:, None], H >= sl_px[:, None])
    tgt_hit = active & np.where(lng, H >= tp_px[:, None] + TICK, L <= tp_px[:, None] - TICK)
    big = N_SLOTS + 10
    ks = np.where(stop_hit.any(axis=1), stop_hit.argmax(axis=1), big)
    kt = np.where(tgt_hit.any(axis=1), tgt_hit.argmax(axis=1), big)
    is_stop = ks <= kt                                  # a bar that reaches both is the stop
    k_in = np.minimum(ks, kt)
    in_bar = k_in < big
    k = np.where(in_bar, k_in, 0)
    o_k = O[rows, np.minimum(k, LAST_BAR)]
    stop_fill = np.where(dirn == 1, np.minimum(o_k, sl_px), np.maximum(o_k, sl_px))
    ts_bar = e + nb
    timed = ~in_bar & (ts_bar <= LAST_BAR)
    eod = ~in_bar & ~timed
    exit_px = np.where(in_bar, np.where(is_stop, stop_fill, tp_px),
                       np.where(timed, O[rows, np.minimum(ts_bar, LAST_BAR)], C[:, LAST_BAR]))
    k_out = np.where(in_bar, k, np.where(timed, ts_bar, LAST_BAR))
    reason = np.where(in_bar, np.where(is_stop, 1, 0), np.where(timed, 2, 3))
    hold = np.where(in_bar, 5 * (k_out - e + 1), np.where(timed, 5 * nb, 5 * (N_SLOTS - e))).astype(float)
    return dict(entry=entry, exit=exit_px, k=k_out.astype(np.int64), reason=reason.astype(np.int64), hold=hold,
                gross=dirn * (exit_px - entry))


def _geom_ticks(ctx: Context, d: np.ndarray, g: dict):
    atr = ctx.atr14[d]
    tp = np.array([ticks(g["tp"] * a) for a in atr], dtype=np.int64)
    sl = np.array([ticks(g["sl"] * a) for a in atr], dtype=np.int64)
    return tp, sl


def real_trades(tape: Tape, ctx: Context, sig: np.ndarray, g: dict) -> dict:
    """One position at a time (§3): enter at the open after a ±1 check; ignore every signal while open;
    after an exit in bar k the next eligible check is the first j > k."""
    nb_all = g["T"] // 5
    checks = {}
    for d in np.flatnonzero((sig != 0).any(axis=1)):
        js = np.flatnonzero(sig[d])
        checks[int(d)] = (js, sig[d, js])
    nxt = {d: 0 for d in checks}
    out = {k: [] for k in ("d", "e", "dir")}
    res = {k: [] for k in ("entry", "exit", "k", "reason", "hold", "gross")}
    active = sorted(checks)
    while active:
        ds, es, dirs = [], [], []
        for d in active:
            js, sv = checks[d]
            i = int(np.searchsorted(js, nxt[d]))
            if i < len(js) and js[i] + 1 <= LAST_BAR:
                ds.append(d)
                es.append(int(js[i]) + 1)
                dirs.append(int(sv[i]))
        if not ds:
            break
        da = np.array(ds, dtype=np.int64)
        tp, sl = _geom_ticks(ctx, da, g)
        r = simulate(tape, da, np.array(es), np.array(dirs), tp, sl, np.full(len(ds), nb_all))
        for d, k in zip(ds, r["k"]):
            nxt[d] = int(k) + 1
        out["d"] += ds
        out["e"] += es
        out["dir"] += dirs
        for key in res:
            res[key].append(r[key])
        active = ds
    t = {k: np.array(v, dtype=np.int64) for k, v in out.items()}
    t.update({k: (np.concatenate(v) if v else np.zeros(0)) for k, v in res.items()})
    order = np.lexsort((t["e"], t["d"]))
    return {k: v[order] for k, v in t.items()}


# --------------------------------------------------------------------------- matched random-entry null (§6)

def null_seed(source_id: str, g: dict, s: int) -> int:
    key = json.dumps(["fr-1", source_id, [g["tp"], g["sl"], g["T"]], int(s)], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")


def null_trades(tape: Tape, ctx: Context, real: dict, g: dict, source_id: str, n_sets: int = N_NULL) -> dict:
    """``n_sets`` independent null sets replaying the real trades in time order. For real trade i on day d
    in hour bucket h, each set draws an entry bar uniformly from the day's bucket-h bars after its own last
    exit that day (one position at a time, so a bar is never drawn twice), and a direction uniformly. Two
    uniforms per real trade are always consumed, so truncating the tape changes no earlier draw.
    Returns arrays of shape (n_sets, N): taken (bool), net (base-cost points), hold (minutes), entry bar."""
    N = len(real["d"])
    nb = g["T"] // 5
    taken = np.zeros((n_sets, N), dtype=bool)
    net = np.full((n_sets, N), np.nan)
    hold = np.full((n_sets, N), np.nan)
    ebar = np.full((n_sets, N), -1, dtype=np.int64)
    kbar = np.full((n_sets, N), -1, dtype=np.int64)
    if N == 0:
        return dict(taken=taken, net=net, hold=hold, e=ebar, k=kbar)
    U = np.stack([np.random.Generator(np.random.PCG64(null_seed(source_id, g, s))).random((N, 2))
                  for s in range(n_sets)])
    d_all = real["d"]
    grp = np.r_[0, np.cumsum(d_all[1:] != d_all[:-1])]          # day group of each real trade
    rank = np.zeros(N, dtype=np.int64)
    for i in range(1, N):
        rank[i] = rank[i - 1] + 1 if grp[i] == grp[i - 1] else 0
    last_exit = np.full((n_sets, int(grp[-1]) + 1), -1, dtype=np.int64)
    tp_all, sl_all = _geom_ticks(ctx, d_all, g)
    for r in range(int(rank.max()) + 1):
        idx = np.flatnonzero(rank == r)
        lo_b = (real["e"][idx] // BUCKET) * BUCKET
        hi_b = np.minimum(lo_b + BUCKET - 1, LAST_BAR)
        lo = np.maximum(lo_b[None, :], last_exit[:, grp[idx]] + 1)
        n_free = hi_b[None, :] - lo + 1
        bar = lo + np.floor(U[:, idx, 0] * np.maximum(n_free, 1)).astype(np.int64)
        dirn = np.where(U[:, idx, 1] < 0.5, 1, -1)
        si, ti = np.nonzero(n_free >= 1)
        if len(si) == 0:
            continue
        tr = idx[ti]
        res = simulate(tape, d_all[tr], bar[si, ti], dirn[si, ti], tp_all[tr], sl_all[tr], np.full(len(tr), nb))
        taken[si, tr] = True
        net[si, tr] = res["gross"] - COST.round_trip_points
        hold[si, tr] = res["hold"]
        ebar[si, tr] = bar[si, ti]
        kbar[si, tr] = res["k"]
        last_exit[si, grp[tr]] = res["k"]
    return dict(taken=taken, net=net, hold=hold, e=ebar, k=kbar)


def null_p(real_exp: float, null_exps: np.ndarray) -> tuple[float, int]:
    """(b + 1) / (N + 1), b = null sets with expectancy >= the real one; ties and empty sets count against."""
    ne = np.asarray(null_exps, dtype=float)
    b = int(np.sum(~np.isfinite(ne) | (ne >= real_exp))) if np.isfinite(real_exp) else len(ne)
    return (b + 1) / (len(ne) + 1), b


# --------------------------------------------------------------------------- statistics (§6)

def wilson_lower(wins: int, n: int, z: float) -> float:
    if n == 0:
        return math.nan
    p = wins / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - adj) / den


def _streaks(win: np.ndarray) -> tuple[int, int]:
    best = {True: 0, False: 0}
    cur, prev = 0, None
    for w in win.tolist():
        cur = cur + 1 if w == prev else 1
        prev = w
        best[w] = max(best[w], cur)
    return best[True], best[False]


def window_days(tape: Tape, win: str, through: date | None = None) -> np.ndarray:
    return np.array([i for i, d in enumerate(tape.dates) if window_of(d) == win and (through is None or d <= through)],
                    dtype=np.int64)


def trade_stats(tape: Tape, real: dict, mask: np.ndarray, days: np.ndarray) -> dict:
    gross = real["gross"][mask]
    n = int(mask.sum())
    net = gross - COST.round_trip_points
    net_s = gross - STRESS.round_trip_points
    win = net > 0
    daily = np.zeros(len(days))
    pos = {int(d): i for i, d in enumerate(days)}
    for d, x in zip(real["d"][mask], net):
        daily[pos[int(d)]] += x
    nw = stats.newey_west_t(daily) if len(days) >= 2 else dict(t=math.nan, p_one_greater=math.nan, lags=0)
    hold = real["hold"][mask]
    ws, ls = _streaks(win) if n else (0, 0)
    pv = COST.point_value
    return dict(
        trades=n, wins=int(win.sum()), trade_days=int(len(set(real["d"][mask].tolist()))), sessions=int(len(days)),
        win_rate=(float(win.mean()) if n else math.nan),
        wilson95_lower=wilson_lower(int(win.sum()), n, 1.96),
        exp_points=(float(net.mean()) if n else math.nan), exp_points_stress=(float(net_s.mean()) if n else math.nan),
        exp_usd=(float(net.mean()) * pv if n else math.nan), exp_usd_stress=(float(net_s.mean()) * pv if n else math.nan),
        net_usd=float(net.sum()) * pv, net_usd_stress=float(net_s.sum()) * pv,
        hold_mean=(float(hold.mean()) if n else math.nan), hold_median=(float(np.median(hold)) if n else math.nan),
        win_streak=ws, loss_streak=ls, nw_t=nw["t"], nw_p=nw["p_one_greater"], nw_lags=nw["lags"],
        reasons={name: int(np.sum(real["reason"][mask] == code))
                 for code, name in enumerate(("target", "stop", "time", "eod"))},
        daily=daily,
    )


def _null_summary(nul: dict, mask: np.ndarray, real_exp: float) -> dict:
    taken = nul["taken"][:, mask]
    net = nul["net"][:, mask]
    with np.errstate(invalid="ignore"):
        counts = taken.sum(axis=1)
        exps = np.where(counts > 0, np.nansum(np.where(taken, net, 0.0), axis=1) / np.maximum(counts, 1), np.nan)
    p, b = null_p(real_exp, exps)
    return dict(p=p, b=int(b), sets=int(len(exps)), b_over_n=b / len(exps) if len(exps) else math.nan,
                skipped=int((~taken).sum()), null_exp_mean=float(np.nanmean(exps)) if np.isfinite(exps).any() else math.nan)


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items() if k != "daily"}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else round(float(x), 6)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


# --------------------------------------------------------------------------- data versions and trials (§8)

def data_version(tape: Tape, win: str, through: date | None = None) -> str:
    """Bind every causal input through the window's last session, including earlier context.

    Future extensions cannot change an earlier window's identity. The prefix includes overnight
    prices, timestamps, contract identities and prior index closes used by roll detection, as well
    as earlier RTH history used by ATR and bands. Volume does not enter FR-1.
    """
    days = window_days(tape, win, through)
    h = hashlib.sha256(("fr1-causal-inputs-v2|" + integrity.DATA_VERSION + "|" + win).encode())
    if not len(days):
        return h.hexdigest()
    last = int(days[-1])
    for arr in (tape.O, tape.H, tape.L, tape.C):
        h.update(np.ascontiguousarray(arr[:last + 1], dtype="<f8").tobytes())
    h.update(json.dumps([str(d) for d in tape.dates[:last + 1]]).encode())
    positions = tape.P[last][tape.P[last] >= 0]
    if len(tape.adf) and len(positions):
        raw = tape.adf.iloc[:int(positions.max()) + 1]
        cols = ["open", "high", "low", "close", "instrument_id"]
        frame = raw.reindex(columns=cols).apply(pd.to_numeric, errors="coerce").astype(float)
        h.update(pd.util.hash_pandas_object(frame, index=True).to_numpy(dtype="<u8").tobytes())
    if tape.index_close is not None:
        ix = tape.index_close[[d < tape.dates[last] for d in tape.index_close.index]]
        h.update(json.dumps([(str(d), float(v)) for d, v in ix.items()], separators=(",", ":")).encode())
    return h.hexdigest()


def fr1_trial(source_id: str, g: dict | None, dv: str, kind: str) -> dict:
    geom = [g["tp"], g["sl"], g["T"]] if g else None
    tid = hashlib.sha256(json.dumps(["fr-1", source_id, geom, dv, kind], separators=(",", ":")).encode()).hexdigest()
    return dict(trial_id=f"fr-1:{tid}", source="fr-1", source_path=REGISTRATION["doc"],
                row_sha256=trial_ledger.row_sha256(dict(source_id=source_id, geometry=geom, data_version=dv, kind=kind)))


# --------------------------------------------------------------------------- decision rules (§7)

def _eligible(st: dict) -> bool:
    return (st["trades"] >= SELECT["min_trades"] and st["win_rate"] >= SELECT["min_wr"] and st["exp_points"] > 0
            and st["hold_mean"] <= SELECT["max_hold"] and st["null"]["p"] <= SELECT["max_null_p"])


def evaluate(tape: Tape, snapshot: dict, n_sets: int = N_NULL, sources: dict | None = None) -> dict:
    """Run FR-1 on a built tape. ``snapshot`` is the frozen trial-ledger snapshot (§8)."""
    mixed = mixed_contract_sessions(tape)
    if mixed:
        raise ValueError("mixed-contract RTH dataset: " + ", ".join(mixed))
    sources = sources or SOURCES
    ctx = build_context(tape, tuple(sorted({s.get("lookback", 10) for s in sources.values()})))
    tune_days, hold_days = window_days(tape, "TUNE"), window_days(tape, "HOLD")
    fwd_days = window_days(tape, "FORWARD")
    win_of_day = np.array([window_of(d) or "" for d in tape.dates], dtype=object)
    out = dict(sources={}, trials=[])
    dv = {w: data_version(tape, w) for w in ("TUNE", "HOLD")}
    tune_sr = []
    for name, src in sources.items():
        if "signals" in src:                 # test hook: a pre-computed signal array (only on eligible days)
            sig = np.where((tape.complete & np.isfinite(ctx.prev_close) & np.isfinite(ctx.atr14))[:, None],
                           np.asarray(src["signals"], dtype=np.int8), 0).astype(np.int8)
            src = {k: v for k, v in src.items() if k != "signals"}
        else:
            sig = signals(tape, ctx, src)
        rows = []
        for g in geometries():
            real = real_trades(tape, ctx, sig, g)
            m_tune = win_of_day[real["d"]] == "TUNE" if len(real["d"]) else np.zeros(0, bool)
            st = trade_stats(tape, real, m_tune, tune_days)
            nul = null_trades(tape, ctx, real, g, src["id"], n_sets)
            st["null"] = _null_summary(nul, m_tune, st["exp_points"])
            st["geometry"] = g
            st["eligible"] = bool(_eligible(st)) if st["trades"] else False
            daily = st["daily"]
            sd = daily.std(ddof=1) if len(daily) > 1 else math.nan
            tune_sr.append(daily.mean() / sd if sd and np.isfinite(sd) and sd > 0 else math.nan)
            rows.append((st, real, nul))
            out["trials"].append(fr1_trial(src["id"], g, dv["TUNE"], "tune"))
        elig = [r for r in rows if r[0]["eligible"]]
        res = dict(source=src, tune=[_clean(r[0]) for r in rows], eligible=len(elig))
        if not elig:
            res["status"] = "NO_REGION"
            out["sources"][name] = res
            continue
        def rank_key(x):
            t = x[1][0]["nw_t"]
            return (t if np.isfinite(t) else -math.inf, -x[0])     # ties: earlier = smaller stop, target, time
        best = max(enumerate(elig), key=rank_key)[1]
        st, real, nul = best
        g = st["geometry"]
        m_hold = win_of_day[real["d"]] == "HOLD"
        hs = trade_stats(tape, real, m_hold, hold_days)
        hs["null"] = _null_summary(nul, m_hold, hs["exp_points"])
        res.update(selected=g, selected_tune=_clean(st), hold=hs, _real=real, _daily_tune=st["daily"])
        out["trials"].append(fr1_trial(src["id"], g, dv["HOLD"], "hold"))
        out["sources"][name] = res
    # HOLD: Holm across the sources that reached HOLD (§7)
    reached = [n for n, r in out["sources"].items() if "hold" in r]
    if reached:
        # All reached sources belong to the registered family, including those with invalid tests.
        pvals = [out["sources"][n]["hold"]["nw_p"] for n in reached]
        holm = stats.holm([p if np.isfinite(p) else 1.0 for p in pvals], HOLD_GATE["alpha"])
        for n, padj in zip(reached, holm.p_adjusted.tolist()):
            hs = out["sources"][n]["hold"]
            hs["holm_p"] = padj
            gates = dict(
                trades=hs["trades"] >= HOLD_GATE["min_trades"],
                nw_holm=bool(np.isfinite(padj) and padj <= HOLD_GATE["alpha"]),
                win_rate=hs["win_rate"] >= HOLD_GATE["min_wr"],
                wilson=hs["wilson95_lower"] >= HOLD_GATE["min_wilson"],
                null=hs["null"]["p"] <= HOLD_GATE["max_null_p"],
                stress=hs["exp_points_stress"] > 0,
            )
            hs["gates"] = gates
            out["sources"][n]["status"] = "HOLD_CONFIRMED" if all(gates.values()) else "REJECTED"
    # deflated Sharpe of each selected configuration, with the frozen snapshot's trial count (§8)
    finite = [x for x in tune_sr if np.isfinite(x)]
    var_sr = float(np.var(finite, ddof=1)) if len(finite) > 1 else math.nan
    n_trials = int(snapshot.get("total", 0)) + len(geometries()) * len(sources)
    for n in reached:
        r = out["sources"][n]
        r["dsr_tune"] = stats.dsr(r["_daily_tune"], n_trials, var_sr) if np.isfinite(var_sr) else None
    # FORWARD (§7): one evaluation at the first session close where the forward count reaches 220
    confirmed = [n for n, r in out["sources"].items() if r.get("status") == "HOLD_CONFIRMED"]
    k = len(confirmed)
    for n in confirmed:
        r = out["sources"][n]
        real = r["_real"]
        m_fwd = win_of_day[real["d"]] == "FORWARD"
        fd = real["d"][m_fwd]
        r["forward"] = forward_evaluation(tape, real, m_fwd, fd, fwd_days, k)
        if r["forward"]["status"] != "FORWARD_PENDING":
            out["trials"].append(fr1_trial(r["source"]["id"], r["selected"], r["forward"]["data_version"], "forward"))
    for r in out["sources"].values():
        r.pop("_real", None)
        r.pop("_daily_tune", None)
        if "hold" in r:
            r["hold"] = _clean(r["hold"])
    out.update(var_sr_tune=var_sr, n_trials_dsr=n_trials, k_forward=k)
    return out


def forward_evaluation(tape: Tape, real: dict, m_fwd: np.ndarray, fd: np.ndarray, fwd_days: np.ndarray, k: int) -> dict:
    n_all = int(m_fwd.sum())
    if n_all < FORWARD_GATE["n"]:
        interim = trade_stats(tape, real, m_fwd, fwd_days) if len(fwd_days) else None
        return dict(status="FORWARD_PENDING", trades=n_all, needed=FORWARD_GATE["n"],
                    interim=_clean(interim) if interim else None, note="interim numbers decide nothing")
    order = np.sort(fd)
    eval_day = int(order[FORWARD_GATE["n"] - 1])            # the session whose close reaches 220
    through = tape.dates[eval_day]
    mask = m_fwd & (real["d"] <= eval_day)
    days = window_days(tape, "FORWARD", through)
    st = trade_stats(tape, real, mask, days)
    alpha = FORWARD_GATE["alpha"] / max(k, 1)
    z = float(sps.norm.ppf(1 - alpha))
    wl = wilson_lower(st["wins"], st["trades"], z)
    gates = dict(nw=bool(np.isfinite(st["nw_p"]) and st["nw_p"] <= alpha), wilson=wl > FORWARD_GATE["wilson_floor"],
                 stress=st["exp_points_stress"] > 0)
    target = dict(win_rate=st["win_rate"] >= FORWARD_GATE["min_wr"], hold=st["hold_mean"] <= FORWARD_GATE["max_hold"])
    if all(gates.values()) and all(target.values()):
        status = "TARGET_QUALIFIED"
    elif all(gates.values()):
        status = "FORWARD_PASS_BELOW_TARGET"
    else:
        status = "FORWARD_REJECTED"
    return dict(status=status, evaluated_through=str(through), alpha=alpha, wilson_one_sided_lower=wl,
                gates=gates, target=target, stats=_clean(st), data_version=data_version(tape, "FORWARD", through))


# --------------------------------------------------------------------------- the real run

def mixed_contract_sessions(tape: Tape) -> list[str]:
    """Reject the whole dataset when a detected switch lies in an RTH session.

    Reporting after evaluation would allow an old-contract entry to fill against a new-contract
    print. A switch on the first RTH bar also leaves the pre-session context in the old
    contract basis, so that boundary is blocked too. No retrospective session mask or
    repaired fill/context is introduced here.
    """
    if tape.adf.empty:
        return []
    return sorted({str(r["session"]) for r in integrity.detect_rolls(tape.adf, tape.index_close)
                   if r.get("status") == "DETECTED" and r.get("pos") is not None
                   and bool(tape.adf["rth"].iloc[int(r["pos"])])})


def load_raw_mnq(cache_dir: str, csv_path: str = "data/mnq_5m_full.csv") -> tuple[pd.DataFrame, pd.Series | None, dict]:
    """The committed MNQ 5m tape extended by the cached Databento corpus, RAW (never back-adjusted), with
    the corpus ``instrument_id`` kept on the extension rows so cl-data-3 exact switches apply there."""
    base = bars.load_csv(csv_path)
    p = os.path.join(cache_dir, "databento_mnq_5m.csv.gz")
    ext = store.load_frame(p) if os.path.exists(p) else None
    df, prov = extend.splice(base, ext)
    if ext is not None and "instrument_id" in ext.columns:
        df = df.copy()
        df["instrument_id"] = pd.to_numeric(ext["instrument_id"], errors="coerce").reindex(df.index)
        df.loc[df.index <= base.index[-1], "instrument_id"] = np.nan
    ip = os.path.join(cache_dir, "fred_nasdaq100.csv.gz")
    ix = None
    if os.path.exists(ip):
        f = store.load_frame(ip, intraday=False)
        ix = f["NASDAQ100"].dropna() if "NASDAQ100" in f else None
    return bars.annotate(df), ix, dict(prov, sha256=store.sha256_frame(df[list(bars.COLUMNS)]))


def run(cache_dir: str, out_path: str, ledger_path: str = trial_ledger.LEDGER, root: str = ".",
        snapshot_path: str = "automation_intelligence/research/fr1_snapshot.json", n_sets: int = N_NULL) -> dict:
    try:
        with trial_ledger.run_lock(ledger_path):
            return _run_locked(cache_dir, out_path, ledger_path, root, snapshot_path, n_sets)
    except trial_ledger.SourceError as ex:
        base = dict(schema=SCHEMA, registration=REGISTRATION, execution_authorized=False,
                    production_decision_authorized=False)
        out = dict(base, status="BLOCKED", blockers=[str(ex)])
        _write(out_path, out)
        return out


def _run_locked(cache_dir: str, out_path: str, ledger_path: str, root: str,
                snapshot_path: str, n_sets: int) -> dict:
    base = dict(schema=SCHEMA, registration=REGISTRATION, execution_authorized=False,
                production_decision_authorized=False)
    # Read-only source validation preserves fail-before-loader behavior for missing history.
    try:
        _, checks = trial_ledger.historical_trials(root)
        bad = trial_ledger.blockers(checks)
    except (trial_ledger.SourceError, KeyError, TypeError, ValueError, OSError, AttributeError) as ex:
        checks, bad = None, [str(ex)]
    if bad:
        out = dict(base, status="BLOCKED", blockers=bad,
                   ledger_import=dict(status="BLOCKED", added=0, checks=checks, blockers=bad))
        _write(out_path, out)
        return out
    adf, ix, prov = load_raw_mnq(cache_dir)
    tape = build_tape(adf, ix)
    mixed = mixed_contract_sessions(tape)
    if mixed:
        out = dict(base, status="BLOCKED", blockers=["mixed-contract RTH dataset: " + ", ".join(mixed)])
        _write(out_path, out)
        return out
    snap = None
    if os.path.exists(snapshot_path):
        try:
            with open(snapshot_path, encoding="utf-8") as fh:
                snap = json.load(fh)
            if not isinstance(snap, dict) or snap.get("registration") != REGISTRATION:
                raise ValueError("frozen snapshot has an incompatible registration")
        except (OSError, ValueError) as ex:
            out = dict(base, status="BLOCKED", blockers=[str(ex)])
            _write(out_path, out)
            return out
    imp = trial_ledger.import_historical(root, ledger_path, frozen_snapshot=snap)
    if imp["status"] != "OK":
        out = dict(base, status="BLOCKED", blockers=imp["blockers"], ledger_import=imp)
        _write(out_path, out)
        return out
    if snap is None:
        snap = trial_ledger.snapshot(ledger_path, exclude_sources=("fr-1",))
        _write(snapshot_path, dict(snap, registration=REGISTRATION))
    res = evaluate(tape, snap, n_sets=n_sets)
    added = trial_ledger.append(ledger_path, res.pop("trials"))
    rolls = integrity.detect_rolls(adf, ix)
    rth_switch = []                       # switches inside an RTH session: that day traded on mixed contracts
    starts = set(int(x) for x in tape.rth_start)
    for r in rolls:
        p = r.get("pos")
        if r.get("status") == "DETECTED" and p is not None and bool(adf["rth"].iloc[int(p)]) and int(p) not in starts:
            rth_switch.append(r.get("session"))
    out = dict(base, status="EVALUATED", snapshot=snap, ledger_import=dict(imp, checks=imp["checks"]),
               fr1_trials_added=added, tape=prov, rolls=integrity.summary(rolls), rth_switch_sessions=rth_switch,
               windows=dict(TUNE=f"< {TUNE_END}", HOLD=f"{HOLD_START}..{HOLD_END}", FORWARD=f">= {FORWARD_START}"),
               **_clean(res))
    _write(out_path, out)
    return out


def _write(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True, default=str)
        fh.write("\n")
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FR-1 win-rate frontier (docs/FRONTIER_PREREG_FR1.md)")
    ap.add_argument("--cache", default=".cl_cache")
    ap.add_argument("--out", default="automation_intelligence/cl_lab/frontier_latest.json")
    ap.add_argument("--ledger", default=trial_ledger.LEDGER)
    a = ap.parse_args(argv)
    res = run(a.cache, a.out, a.ledger)
    print(json.dumps({k: res.get(k) for k in ("status", "fr1_trials_added")}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
