# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.hypotheses: research-ranked hypotheses, pre-registered from the CL deep research
"""Pre-registered specifications copied from the CL research report
("NQ intraday edges and validation", 2026-10-04, ranked hypothesis 1), evaluated as
their own family (own FDR / DSR accounting) so adding them never edits the frozen
cl-g1 grammar or its candidate ids.

R1 conditional end-of-day momentum: r = close of the 15:25-15:30 bar / close of the
prior session's 15:55-16:00 bar - 1; trade sign(r) from the open of the 15:30-15:35 bar
to the close of the 15:55-16:00 bar. Variants: unconditional; |r| in the top tercile of
its trailing 250 sessions; 09:30-10:00 realized volatility in its trailing top tercile.
(Gao's prior-close-to-10:00 variant already exists in cl-g1 as imom.)
Ranked hypotheses 2 (month-end rebalancing) and 4 (pre-FOMC drift) hold across sessions
and need the multi-session simulator — not implemented yet, so not claimed here."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np

from . import backtest
from .backtest import bracket_trade
from .sessions import slot_of

HYPOTHESES_VERSION = "cl-r1"


@dataclass(frozen=True)
class RCandidate:
    family: str
    params: tuple

    @property
    def id(self) -> str:
        blob = json.dumps([HYPOTHESES_VERSION, self.family, [list(p) for p in self.params]], sort_keys=True)
        return "r" + hashlib.sha1(blob.encode()).hexdigest()[:11]

    def spec(self) -> dict:
        return dict(id=self.id, family=self.family, grammar=HYPOTHESES_VERSION, params=dict(self.params))


def eod_trades(sess, variant: str):
    k_sig, e = slot_of("15:25"), slot_of("15:30")
    prev_last = np.r_[np.nan, sess.C[:-1, -1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(sess.complete, sess.C[:, k_sig] / prev_last - 1.0, np.nan)
        rv = np.where(sess.complete, np.nanstd(np.diff(np.log(sess.C[:, :6]), axis=1), axis=1), np.nan)
    gate = np.ones(sess.D, bool)
    if variant == "r_top_tercile":
        thr = sess.trailing_stat("r1|eod_abs_r", np.abs(r), lambda w: np.quantile(w, 2 / 3), 250, 60)
        gate = np.abs(r) >= thr
    elif variant == "rv_open_top_tercile":
        thr = sess.trailing_stat("r1|eod_rv_open", rv, lambda w: np.quantile(w, 2 / 3), 250, 60)
        gate = rv >= thr
    out = []
    for d in np.nonzero(sess.complete & np.isfinite(r) & gate)[0]:
        if r[d] != 0:
            out.append(bracket_trade(sess, d, e, 1 if r[d] > 0 else -1))
    return out


CANDIDATES = [RCandidate("eod", (("variant", v),)) for v in ("unconditional", "r_top_tercile", "rv_open_top_tercile")]


def run_r(c, sess, cost):
    return backtest.to_result(eod_trades(sess, dict(c.params)["variant"]), sess, cost)
