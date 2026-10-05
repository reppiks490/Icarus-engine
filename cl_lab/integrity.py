# CL (Claude, Anthropic) — 2026-10-04 (rev. 2026-10-05) — cl_lab.integrity: contract-roll detection and Panama back-adjustment (cl-data-3)
"""Continuous futures tapes that splice contracts without adjustment jump by the calendar
spread at each switch. That corrupts every cross-session price (prior close, overnight
range, gap, ATR true range) and every position held through the switch.

Primary detector (needs the underlying index close): the futures-minus-index basis at the
RTH close jumps by the calendar spread on the switch session and moves a few points on
other days. Per quarter, the switch session is the session dated in [third Friday - 14d,
third Friday - 1d] with the largest |basis change|, accepted at >= MIN_JUMP_BP of price;
the adjustment is that basis change. The switch bar is the session's largest bar-to-bar
jump when it has the same sign and at least half the size; otherwise the whole session is
treated as the new contract and its overnight range is marked unreliable. On the MNQ
tapes the switch sessions sit in data gaps, so a bar jump alone mixes the spread with the
market's move across the gap.

Fallback (no index data): the largest bar jump in the session dated the Thursday 8 days
before the third Friday, accepted at >= MIN_JUMP_BP, with that jump as the adjustment.

cl-data-3 (2026-10-05): when the tape carries Databento's ``instrument_id`` (the contract of each
bar), every change of it IS a roll, whatever its size; the size threshold above only exists because
plain tapes do not say which contract a bar came from. On the 2013-2022 NQ history the calendar
spread was often 3-30 points (< 40 bp; carry was near zero), so 35 of 46 rolls went unadjusted under
cl-data-2. A switch is sized by the jump from the last bar of the old contract to the first bar of
the new one when they are at most ``ADJACENT_GAP`` apart (Databento switches at 00:00 UTC, inside the
overnight session, so the two prints are minutes apart), otherwise by the basis change of that session
when the index close is available, otherwise by the bar jump. Quarters the instrument_id does not
cover keep the cl-data-2 rules."""
from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import numpy as np
import pandas as pd

DATA_VERSION = "cl-data-3"
MIN_JUMP_BP = 40.0
BASIS_JUMP_PTS = 150.0
ADJACENT_GAP = pd.Timedelta(minutes=10)


def third_friday(y: int, m: int) -> date:
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def quarters(first: date, last: date):
    for y in range(first.year, last.year + 1):
        for m in (3, 6, 9, 12):
            tf = third_friday(y, m)
            if first < tf - timedelta(days=8) <= last:
                yield f"{y}-{m:02d}", tf


def _last_rth_close(adf: pd.DataFrame) -> pd.Series:
    r = adf[adf["rth"]]
    return r.groupby("session_date", sort=True)["close"].last()


def _bar_jumps(adf):
    o, c = adf["open"].to_numpy(float), adf["close"].to_numpy(float)
    return np.r_[np.nan, o[1:] - c[:-1]], c


def _quarter_of(d: date) -> tuple[str, date]:
    """The quarterly expiry a switch on session ``d`` belongs to (the next third Friday of Mar/Jun/Sep/Dec)."""
    for y in (d.year, d.year + 1):
        for m in (3, 6, 9, 12):
            tf = third_friday(y, m)
            if tf >= d - timedelta(days=3):
                return f"{y}-{m:02d}", tf
    raise ValueError(d)


def _instrument_rolls(adf, sd, jump, basis):
    """(rolls from instrument_id switches, set of quarters the instrument_id covers) or (None, set())."""
    if "instrument_id" not in adf.columns:
        return None, set()
    v = pd.to_numeric(adf["instrument_id"], errors="coerce").to_numpy(float)
    pos = np.flatnonzero(np.isfinite(v))
    if len(pos) < 2:
        return None, set()
    first_d, last_d = sd[pos[0]], sd[pos[-1]]
    covered = {q for q, tf in quarters(first_d, last_d) if first_d <= tf - timedelta(days=21) and tf <= last_d}
    ts = adf.index
    out = []
    for i in np.flatnonzero(v[pos[1:]] != v[pos[:-1]]):
        k, prev = int(pos[i + 1]), int(pos[i])
        s = sd[k]
        q, tf = _quarter_of(s)
        rec = dict(quarter=q, third_friday=str(tf), method="instrument_id", session=str(s), pos=k,
                   ts=ts[k].isoformat(), from_id=int(v[prev]), to_id=int(v[k]), bar_jump=float(jump[k]) if np.isfinite(jump[k]) else None)
        prior = [d for d in (basis.index if basis is not None else []) if d < s]
        if k == prev + 1 and ts[k] - ts[prev] <= ADJACENT_GAP and np.isfinite(jump[k]):
            delta, sized = float(jump[k]), "adjacent_bars"
        elif basis is not None and s in basis.index and prior:
            delta, sized = float(basis[s] - basis[prior[-1]]), "basis"
        else:
            delta, sized = float(jump[k]) if np.isfinite(jump[k]) else 0.0, "bar_jump"
        px = float(adf["close"].iloc[prev])
        out.append(dict(rec, delta=round(delta, 4), bp=round(1e4 * delta / px, 1) if px else None, sized_by=sized,
                        switch="bar", status="DETECTED"))
    return out, covered


