# CL (Claude, Anthropic) — 2026-10-05 — cl_lab.depth_resilience: liquidity replenishment after touch-clearing trades (R7-E08)
"""Event-level book resilience from Databento MBP-10 records, computed while the raw file still exists
(the raw DBN is deleted after reduction, so anything not computed here can never be recomputed).

An EVENT is one aggressive order: consecutive trade records (action T) with the same ``ts_event`` and
aggressor side (B = buyer lifted the ask, A = seller hit the bid). It is kept when it CLEARED the touch:
traded size >= the resting size at the best price on the side it hit. Measured per event, all in ticks
of ``tick`` and signed so that positive = in the aggressor's direction:

- pre-event book (the last record flagged F_LAST before the first trade): spread, touch size, top-5 depth;
- ``levels_swept``: price levels traded through (1 = only the touch, >= 2 = a sweep);
- post-event book, starting at the record flagged F_LAST that closes the event (the book after the event):
  swept-side top-5 depth relative to before at +1 s / +5 s / +30 s, milliseconds until that depth is back
  to 100 % and until the spread is back to its pre-event width (censored at 60 s), and the mid-price move
  from the pre-event mid at +5 s / +30 s / +60 s / +300 s.

Horizons that run past the end of the file are left empty (NaN), never filled. Only derived numbers are
returned; no order-book rows are kept."""
from __future__ import annotations

import numpy as np
import pandas as pd

UNDEF_PRICE = (1 << 63) - 1
F_LAST = 0x80
NS = 1_000_000_000
REFILL_H = (1, 5, 30)                  # seconds
MOVE_H = (5, 30, 60, 300)              # seconds
CENSOR_MS = 60_000
COLUMNS = ("ts", "dir", "levels_swept", "traded", "n_trades", "pre_spread", "pre_touch", "pre_d5", "pre_d5_opp",
           *[f"refill_{h}s" for h in REFILL_H], "t_refill_ms", "t_spread_ms", *[f"move_{h}s" for h in MOVE_H])


def _compact(store, chunk: int) -> dict[str, np.ndarray]:
    """Columns needed for the measurement, chunk by chunk (an MBP-10 day does not fit in memory whole)."""
    keys = ("ts", "te", "act", "side", "px", "sz", "flags", "bp", "ap", "bs", "as_", "bd5", "ad5")
    parts = {k: [] for k in keys}
    it = store.to_ndarray(count=chunk)
    for a in (it if not isinstance(it, np.ndarray) else [it]):
        if a is None or not len(a):
            continue
        parts["ts"].append(a["ts_recv"].astype(np.int64))
        parts["te"].append(a["ts_event"].astype(np.int64))
        parts["act"].append(a["action"].copy())
        parts["side"].append(a["side"].copy())
        parts["px"].append(a["price"].astype(np.int64))
        parts["sz"].append(a["size"].astype(np.int64))
        parts["flags"].append(a["flags"].astype(np.int64))
        parts["bp"].append(a["bid_px_00"].astype(np.int64))
        parts["ap"].append(a["ask_px_00"].astype(np.int64))
        parts["bs"].append(a["bid_sz_00"].astype(np.int64))
        parts["as_"].append(a["ask_sz_00"].astype(np.int64))
        parts["bd5"].append(sum(a[f"bid_sz_0{i}"].astype(np.int64) for i in range(5)))
        parts["ad5"].append(sum(a[f"ask_sz_0{i}"].astype(np.int64) for i in range(5)))
    if not parts["ts"]:
        return {}
    return {k: np.concatenate(v) for k, v in parts.items()}


