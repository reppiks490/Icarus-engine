# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.store: cache frames, merge, integrity checks and manifest entries
from __future__ import annotations

import hashlib
import os

import numpy as np
import pandas as pd


def save_frame(df: pd.DataFrame, path) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp"
    df.to_csv(tmp, compression="gzip", date_format="%Y-%m-%dT%H:%M:%S%z")
    os.replace(tmp, path)


def load_frame(path, intraday: bool = True) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, compression="gzip", index_col=0)
    idx = pd.to_datetime(df.index, utc=intraday)
    df.index = pd.DatetimeIndex(idx, name="ts_open" if intraday else "date")
    return df


def merge_frames(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if old is None or old.empty:
        out = new.copy()
    elif new is None or new.empty:
        out = old.copy()
    else:
        out = pd.concat([old, new])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def integrity(df: pd.DataFrame, tick_size=None, intraday: bool = True) -> dict:
    if df.empty:
        return dict(rows=0)
    rep = dict(rows=int(len(df)), first=df.index[0].isoformat(), last=df.index[-1].isoformat(),
               dup_index=int(df.index.duplicated().sum()),
               non_monotonic=int((np.diff(df.index.asi8) <= 0).sum()))
    if intraday and {"open", "high", "low", "close"} <= set(df.columns):
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        rep["ohlc_violations"] = int(((l > h) | (o > h) | (o < l) | (c > h) | (c < l)).sum())
        rep["nonpositive"] = int((np.c_[o, h, l, c] <= 0).any(axis=1).sum())
        if tick_size:
            q = np.c_[o, h, l, c] / tick_size
            rep["off_tick"] = int((np.abs(q - np.round(q)) > 1e-6).any(axis=1).sum())
        gaps = np.diff(df.index.asi8) / 6e10
        rep["max_gap_minutes"] = float(gaps.max()) if len(gaps) else 0.0
    return rep


def sha256_frame(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.to_csv(date_format="%Y-%m-%dT%H:%M:%S%z").encode()).hexdigest()


def manifest_entry(name, df, status, error=None, source_url=None, tick_size=None, intraday=True) -> dict:
    ent = dict(name=name, status=status, error=(str(error)[:300] if error else None), source=source_url)
    if df is not None and not df.empty:
        ent["integrity"] = integrity(df, tick_size, intraday)
        ent["sha256"] = sha256_frame(df)
    else:
        ent["integrity"] = dict(rows=0)
        ent["sha256"] = None
    return ent
