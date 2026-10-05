# CL (Claude, Anthropic) — 2026-10-04 — tests for cl-data-2 integrity, multi-session holds, cl-r2 and cl-ml1
import json
import os
from datetime import date

import numpy as np
import pandas as pd
import pytest

from cl_lab import (backtest, bars, causality, costs, events, hypotheses, hypotheses_r2 as r2, integrity, ml,
                    multisession as ms, sessions)
from cl_lab.sessions import slot_of


def _vix(sess):
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(sess.dates)) - pd.Timedelta(days=1))
    o = np.array([d.toordinal() for d in idx.date], float)
    sess.cache[("ext", "VIX_close")] = pd.Series(18 + 4 * np.sin(o / 7.0), index=idx)
    sess.cache[("ext", "VIX9D_close")] = pd.Series(17 + 5 * np.cos(o / 5.0), index=idx)


def _tb(sess):
    sess.cache["TB"] = sess.V * np.where(sess.C >= sess.O, 0.7, 0.3)


# ---------------- integrity ----------------
def _rolled_frame():
    f = causality.synth_frame(n_sessions=60, start="2025-02-03")
    a = bars.annotate(f)
    sw = a.index[(a["session_date"] == date(2025, 3, 13)) & (a["minute_et"] == 0)][0]
    k = a.index.get_loc(sw)
    f = f.copy()
    for col in ("open", "high", "low", "close"):
        f.iloc[k:, f.columns.get_loc(col)] += 200.0   # unadjusted splice: +200 points from 00:00 ET Mar 13
    return f, k


def test_roll_detected_by_basis_and_by_bar_jump_and_removed():
    f, k = _rolled_frame()
    a = bars.annotate(f)
    s0 = sessions.build_sessions(a)
    last = pd.Series([row[np.isfinite(row)][-1] for row in s0.C], index=pd.to_datetime(pd.Series(s0.dates)))
    index = last - np.where(last.index >= pd.Timestamp("2025-03-13"), 200.0, 0.0) - 5.0   # index = old contract - 5
    for idx in (index, None):
        rolls = integrity.detect_rolls(a, idx)
        mar = [r for r in rolls if r["quarter"] == "2025-03"][0]
        assert mar["status"] == "DETECTED" and mar["pos"] == k and abs(mar["delta"] - 200.0) < 20
        adj = integrity.back_adjust(a, rolls)
        j = adj["open"].to_numpy()[k] - adj["close"].to_numpy()[k - 1]
        assert abs(j) < 20
    s = sessions.build_sessions(integrity.back_adjust(a, integrity.detect_rolls(a, index)))
    assert integrity.basis_check(s, index)["status"] == "OK"


def test_session_boundary_switch_blanks_overnight_range():
    f = causality.synth_frame(n_sessions=60, start="2025-02-03")
    a = bars.annotate(f)
    on = np.nonzero(((a["session_date"] == date(2025, 3, 13)) & ~a["rth"]).to_numpy())[0]
    f = f.copy()
    for k in (on[10], on[60], on[110]):                 # spread splice: no single bar carries half of it
        for col in ("open", "high", "low", "close"):
            f.iloc[k:, f.columns.get_loc(col)] += 70.0
    a = bars.annotate(f)
    s0 = sessions.build_sessions(a)
    last = pd.Series([row[np.isfinite(row)][-1] for row in s0.C], index=pd.to_datetime(pd.Series(s0.dates)))
    index = last - np.where(last.index >= pd.Timestamp("2025-03-13"), 210.0, 0.0)
    rolls = integrity.detect_rolls(a, index)
    mar = [r for r in rolls if r["quarter"] == "2025-03"][0]
    assert mar["status"] == "DETECTED" and mar["switch"] == "session_boundary" and mar["delta"] == pytest.approx(210.0)
    s = sessions.build_sessions(integrity.back_adjust(a, rolls))
    integrity.mark_sessions(s, rolls)
    i = list(s.dates).index(date(2025, 3, 13))
    assert np.isnan(s.on_high[i]) and np.isnan(s.on_low[i]) and np.isfinite(s.on_high[i - 1])
    assert integrity.basis_check(s, index)["status"] == "OK"


