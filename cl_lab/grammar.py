# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.grammar: pre-registered rule grammar of candidate intraday edges
"""Rule families with deterministic parameter grids (the pre-registered search space).

Causality contract: a decision at bar j of day d may use O/H/L/C/V of bars <= j
of day d, per-day context computed from days < d (plus the overnight bars known
at 09:30 ET) and anything from days < d. Execution is at O[d, j+1] (or at the
session's last close). Tests in tests_cl/test_core.py enforce this with
cross-day prefix invariance and intraday truncation invariance plus a leaky
positive control.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass

import numpy as np

from .backtest import Trade, bracket_trade
from .sessions import slot_of

GRAMMAR_VERSION = "cl-g1"
TICK = 0.25
REGIMES = ("all", "vol_hi", "vol_lo")


@dataclass(frozen=True)
class Candidate:
    family: str
    params: tuple  # ((key, value), ...) sorted by key

    @property
    def id(self) -> str:
        blob = json.dumps([GRAMMAR_VERSION, self.family, [list(p) for p in self.params]], sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]

    def spec(self) -> dict:
        return dict(id=self.id, family=self.family, grammar=GRAMMAR_VERSION, params=dict(self.params))


def _product(**axes):
    keys = list(axes)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(axes[k] for k in keys))]


def _days(sess, p, extra=None):
    ok = sess.complete & sess.regime_ok(p["regime"])
    if extra is not None:
        ok = ok & extra
    return np.nonzero(ok)[0]


def _target(entry, stop, direction, mode):
    if mode in ("eod", None):
        return np.nan
    r = abs(entry - stop)
    mult = {"2R": 2.0, "10R": 10.0}[mode]
    return entry + direction * mult * r


class Family:
    name = ""

    def grid(self):
        raise NotImplementedError

    def trades(self, sess, p):
        raise NotImplementedError


class IntradayMomentum(Family):
    """Gao, Han, Li & Zhou (2018): early return sign predicts the last part of the session."""
    name = "imom"

    def grid(self):
        return _product(base=("prevclose", "open"), t1=("10:00", "10:30"), entry=("15:00", "15:30"),
                        min_abs=("none", "q50"), regime=REGIMES)

    def trades(self, sess, p):
        k1, e = slot_of(p["t1"]) - 1, slot_of(p["entry"])
        base = sess.prev_close if p["base"] == "prevclose" else sess.O[:, 0]
        with np.errstate(invalid="ignore", divide="ignore"):
            r1 = np.where(sess.complete, sess.C[:, k1] / base - 1.0, np.nan)
        thr = None
        if p["min_abs"] == "q50":
            thr = sess.trailing_stat(f"imom|{p['base']}|{p['t1']}", np.abs(r1), np.median, 60, 20)
        out = []
        for d in _days(sess, p, np.isfinite(r1)):
            if r1[d] == 0 or (thr is not None and not (np.isfinite(thr[d]) and abs(r1[d]) >= thr[d])):
                continue
            out.append(bracket_trade(sess, d, e, int(np.sign(r1[d]))))
        return out


class NoiseBoundary(Family):
    """Zarattini, Aziz & Barbon (2024): breakout of a time-of-day noise band around the open."""
    name = "noise"

    def grid(self):
        return _product(lookback=(10, 14, 20), mult=(1.0, 1.5), check=(30, 60), trail=("band", "band_vwap"),
                        regime=REGIMES)

    @staticmethod
    def sigma(sess, lookback):
        key = ("noise_sigma", lookback)
        if key not in sess.cache:
            with np.errstate(invalid="ignore", divide="ignore"):
                move = np.abs(sess.C / sess.O[:, [0]] - 1.0)
            comp = np.nonzero(sess.complete)[0]
            sig = np.full(move.shape, np.nan)
            for i in range(lookback, len(comp)):
                sig[comp[i]] = move[comp[i - lookback:i]].mean(axis=0)
            sess.cache[key] = sig
        return sess.cache[key]

    def trades(self, sess, p):
        sig = self.sigma(sess, p["lookback"])
        checks = [j for j in range(5, 77) if ((j + 1) * 5) % p["check"] == 0]
        O, C, VW = sess.O, sess.C, sess.vwap
        out = []
        for d in _days(sess, p, np.isfinite(sig[:, 0]) & np.isfinite(sess.prev_close)):
            o0, pc = O[d, 0], sess.prev_close[d]
            up = max(o0, pc) * (1 + p["mult"] * sig[d])
            lo = min(o0, pc) * (1 - p["mult"] * sig[d])
            pos, es = 0, -1
            for j in checks:
                c, exited = C[d, j], 0
                if pos == 1 and c < (up[j] if p["trail"] == "band" else max(up[j], VW[d, j])):
                    out.append(Trade(d, es, float(O[d, es]), j + 1, float(O[d, j + 1]), 1, "trail"))
                    pos, exited = 0, 1
                elif pos == -1 and c > (lo[j] if p["trail"] == "band" else min(lo[j], VW[d, j])):
                    out.append(Trade(d, es, float(O[d, es]), j + 1, float(O[d, j + 1]), -1, "trail"))
                    pos, exited = 0, -1
                if pos == 0:
                    if c > up[j] and exited != 1:
                        pos, es = 1, j + 1
                    elif c < lo[j] and exited != -1:
                        pos, es = -1, j + 1
            if pos != 0:
                out.append(Trade(d, es, float(O[d, es]), 78, float(C[d, 77]), pos, "eod"))
        return out


class OpeningRange(Family):
    """Opening-range breakout incl. the 5-minute first-candle rule of Zarattini, Barbon & Aziz."""
    name = "orb"

    def grid(self):
        g = _product(or_min=(5,), entry_mode=("first_candle_dir",), stop=("candle",), target=("eod", "2R", "10R"),
                     side=("both", "long"), regime=REGIMES)
        g += _product(or_min=(5, 15, 30), entry_mode=("breakout_close",), stop=("or_opposite", "atr10"),
                      target=("eod", "2R", "10R"), side=("both", "long"), regime=REGIMES)
        return g

    def trades(self, sess, p):
        O, H, L, C = sess.O, sess.H, sess.L, sess.C
        k = p["or_min"] // 5
        out = []
        need = np.isfinite(sess.atr14) if p["stop"] == "atr10" else None
        for d in _days(sess, p, need):
            if p["entry_mode"] == "first_candle_dir":
                dr = int(np.sign(C[d, 0] - O[d, 0]))
                if dr == 0 or (p["side"] == "long" and dr < 0):
                    continue
                entry, stop = O[d, 1], (L[d, 0] if dr > 0 else H[d, 0])
                if (entry - stop) * dr <= 0:
                    continue
                out.append(bracket_trade(sess, d, 1, dr, stop, _target(entry, stop, dr, p["target"])))
                continue
            orh, orl = H[d, :k].max(), L[d, :k].min()
            for j in range(k, 77):
                dr = 1 if C[d, j] > orh else (-1 if (C[d, j] < orl and p["side"] == "both") else 0)
                if dr == 0:
                    continue
                entry = O[d, j + 1]
                if p["stop"] == "or_opposite":
                    stop = orl if dr > 0 else orh
                else:
                    stop = entry - dr * 0.10 * sess.atr14[d]
                if (entry - stop) * dr > 0:
                    out.append(bracket_trade(sess, d, j + 1, dr, stop, _target(entry, stop, dr, p["target"])))
                break
        return out


class OpeningGap(Family):
    """Overnight gap (09:30 overnight close vs prior RTH close): fade or follow."""
    name = "gap"

    def grid(self):
        g = _product(thr=("q50", "q80"), mode=("fade",), exit=("10:30", "12:00", "eod", "fill"), regime=REGIMES)
        g += _product(thr=("q50", "q80"), mode=("go",), exit=("10:30", "12:00", "eod"), regime=REGIMES)
        return g

    def trades(self, sess, p):
        with np.errstate(invalid="ignore", divide="ignore"):
            gap = sess.on_close / sess.prev_close - 1.0
        q = 0.5 if p["thr"] == "q50" else 0.8
        thr = sess.trailing_stat(f"gap|{p['thr']}", np.abs(gap), lambda w: np.quantile(w, q), 60, 20)
        out = []
        for d in _days(sess, p, np.isfinite(gap) & np.isfinite(thr)):
            if gap[d] == 0 or abs(gap[d]) < thr[d]:
                continue
            dr = int(-np.sign(gap[d]) if p["mode"] == "fade" else np.sign(gap[d]))
            if p["exit"] == "fill":
                out.append(bracket_trade(sess, d, 0, dr, np.nan, sess.prev_close[d], 78))
            else:
                xs = 78 if p["exit"] == "eod" else slot_of(p["exit"])
                out.append(bracket_trade(sess, d, 0, dr, exit_slot=xs))
        return out


class LevelSweep(Family):
    """Sweep of the prior-day or overnight high/low: reversal vs continuation (the Icarus core premise)."""
    name = "sweep"

    def grid(self):
        return _product(level=("pd", "on"), mode=("reverse", "continue"), depth_ticks=(0, 4, 8),
                        window=("am", "day"), exit=("eod", "2R"), regime=REGIMES)

    def trades(self, sess, p):
        O, H, L, C = sess.O, sess.H, sess.L, sess.C
        hi = sess.prev_high if p["level"] == "pd" else sess.on_high
        lo = sess.prev_low if p["level"] == "pd" else sess.on_low
        last = slot_of("11:30") - 1 if p["window"] == "am" else slot_of("15:00") - 1
        dep = p["depth_ticks"] * TICK
        out = []
        for d in _days(sess, p, np.isfinite(hi) & np.isfinite(lo)):
            for j in range(0, last + 1):
                if p["mode"] == "reverse":
                    up = H[d, j] >= hi[d] + dep and C[d, j] < hi[d]
                    dn = L[d, j] <= lo[d] - dep and C[d, j] > lo[d]
                    dr = -1 if (up and not dn) else (1 if (dn and not up) else 0)
                    stop = (H[d, j] + TICK) if dr < 0 else (L[d, j] - TICK)
                else:
                    up = C[d, j] > hi[d] + dep
                    dn = C[d, j] < lo[d] - dep
                    dr = 1 if up else (-1 if dn else 0)
                    stop = (L[d, j] - TICK) if dr > 0 else (H[d, j] + TICK)
                if dr == 0:
                    continue
                entry = O[d, j + 1]
                if (entry - stop) * dr > 0:
                    out.append(bracket_trade(sess, d, j + 1, dr, stop, _target(entry, stop, dr, p["exit"])))
                break
        return out


class TimeOfDay(Family):
    """Heston, Korajczyk & Sadka (2010): same half-hour return persistence across days."""
    name = "tod"
    WHICH = {"first": (0,), "last": (12,), "ends": (0, 12), "all": tuple(range(13))}

    def grid(self):
        return _product(lookback=(10, 20, 40), which=tuple(self.WHICH), regime=REGIMES)

    @staticmethod
    def signal(sess, lookback):
        key = ("tod_signal", lookback)
        if key not in sess.cache:
            hs = np.arange(13)
            with np.errstate(invalid="ignore", divide="ignore"):
                hr = sess.C[:, 6 * hs + 5] / sess.O[:, 6 * hs] - 1.0
            comp = np.nonzero(sess.complete)[0]
            sig = np.zeros(hr.shape, dtype=int)
            for i in range(lookback, len(comp)):
                sig[comp[i]] = np.sign(hr[comp[i - lookback:i]].sum(axis=0)).astype(int)
            sess.cache[key] = sig
        return sess.cache[key]

    def trades(self, sess, p):
        sig = self.signal(sess, p["lookback"])
        out = []
        for d in _days(sess, p):
            for h in self.WHICH[p["which"]]:
                dr = int(sig[d, h])
                if dr:
                    out.append(bracket_trade(sess, d, 6 * h, dr, exit_slot=(6 * h + 6 if h < 12 else 78)))
        return out


class VwapTrend(Family):
    """Zarattini & Aziz (2023): hold the side of session VWAP, re-checked on bar closes."""
    name = "vwap"

    def grid(self):
        return _product(check=(5, 30), side=("both", "long"), start=("09:35", "10:00"), regime=REGIMES)

    def trades(self, sess, p):
        O, C, VW = sess.O, sess.C, sess.vwap
        j0 = slot_of(p["start"]) - 1
        checks = [j for j in range(j0, 77) if ((j + 1) * 5) % p["check"] == 0]
        out = []
        for d in _days(sess, p):
            pos, es = 0, -1
            for j in checks:
                want = 1 if C[d, j] > VW[d, j] else (-1 if p["side"] == "both" else 0)
                if want == pos:
                    continue
                if pos != 0:
                    out.append(Trade(d, es, float(O[d, es]), j + 1, float(O[d, j + 1]), pos, "flip"))
                pos, es = want, j + 1
            if pos != 0:
                out.append(Trade(d, es, float(O[d, es]), 78, float(C[d, 77]), pos, "eod"))
        return out


FAMILIES = {f.name: f for f in (IntradayMomentum(), NoiseBoundary(), OpeningRange(), OpeningGap(),
                                LevelSweep(), TimeOfDay(), VwapTrend())}


def enumerate_candidates(families=None):
    names = families or list(FAMILIES)
    return [Candidate(n, tuple(sorted(p.items()))) for n in names for p in FAMILIES[n].grid()]


def registration_hash(cands) -> str:
    return hashlib.sha256("\n".join(sorted(c.id for c in cands)).encode()).hexdigest()