def detect_rolls(adf: pd.DataFrame, index_close: pd.Series | None = None) -> list[dict]:
    """``adf``: :func:`cl_lab.bars.annotate` frame in time order (an ``instrument_id`` column, when present,
    gives exact switches). ``index_close``: daily close of the underlying index (date-indexed), or None."""
    if adf.empty:
        return []
    sd = adf["session_date"].to_numpy()
    jump, c = _bar_jumps(adf)
    basis = None
    if index_close is not None and len(index_close):
        ix = index_close.dropna()
        ix = pd.Series(ix.to_numpy(float), index=pd.to_datetime(ix.index).date)
        lc = _last_rth_close(adf)
        common = [d for d in lc.index if d in ix.index]
        if len(common) > 2:
            basis = pd.Series([lc[d] - ix[d] for d in common], index=common)
    out, covered = _instrument_rolls(adf, sd, jump, basis)
    out = list(out or [])
    for q, tf in quarters(min(sd), max(sd)):
        if q in covered:
            if not any(r["quarter"] == q for r in out):
                out.append(dict(quarter=q, third_friday=str(tf), method="instrument_id", status="NO_SWITCH"))
            continue
        rec = dict(quarter=q, third_friday=str(tf))
        if basis is not None:
            db = basis.diff()
            win = db[[(tf - timedelta(days=14)) <= d <= (tf - timedelta(days=1)) for d in db.index]].dropna()
            if len(win) == 0:
                out.append(dict(rec, method="basis", status="NO_DATA"))
                continue
            sess_d = win.abs().idxmax()
            delta = float(win[sess_d])
            px = float(_last_rth_close(adf).get(sess_d, np.nan))
            bp = 1e4 * delta / px
            rec.update(method="basis", session=str(sess_d), delta=round(delta, 4), bp=round(bp, 1))
            if abs(bp) < MIN_JUMP_BP:
                out.append(dict(rec, status="ROLL_NOT_DETECTED"))
                continue
            idx = np.nonzero(sd == sess_d)[0]
            idx = idx[(idx > 0) & np.isfinite(jump[idx])]
            k = int(idx[np.argmax(np.abs(jump[idx]))]) if len(idx) else -1
            if k >= 0 and np.sign(jump[k]) == np.sign(delta) and abs(jump[k]) >= 0.5 * abs(delta):
                rec.update(pos=k, switch="bar", ts=adf.index[k].isoformat(), bar_jump=float(jump[k]))
            else:
                first = int(np.nonzero(sd == sess_d)[0][0])
                rec.update(pos=first, switch="session_boundary", ts=adf.index[first].isoformat(),
                           bar_jump=(float(jump[k]) if k >= 0 else None))
            out.append(dict(rec, status="DETECTED"))
        else:
            sw = tf - timedelta(days=8)
            idx = np.nonzero(sd == sw)[0]
            idx = idx[(idx > 0) & np.isfinite(jump[idx])]
            if len(idx) == 0:
                out.append(dict(rec, method="bar_jump", status="NO_DATA"))
                continue
            k = int(idx[np.argmax(np.abs(jump[idx]))])
            bp = 1e4 * jump[k] / c[k - 1]
            rec.update(method="bar_jump", session=str(sw), pos=k, switch="bar", ts=adf.index[k].isoformat(),
                       delta=float(jump[k]), bar_jump=float(jump[k]), bp=round(float(bp), 1))
            out.append(dict(rec, status="DETECTED" if abs(bp) >= MIN_JUMP_BP else "ROLL_NOT_DETECTED"))
    return sorted(out, key=lambda r: (r["quarter"], r.get("pos", -1)))


def transfer(rolls: list[dict], adf: pd.DataFrame) -> list[dict]:
    """Re-locate detected rolls (session + delta) on another tape of the same contract series."""
    sd = adf["session_date"].to_numpy()
    jump, _ = _bar_jumps(adf)
    out = []
    for r in rolls:
        r2 = {k: v for k, v in r.items() if k not in ("pos", "ts", "switch", "bar_jump")}
        if r.get("status") != "DETECTED":
            out.append(r2)
            continue
        d = date.fromisoformat(r["session"])
        idx = np.nonzero(sd == d)[0]
        if len(idx) == 0:
            out.append(dict(r2, status="NO_DATA"))
            continue
        cand = idx[(idx > 0) & np.isfinite(jump[idx])]
        k = int(cand[np.argmax(np.abs(jump[cand]))]) if len(cand) else -1
        if k >= 0 and np.sign(jump[k]) == np.sign(r["delta"]) and abs(jump[k]) >= 0.5 * abs(r["delta"]):
            out.append(dict(r2, pos=k, switch="bar", ts=adf.index[k].isoformat(), bar_jump=float(jump[k])))
        else:
            out.append(dict(r2, pos=int(idx[0]), switch="session_boundary", ts=adf.index[int(idx[0])].isoformat()))
    return out


