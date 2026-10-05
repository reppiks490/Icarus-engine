# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.extend: extend the committed MNQ tapes with the cached Databento corpus
"""The committed MNQ tapes end on 2026-09-18. The Databento corpus (``databento_mnq_5m``,
continuous ``MNQ.v.0``, unadjusted front month, Actions cache only) continues them, so every
registered rule keeps collecting FORWARD evidence. Only bars strictly after the committed
tape's last bar are appended; the committed history is never replaced. Roll handling runs
on the combined tape (cl_lab.integrity), and the Databento ``instrument_id`` changes are
reported as an independent cross-check of the detected switch sessions."""
from __future__ import annotations

import pandas as pd

from . import bars as bars_mod

COLS = ("open", "high", "low", "close", "volume")


def splice(base: pd.DataFrame, ext: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    """(combined 5m frame, provenance). Both frames are indexed by UTC bar open."""
    prov = dict(base=dict(first=base.index[0].isoformat(), last=base.index[-1].isoformat(), rows=int(len(base))))
    if ext is None or ext.empty:
        return base, dict(prov, extension=None)
    e = ext[list(COLS)].astype(float)
    e = e[e.index > base.index[-1]].dropna(subset=["open", "high", "low", "close"])
    if e.empty:
        return base, dict(prov, extension=dict(rows=0))
    out = pd.concat([base[list(COLS)], e]).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out, dict(prov, extension=dict(source="cache:databento_mnq_5m (MNQ.v.0)", first=e.index[0].isoformat(),
                                          last=e.index[-1].isoformat(), rows=int(len(e))))


def instrument_switches(ext: pd.DataFrame | None) -> list[dict]:
    """Session dates on which the Databento continuous contract changed instrument."""
    if ext is None or ext.empty or "instrument_id" not in ext:
        return []
    a = bars_mod.annotate(ext[list(COLS)].astype(float))
    iid = ext["instrument_id"].to_numpy()
    out = []
    for k in range(1, len(iid)):
        if pd.notna(iid[k]) and pd.notna(iid[k - 1]) and iid[k] != iid[k - 1]:
            out.append(dict(session=str(a["session_date"].iloc[k]), ts=a.index[k].isoformat(),
                            from_id=int(iid[k - 1]), to_id=int(iid[k])))
    return out


def bars_20m(ext: pd.DataFrame | None, after_close_ts) -> list:
    """Close-stamped 20-minute ``icarus.data.Bar`` objects built from the 5m extension, for bars
    closing strictly after ``after_close_ts`` (the committed 20m tape's last bar)."""
    if ext is None or ext.empty:
        return []
    from icarus.data import Bar
    e = ext[list(COLS)].astype(float)
    r = e.resample("20min", origin="epoch", label="left", closed="left")
    df = pd.DataFrame(dict(open=r["open"].first(), high=r["high"].max(), low=r["low"].min(),
                           close=r["close"].last(), volume=r["volume"].sum())).dropna(subset=["open", "close"])
    df.index = df.index + pd.Timedelta(minutes=20)
    df = df[(df.index > pd.Timestamp(after_close_ts)) & (df.index <= e.index[-1] + pd.Timedelta(minutes=5))]
    return [Bar(ts=t.to_pydatetime(), open=float(x.open), high=float(x.high), low=float(x.low), close=float(x.close),
                volume=float(x.volume)) for t, x in df.iterrows()]