def test_undetected_roll_blocks_multisession_holds():
    f = causality.synth_frame(n_sessions=60, start="2025-02-03")
    a = bars.annotate(f)
    rolls = integrity.detect_rolls(a, None)            # no jump injected -> ROLL_NOT_DETECTED for 2025-03
    s = sessions.build_sessions(a)
    integrity.mark_sessions(s, rolls)
    i = list(s.dates).index(date(2025, 3, 10))
    assert ms.hold_trade(s, i, ms.CLOSE, i + 3, ms.CLOSE, 1) is None
    assert ms.hold_trade(s, 2, ms.CLOSE, 4, ms.CLOSE, 1) is not None


# ---------------- multi-session simulator ----------------
def test_hold_pnl_telescopes_and_costs_split():
    s = sessions.build_sessions(bars.annotate(causality.synth_frame(n_sessions=20)))
    t = ms.hold_trade(s, 3, slot_of("14:00"), 6, slot_of("13:55"), -1)
    res = ms.to_result([t], s, costs.MNQ)
    gross = -(s.O[6, slot_of("13:55")] - s.O[3, slot_of("14:00")])
    assert res.daily_net_pts.sum() == pytest.approx(gross - costs.MNQ.round_trip_points)
    assert res.daily_net_pts[[0, 1, 2, 7]].tolist() == [0, 0, 0, 0] and res.daily_net_pts[4] != 0
    c = ms.hold_trade(s, 2, ms.CLOSE, 3, ms.CLOSE, 1)
    r2_ = ms.to_result([c], s, costs.MNQ)
    assert r2_.daily_net_pts[2] == pytest.approx(-costs.MNQ.round_trip_points / 2)
    assert ms.hold_trade(s, 3, 10, 3, 10, 1) is None


def test_daily_weights_charges_entry_and_exit():
    ret = np.array([0.0, 0.01, 0.01, -0.02, 0.0])
    w = np.array([0, 0, 1, 1, 0], float)
    net = ms.daily_weights(ret, w, 2.0)
    assert net.tolist() == pytest.approx([0, -1e-4, 0.01, -0.02 - 1e-4, 0])


# ---------------- calendars ----------------
def test_fomc_calendar_and_month_ends():
    ev = events.fomc_events()
    assert len(ev) == 24 and all(e["first_day"].weekday() in (1, 2) for e in ev)
    assert date(2025, 8, 22) not in [e["decision"] for e in ev]
    d = [x.date() for x in pd.bdate_range("2025-01-02", "2025-04-15")]
    me = events.month_ends(d)
    assert [m["month"] for m in me] == ["2025-02", "2025-03"]              # Jan has no M0; April unfinished
    assert d[me[0]["t"]] == date(2025, 2, 28) and d[me[0]["m0"]] == date(2025, 1, 31)


# ---------------- R2-B month-end ----------------
def _daily_series(n=900, seed=5):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-02", periods=n)
    ndx = pd.Series(10000 * np.exp(np.cumsum(rng.normal(0, 0.012, n))), index=idx)
    y = pd.Series(2.5 + np.cumsum(rng.normal(0, 0.03, n)), index=idx)
    return ndx, y


def test_month_end_signal_uses_only_data_through_t_minus_6():
    ndx, y = _daily_series()
    base = {s["month"]: s["z"] for s in r2.month_end_signals(ndx, y)}
    sigs = r2.month_end_signals(ndx, y)
    s = sigs[10]
    ndx2, y2 = ndx.copy(), y.copy()
    ndx2.iloc[s["t"] - 5:s["t"] + 1] *= 1.3          # entry day .. T: must not move the signal
    y2.iloc[s["t"] - 6:s["t"] + 1] += 1.0             # bond leg uses <= T-7
    after = {x["month"]: x["z"] for x in r2.month_end_signals(ndx2, y2)}
    assert after[s["month"]] == pytest.approx(base[s["month"]])
    cut = ndx.index[sigs[15]["t"] + 3]
    trunc = {x["month"]: x["z"] for x in r2.month_end_signals(ndx[ndx.index <= cut], y[y.index <= cut])}
    for m, z in trunc.items():
        assert base[m] == pytest.approx(z)


def test_month_end_daily_variants_trade_against_signal():
    ndx, y = _daily_series()
    rec, diag, sigs = r2.month_end_daily(ndx, y, date(2026, 10, 5))
    assert set(rec) == set(r2.B_VARIANTS) and diag["signals"] == len(sigs)
    assert all(rec[v]["status"] in ("REJECTED", "CANDIDATE", "CHALLENGER", "CHAMPION") for v in rec)