def events(store, tick: float = 0.25, chunk: int = 500_000) -> pd.DataFrame:
    c = _compact(store, chunk)
    if not c or len(c["ts"]) < 3:
        return pd.DataFrame(columns=COLUMNS)
    ts, te, px, sz = c["ts"], c["te"], c["px"], c["sz"]
    bp, ap = c["bp"].astype(float), c["ap"].astype(float)
    bad = (c["bp"] == UNDEF_PRICE) | (c["ap"] == UNDEF_PRICE) | (c["ap"] < c["bp"])
    bp[bad] = np.nan
    ap[bad] = np.nan
    mid, spread = (bp + ap) / 2.0, ap - bp
    tick_ns = tick * NS
    sd = np.where(c["side"] == b"B", 1, np.where(c["side"] == b"A", -1, 0))
    it = np.flatnonzero((c["act"] == b"T") & (sd != 0))
    if len(it) == 0:
        return pd.DataFrame(columns=COLUMNS)
    te_t, sd_t = te[it], sd[it]
    new = np.r_[True, (te_t[1:] != te_t[:-1]) | (sd_t[1:] != sd_t[:-1])]
    starts = np.flatnonzero(new)
    first, last = it[starts], it[np.r_[starts[1:] - 1, len(it) - 1]]
    traded = np.add.reduceat(sz[it], starts)
    hi = np.maximum.reduceat(px[it], starts)
    lo = np.minimum.reduceat(px[it], starts)
    n_tr = np.diff(np.r_[starts, len(it)])
    dirs = sd[first]
    flag_idx = np.flatnonzero((c["flags"] & F_LAST) != 0)
    # Pre-event book: the last record that closed an earlier event (F_LAST) before the first trade; the
    # record just before the trade only when no flag precedes it.
    q0 = np.searchsorted(flag_idx, first) - 1
    pre = np.where(q0 >= 0, flag_idx[np.maximum(q0, 0)], first - 1)
    ok = pre >= 0
    pre = np.where(ok, pre, 0)
    touch = np.where(dirs > 0, c["as_"][pre], c["bs"][pre])
    d5 = np.where(dirs > 0, c["ad5"][pre], c["bd5"][pre]).astype(float)
    d5o = np.where(dirs > 0, c["bd5"][pre], c["ad5"][pre]).astype(float)
    best = np.where(dirs > 0, ap[pre], bp[pre])
    through = np.where(dirs > 0, hi - best, best - lo)
    lv = np.where(np.isfinite(through) & (through >= 0), np.floor(np.nan_to_num(through) / tick_ns + 1e-9) + 1, 0)
    keep = ok & np.isfinite(mid[pre]) & (touch > 0) & (traded >= touch) & (lv >= 1) & (d5 > 0)
    rows = []
    end_ts = ts[-1]
    for k in np.flatnonzero(keep):
        f, l, d, pk = int(first[k]), int(last[k]), int(dirs[k]), int(pre[k])
        q = np.searchsorted(flag_idx, l)
        p = int(flag_idx[q]) if q < len(flag_idx) else l          # the book after the event
        t0 = ts[p]
        depth = c["ad5"] if d > 0 else c["bd5"]
        row = dict(ts=int(ts[f]), dir=d, levels_swept=int(lv[k]), traded=int(traded[k]), n_trades=int(n_tr[k]),
                   pre_spread=float(spread[pk] / tick_ns), pre_touch=int(touch[k]), pre_d5=float(d5[k]),
                   pre_d5_opp=float(d5o[k]))
        for h in REFILL_H:
            if t0 + h * NS > end_ts:
                row[f"refill_{h}s"] = np.nan
            else:
                j = int(np.searchsorted(ts, t0 + h * NS, side="right")) - 1
                row[f"refill_{h}s"] = float(depth[j]) / d5[k]
        w_end = int(np.searchsorted(ts, t0 + CENSOR_MS * 1_000_000, side="right"))
        censored = t0 + CENSOR_MS * 1_000_000 <= end_ts
        win = slice(p, w_end)
        hit = np.flatnonzero(depth[win] >= d5[k])
        row["t_refill_ms"] = (float(ts[p + hit[0]] - t0) / 1e6 if len(hit) else (float(CENSOR_MS) if censored else np.nan))
        sp = spread[win]
        hit = np.flatnonzero(np.isfinite(sp) & (sp <= spread[pk] + 1e-6))
        row["t_spread_ms"] = (float(ts[p + hit[0]] - t0) / 1e6 if len(hit) else (float(CENSOR_MS) if censored else np.nan))
        for h in MOVE_H:
            if t0 + h * NS > end_ts:
                row[f"move_{h}s"] = np.nan
            else:
                j = int(np.searchsorted(ts, t0 + h * NS, side="right")) - 1
                row[f"move_{h}s"] = float(d * (mid[j] - mid[pk]) / tick_ns)
        rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)
