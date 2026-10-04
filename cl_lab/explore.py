# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.explore: edge explorer — invents and tests new rule compositions every run
"""Each run samples EXPLORE_PER_RUN never-tested compositions per asset from a much
larger space (wider parameter grids x volatility regime x causal day conditioners),
deterministically from (asset, date). Every attempt is appended to an append-only
ledger, and the gate stack is told the full history (all earlier TUNE p-values for
BH-FDR, the cumulative trial count for the Deflated Sharpe, every HOLD visit for the
Bonferroni HOLD test), so searching more can never make a lucky rule look better."""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from dataclasses import dataclass

import numpy as np

from . import backtest, conditions
from .grammar import FAMILIES, REGIMES

EXPLORE_VERSION = "cl-x1"
EXPLORE_PER_RUN = 24

EXT = {
    "imom": [dict(base=("prevclose", "open"), t1=("10:00", "10:30", "11:00", "11:30"),
                  entry=("14:30", "15:00", "15:30"), min_abs=("none", "q50"))],
    "noise": [dict(lookback=(5, 10, 14, 20, 30), mult=(0.75, 1.0, 1.25, 1.5, 2.0), check=(15, 30, 60),
                   trail=("band", "band_vwap"))],
    "orb": [dict(or_min=(5,), entry_mode=("first_candle_dir",), stop=("candle",), target=("eod", "2R", "10R"),
                 side=("both", "long")),
            dict(or_min=(5, 10, 15, 30, 60), entry_mode=("breakout_close",), stop=("or_opposite", "atr10"),
                 target=("eod", "2R", "10R"), side=("both", "long"))],
    "gap": [dict(thr=("q50", "q80"), mode=("fade",), exit=("10:00", "10:30", "11:00", "12:00", "eod", "fill")),
            dict(thr=("q50", "q80"), mode=("go",), exit=("10:00", "10:30", "11:00", "12:00", "eod"))],
    "sweep": [dict(level=("pd", "on"), mode=("reverse", "continue"), depth_ticks=(0, 2, 4, 8, 12, 16),
                   window=("am", "day"), exit=("eod", "2R"))],
    "tod": [dict(lookback=(5, 10, 20, 40, 60), which=("first", "last", "ends", "all"))],
    "vwap": [dict(check=(5, 15, 30, 60), side=("both", "long"), start=("09:35", "10:00", "10:30"))],
}


@dataclass(frozen=True)
class XCandidate:
    family: str
    params: tuple  # includes ("regime", ..) and ("cond", ..)

    @property
    def id(self) -> str:
        blob = json.dumps([EXPLORE_VERSION, self.family, [list(p) for p in self.params]], sort_keys=True)
        return "x" + hashlib.sha1(blob.encode()).hexdigest()[:11]

    def spec(self) -> dict:
        return dict(id=self.id, family=self.family, grammar=EXPLORE_VERSION, params=dict(self.params))


def space():
    out = []
    for fam, grids in EXT.items():
        for g in grids:
            keys = list(g)
            for vals in itertools.product(*(g[k] for k in keys)):
                base = dict(zip(keys, vals))
                for reg in REGIMES:
                    for cond in conditions.CONDITIONS:
                        out.append(XCandidate(fam, tuple(sorted({**base, "regime": reg, "cond": cond}.items()))))
    return out


def run_x_trades(c, sess):
    p = dict(c.params)
    keep = conditions.mask(sess, p.pop("cond"))
    return [t for t in FAMILIES[c.family].trades(sess, p) if keep[t.day]]


def run_x(c, sess, cost):
    return backtest.to_result(run_x_trades(c, sess), sess, cost)


def neighbours(c):
    """One-parameter variants inside the explorer space (same family, regime and conditioner)."""
    p = dict(c.params)
    out = []
    for g in EXT[c.family]:
        if not all(p.get(k) in v for k, v in g.items()):
            continue
        for k, vals in g.items():
            for v in vals:
                if v != p[k]:
                    out.append(XCandidate(c.family, tuple(sorted({**p, k: v}.items()))))
    return out


def sample(asset: str, day: str, explored: set, k: int = EXPLORE_PER_RUN):
    seed = int(hashlib.sha256(f"{EXPLORE_VERSION}|{asset}|{day}".encode()).hexdigest()[:16], 16)
    sp = space()
    order = np.random.default_rng(seed).permutation(len(sp))
    picks = []
    for i in order:
        c = sp[int(i)]
        if c.id not in explored:
            picks.append(c)
            if len(picks) == k:
                break
    return picks


def load_ledger(path):
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    return rows


def append_ledger(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