def adjustment(n: int, rolls: list[dict]) -> np.ndarray:
    adj = np.zeros(n)
    for r in rolls:
        if r.get("status") == "DETECTED":
            adj[: r["pos"]] += r["delta"]
    return adj


def back_adjust(adf: pd.DataFrame, rolls: list[dict]) -> pd.DataFrame:
    adj = adjustment(len(adf), rolls)
    out = adf.copy()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].to_numpy(float) + adj
    return out


def mark_sessions(sess, rolls: list[dict]) -> None:
    """Blank overnight ranges that may mix contracts; record windows of undetected rolls."""
    pos = {d: i for i, d in enumerate(sess.dates)}
    for r in rolls:
        if r.get("status") == "DETECTED" and r.get("switch") == "session_boundary":
            i = pos.get(date.fromisoformat(r["session"]))
            if i is not None:
                sess.on_high[i] = sess.on_low[i] = np.nan
    sess.cache["roll_unadjusted_windows"] = [
        (date.fromisoformat(r["third_friday"]) - timedelta(days=14), date.fromisoformat(r["third_friday"]))
        for r in rolls if r.get("status") in ("ROLL_NOT_DETECTED", "NO_DATA")]


def bars_frame(bar_list, minutes: int) -> pd.DataFrame:
    """Annotated frame indexed by bar OPEN (UTC) from close-stamped ``icarus.data.Bar`` objects."""
    from . import bars
    ts = pd.DatetimeIndex([b.ts for b in bar_list]).tz_convert("UTC") - pd.Timedelta(minutes=minutes)
    df = pd.DataFrame({k: [getattr(b, k) for b in bar_list] for k in ("open", "high", "low", "close")}, index=ts)
    df["volume"] = [getattr(b, "volume", 0.0) or 0.0 for b in bar_list]
    return bars.annotate(df)


def back_adjust_bars(bar_list, minutes: int, rolls: list[dict]):
    """(adjusted Bar list, relocated rolls) for a close-stamped Bar tape, e.g. THE PULSE's 20m tape."""
    if not bar_list:
        return bar_list, []
    moved = transfer(rolls, bars_frame(bar_list, minutes))
    adj = adjustment(len(bar_list), moved)
    out = [b if a == 0 else dataclasses.replace(b, open=b.open + a, high=b.high + a, low=b.low + a, close=b.close + a)
           for b, a in zip(bar_list, adj)]
    return out, moved


def basis_check(sess, index_close: pd.Series | None) -> dict:
    """Session-to-session change of (last RTH close - index close) on the ADJUSTED tape."""
    if index_close is None or len(index_close) == 0:
        return dict(status="UNAVAILABLE")
    s = index_close.dropna()
    lookup = dict(zip(pd.to_datetime(s.index).date, s.to_numpy(float)))
    last = np.array([row[np.isfinite(row)][-1] if np.isfinite(row).any() else np.nan for row in sess.C])
    rows = [(d, last[i] - lookup[d]) for i, d in enumerate(sess.dates) if d in lookup and np.isfinite(last[i])]
    if len(rows) < 3:
        return dict(status="UNAVAILABLE")
    dates, basis = zip(*rows)
    db = np.diff(np.asarray(basis))
    bad = [dict(date=str(dates[i + 1]), dbasis=round(float(db[i]), 2)) for i in np.nonzero(np.abs(db) > BASIS_JUMP_PTS)[0]]
    return dict(status="DEGRADED" if bad else "OK", sessions=len(rows),
                median_abs_dbasis=round(float(np.median(np.abs(db))), 2), max_abs_dbasis=round(float(np.max(np.abs(db))), 2),
                jumps=bad[:20], threshold_points=BASIS_JUMP_PTS)


def summary(rolls: list[dict]) -> dict:
    keep = ("quarter", "session", "method", "switch", "ts", "delta", "bp", "bar_jump", "sized_by", "status")
    return dict(data_version=DATA_VERSION, min_jump_bp=MIN_JUMP_BP,
                detected=[{k: r.get(k) for k in keep} for r in rolls if r.get("status") == "DETECTED"],
                not_detected=[{k: r.get(k) for k in keep} for r in rolls if r.get("status") != "DETECTED"])
