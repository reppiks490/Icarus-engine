# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.pulse_track: THE PULSE OF ICARUS v3.1 tracked through the CL gate stack
"""Runs the repository's own Python port of THE PULSE OF ICARUS v3.1
(icarus_engine/strategy/pulse.py, Emulator, HeikinAshi, tools/htf_context) on the
committed real MNQ 20m tape and grades it with the same gates as every CL rule.

Variants (everything else identical):
  HA_REAL_FILLS  signals on the Heikin-Ashi chart, orders fill on REAL bars (what a broker gives)
  CANDLES        standard candles, real fills
  HA_HA_FILLS    TradingView's default on an HA chart: fills at synthetic HA prices.
                 Reported for transparency only; status is always ARTIFACT_REFERENCE.

Preset: presets/NQ-20m-ultracoded.json values (RECONSTRUCTED there) + use_session=False,
10 MNQ ($2/pt). Costs: CL base = $0.85/side/contract + 1 tick; stress = $1.70 + 2 ticks.
The repository's historical convention ($0.37 + 2 ticks) is also reported for continuity.
PULSE was tuned in TradingView with an unrecorded number of trials, so its Deflated
Sharpe assumes PULSE_TRIALS_ASSUMED trials; the plain PSR is reported alongside.
"""
from __future__ import annotations

import glob
import hashlib
import os

import numpy as np
import pandas as pd

PRESET = dict(tp1_pts=100, sl_pts=80, qty_contracts=10, htf_tf_5="W", use_kalman=False,
              tide_confirm_mode="Strict", use_session=False, point_value=2.0)
TAPE = "data/mnq_20m_full.csv"
PULSE_TRIALS_ASSUMED = 100
COSTS = {"base": (0.85, 1), "stress": (1.70, 2), "repo_convention": (0.37, 2)}
SOURCES = ("icarus_engine/strategy/**/*.py", "icarus_engine/pine/**/*.py", "icarus_engine/emulator.py",
           "icarus_engine/runtime.py", "tools/htf_context.py", "tools/validate_pulse.py", TAPE,
           "cl_lab/pulse_track.py")


def fingerprint(root=".") -> str:
    h = hashlib.sha256()
    for pat in SOURCES:
        for p in sorted(glob.glob(os.path.join(root, pat), recursive=True)):
            h.update(os.path.relpath(p, root).encode())
            with open(p, "rb") as f:
                h.update(f.read())
    h.update(repr(sorted(PRESET.items())).encode())
    h.update(repr(sorted(COSTS.items())).encode())
    return h.hexdigest()


def run_variant(raw_bars, variant: str, commission: float, slip_ticks: int, **overrides):
    """Drive the repo port over the tape; returns the Emulator's closed trades."""
    from icarus_engine.emulator import Emulator
    from icarus_engine.runtime import HeikinAshi
    from icarus_engine.strategy.inputs import Inputs
    from icarus_engine.strategy.pulse import PulseStrategy
    from tools.htf_context import ContextProvider
    from tools.validate_pulse import to_pulse_bars

    real = to_pulse_bars(raw_bars)
    ha_tf = HeikinAshi(mintick=0.25)
    ha = [ha_tf.transform(b) for b in real]
    ctx = ContextProvider(raw_bars, "20m")
    em = Emulator(100_000.0, commission, 0.25, 2.0, slippage_ticks=slip_ticks)
    strat = PulseStrategy(Inputs(**{**PRESET, **overrides}), em, mintick=0.25, tf_minutes=20)
    for i, (rb, hb) in enumerate(zip(real, ha)):
        chart = rb if variant == "CANDLES" else hb
        fill = hb if variant == "HA_HA_FILLS" else rb
        em.process_bar(fill, i)
        htf, ltf = ctx.at(rb.ts)
        strat.on_bar(chart, i, htf, ltf)
    return list(em.closed)


def session_date_of(exit_ts) -> pd.Series:
    """Globex session date of each exit (ET clock >= 18:00 belongs to the next date)."""
    et = pd.to_datetime(pd.Series(exit_ts, dtype="int64"), unit="s", utc=True).dt.tz_convert("America/New_York")
    return (et.dt.tz_localize(None).dt.normalize() + pd.to_timedelta((et.dt.hour >= 18).astype(int), unit="D")).dt.date


def daily_pnl(closed, dates) -> tuple[np.ndarray, np.ndarray]:
    """USD P&L per session date (aligned to ``dates``) and trade counts per date."""
    idx = {d: i for i, d in enumerate(dates)}
    pnl, cnt = np.zeros(len(dates)), np.zeros(len(dates), dtype=int)
    if closed:
        sd = session_date_of([c.exit_ts for c in closed])
        for d, c in zip(sd, closed):
            if d in idx:
                pnl[idx[d]] += c.profit
                cnt[idx[d]] += 1
    return pnl, cnt