# ---------------- R2-A / R2-C / R2-D ----------------
def test_eod_reversal_is_exact_mirror_and_vix_filter_subsets():
    s = sessions.build_sessions(bars.annotate(causality.synth_frame(n_sessions=90)))
    _vix(s)
    mom = hypotheses.eod_trades(s, "unconditional")
    rev = r2.eodrev_trades(s, "unconditional")
    assert [(t.day, -t.direction, t.entry_px, t.exit_px) for t in mom] == [(t.day, t.direction, t.entry_px, t.exit_px) for t in rev]
    assert {t.day for t in r2.eodrev_trades(s, "vix_low")} <= {t.day for t in rev}


def test_pre_fomc_hold_enters_1400_first_day_exits_1355_decision_day():
    s = sessions.build_sessions(bars.annotate(causality.synth_frame(n_sessions=120, start="2025-02-03")))
    trades, _ = r2.pre_fomc_trades(s)
    d = {t.exit_day: t for t in trades}
    i = list(s.dates).index(date(2025, 3, 19))
    t = d[i]
    assert t.day == i - 1 and t.entry_px == s.O[i - 1, slot_of("14:00")] and t.exit_px == s.O[i, slot_of("13:55")]
    st = r2.event_study(s, costs.MNQ, date(2026, 10, 5))
    assert st["status"] == "INSUFFICIENT_SAMPLE" and st["events"] == len(trades)


def test_flow_rules_are_causal():
    f = causality.synth_frame(n_sessions=140)
    for w, dirn in (("open30", "cont"), ("morning", "rev")):
        fn = lambda s, w=w, dirn=dirn: r2.flow_trades(s, w, dirn)
        assert causality.prefix_violations(f, fn, prepare=_tb) == []
        assert causality.intraday_violations(f, fn, [(100, slot_of(r2.D_WINDOWS[w])), (130, 40)], prepare=_tb) == []
    s = sessions.build_sessions(bars.annotate(f))
    _tb(s)
    tr = r2.flow_trades(s, "open30", "cont")
    imb = r2.flow_imbalance(s, "open30")
    assert tr and all(t.direction == np.sign(imb[t.day]) for t in tr)


# ---------------- cl-ml1 ----------------
def test_logistic_fit_recovers_signal():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(400, 3))
    y = (X[:, 0] - 0.5 * X[:, 2] + rng.normal(0, 0.5, 400) > 0).astype(float)
    b = ml.fit_logistic(X, y, alpha=0.01)
    assert b[1] > 0.5 and b[3] < -0.2 and abs(b[2]) < 0.3


def _ml_prepare(s):
    _vix(s)
    s.cache["ml_kind"] = "futures"


def test_ml_walk_forward_is_causal_and_leak_control_is_caught():
    f = causality.synth_frame(n_sessions=200)
    k = slot_of("12:00")
    clean = lambda s: ml.ml_trades(s, k)
    leaky = lambda s: ml.ml_trades(s, k, leak=True)
    assert causality.prefix_violations(f, clean, cuts=(150, 180), prepare=_ml_prepare) == []
    pairs = [(d, k) for d in range(150, 200, 7)]
    assert causality.intraday_violations(f, clean, pairs, prepare=_ml_prepare) == []
    assert causality.intraday_violations(f, leaky, pairs, prepare=_ml_prepare) != []
    s = sessions.build_sessions(bars.annotate(f))
    _ml_prepare(s)
    q = ml.qualify(ml.CANDIDATES[1], s, costs.MNQ, "points", date(2026, 10, 5))
    assert q["refits"] >= 1 and q["permutation_control"]["flag"] in ("OK", "HARNESS_SUSPECT")


def test_ml_unavailable_without_vix():
    s = sessions.build_sessions(bars.annotate(causality.synth_frame(n_sessions=40)))
    assert ml.ml_trades(s, slot_of("10:00")) == []
    assert ml.qualify(ml.CANDIDATES[0], s, costs.MNQ, "points", date(2026, 10, 5))["status"] == "UNAVAILABLE"


# ---------------- pre-registration ----------------
def test_prereg_registry_matches_code():
    p = os.path.join(os.path.dirname(r2.__file__), "prereg_r2.json")
    reg = json.load(open(p, encoding="utf-8"))
    assert reg["r2"] == r2.prereg_manifest() and reg["ml"] == ml.prereg_manifest()
    assert reg["data_version"] == integrity.DATA_VERSION and reg["execution_authorized"] is False
