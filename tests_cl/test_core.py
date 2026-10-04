# CL (Claude, Anthropic) — 2026-10-03 — tests for cl_lab bars/sessions/backtest/grammar (causality first)
"""Causality is the contract: cross-day prefix invariance, intraday truncation
invariance (with a leaky positive control that must be caught), known-answer
trades and stable pre-registration ids."""
import numpy as np
import pandas as pd
import pytest

from cl_lab import backtest, bars, costs, grammar, sessions
from cl_lab.backtest import bracket_trade, simulate_bracket
from cl_lab.sessions import slot_of

ET = "America/New_York"


def synth_frame(n_sessions=140, seed=3, start="2025-02-03"):
    """Random-walk 5m bars, 18:00 ET prior evening -> 17:00 ET, weekdays, spanning the March DST change."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_sessions)
    stamps, px, rows = [], 20000.0, []
    for d in days:
        t0 = pd.Timestamp(d.date()) - pd.Timedelta(hours=6)  # 18:00 ET previous evening
        for k in range(276):
            stamps.append((t0 + pd.Timedelta(minutes=5 * k)).tz_localize(ET))
            o = px
            c = round((o + rng.normal(0, 3.0)) * 4) / 4
            h = max(o, c) + round(abs(rng.normal(0, 1.5)) * 4) / 4
            lo = min(o, c) - round(abs(rng.normal(0, 1.5)) * 4) / 4
            rows.append((o, h, lo, c, float(rng.integers(50, 500))))
            px = c
    df = pd.DataFrame(rows, columns=list(bars.COLUMNS))
    df.index = pd.DatetimeIndex(stamps).tz_convert("UTC").rename("ts_open")
    return df


@pytest.fixture(scope="module")
def frame():
    return synth_frame()


@pytest.fixture(scope="module")
def sess(frame):
    return sessions.build_sessions(bars.annotate(frame))


def test_load_csv_close_stamp_shift(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("ts,open,high,low,close,volume\n2025-01-06T23:05:00+00:00,1,2,0.5,1.5,10\n"
                 "2025-01-06T23:10:00+00:00,1.5,2,1,1.75,11\n")
    df = bars.load_csv(p)
    assert str(df.index[0]) == "2025-01-06 23:00:00+00:00"
    a = bars.annotate(df)
    assert a["minute_et"].iloc[0] == 18 * 60 and str(a["session_date"].iloc[0]) == "2025-01-07"


def test_rth_flags_follow_dst():
    idx = pd.DatetimeIndex(["2025-03-07 14:30", "2025-03-10 13:30", "2025-03-10 14:25"], tz="UTC", name="ts_open")
    df = pd.DataFrame({c: 1.0 for c in bars.COLUMNS}, index=idx)
    a = bars.annotate(df)
    assert list(a["rth"]) == [True, True, True]
    assert list(a["minute_et"]) == [570, 570, 625]


def test_sunday_evening_bar_belongs_to_monday():
    idx = pd.DatetimeIndex([pd.Timestamp("2025-03-09 18:00", tz=ET).tz_convert("UTC")], name="ts_open")
    a = bars.annotate(pd.DataFrame({c: 1.0 for c in bars.COLUMNS}, index=idx))
    assert str(a["session_date"].iloc[0]) == "2025-03-10"


def test_slots_and_session_context(sess, frame):
    assert (slot_of("09:30"), slot_of("10:00"), slot_of("15:30"), slot_of("15:55")) == (0, 6, 72, 77)
    assert sess.complete.all() and sess.D == 140
    d = 37
    tp = (sess.H[d] + sess.L[d] + sess.C[d]) / 3
    np.testing.assert_allclose(sess.vwap[d], np.cumsum(tp * sess.V[d]) / np.cumsum(sess.V[d]))
    assert sess.prev_close[d] == sess.C[d - 1, 77]
    assert sess.prev_high[d] == sess.H[d - 1].max() and np.isnan(sess.atr14[:14]).all()
    a = bars.annotate(frame)
    on = a[(a.session_date == sess.dates[d]) & ~a.rth & ((a.minute_et < 570) | (a.minute_et >= 1080))]
    assert sess.on_high[d] == on.high.max() and sess.on_close[d] == on.close.iloc[-1]
    assert on.minute_et.iloc[-1] == 9 * 60 + 25


def test_bracket_stop_first_gap_and_target(sess):
    s = sessions.Sessions(**{k: (v.copy() if isinstance(v, np.ndarray) else v)
                            for k, v in sess.__dict__.items() if k != "cache"})
    d = 50
    s.O[d, 10:13], s.H[d, 10:13], s.L[d, 10:13], s.C[d, 10:13] = 100, 101, 99, 100
    s.H[d, 11], s.L[d, 11] = 110, 90                       # touches both -> stop
    assert simulate_bracket(s, d, 10, 1, stop=95, target=105) == (11, 95, "stop")
    s.H[d, 11], s.L[d, 11] = 106, 99.5                     # target only
    assert simulate_bracket(s, d, 10, 1, stop=95, target=105) == (11, 105, "target")
    s.O[d, 11], s.L[d, 11] = 94, 93                        # opens through the stop -> fill at open
    assert simulate_bracket(s, d, 10, 1, stop=95, target=105)[:2] == (11, 94)
    assert simulate_bracket(s, d, 70, -1)[2] == "eod"


def test_imom_matches_independent_computation(sess):
    p = dict(base="prevclose", t1="10:00", entry="15:30", min_abs="none", regime="all")
    got = grammar.FAMILIES["imom"].trades(sess, p)
    want = []
    for d in range(sess.D):
        r = sess.C[d, 5] / sess.prev_close[d] - 1
        if np.isfinite(r) and r != 0:
            dr = 1 if r > 0 else -1
            want.append((d, 72, sess.O[d, 72], 78, sess.C[d, 77], dr))
    assert [(t.day, t.entry_slot, t.entry_px, t.exit_slot, t.exit_px, t.direction) for t in got] == want


def test_gap_fill_and_first_candle_orb_rules(sess):
    t = grammar.FAMILIES["gap"].trades(sess, dict(thr="q50", mode="fade", exit="fill", regime="all"))
    assert t and all(tr.entry_slot == 0 for tr in t)
    for tr in t:
        g = sess.on_close[tr.day] / sess.prev_close[tr.day] - 1
        assert tr.direction == -np.sign(g)
        if tr.reason == "target":
            assert tr.exit_px == sess.prev_close[tr.day] or tr.exit_px == sess.O[tr.day, tr.exit_slot]
    o = grammar.FAMILIES["orb"].trades(sess, dict(or_min=5, entry_mode="first_candle_dir", stop="candle",
                                                   target="eod", side="both", regime="all"))
    for tr in o:
        assert tr.entry_slot == 1 and tr.direction == np.sign(sess.C[tr.day, 0] - sess.O[tr.day, 0])


def _key(trs, upto_day=None, max_entry=None, day=None):
    out = []
    for t in trs:
        if upto_day is not None and t.day >= upto_day:
            continue
        if day is not None and (t.day != day or t.entry_slot > max_entry):
            continue
        out.append((t.day, t.entry_slot, t.direction, t.entry_px) if day is not None else tuple(t.__dict__.values()))
    return out


def test_cross_day_prefix_invariance_every_candidate(frame, sess):
    a = bars.annotate(frame)
    cands = grammar.enumerate_candidates()
    for K in (90, 120):
        keep = set(sess.dates[:K])
        short = sessions.build_sessions(a[a.session_date.isin(keep)])
        for c in cands:
            fam, p = grammar.FAMILIES[c.family], dict(c.params)
            assert _key(fam.trades(short, p), upto_day=K) == _key(fam.trades(sess, p), upto_day=K), c.spec()


def _garbage(a, date, s, rng):
    m = (a.session_date == date) & a.rth & (((a.minute_et - 570) // 5) > s)
    a = a.copy()
    n = int(m.sum())
    base = rng.uniform(15000, 25000, n)
    a.loc[m, "open"], a.loc[m, "close"] = base, base + rng.normal(0, 50, n)
    a.loc[m, "high"] = np.maximum(a.loc[m, "open"], a.loc[m, "close"]) + 30
    a.loc[m, "low"] = np.minimum(a.loc[m, "open"], a.loc[m, "close"]) - 30
    a.loc[m, "volume"] = rng.integers(1, 10_000, n).astype(float)
    return a


def _intraday_violations(frame, sess, trade_fns, pairs):
    a0, rng, bad = bars.annotate(frame), np.random.default_rng(99), []
    for d, s in pairs:
        s2 = sessions.build_sessions(_garbage(a0, sess.dates[d], s, rng))
        for name, fn in trade_fns:
            if _key(fn(sess), max_entry=s, day=d) != _key(fn(s2), max_entry=s, day=d):
                bad.append((name, d, s))
    return bad


PAIRS = [(60, 0), (70, 5), (80, 11), (95, 23), (100, 40), (110, 60), (120, 71), (130, 76)]


def test_intraday_truncation_invariance_every_candidate(frame, sess):
    fns = [(c.id, (lambda f, p: (lambda S: f.trades(S, p)))(grammar.FAMILIES[c.family], dict(c.params)))
           for c in grammar.enumerate_candidates()]
    assert _intraday_violations(frame, sess, fns, PAIRS) == []


def test_positive_control_leak_is_detected(frame, sess):
    def leaky(S):
        return [bracket_trade(S, d, 0, 1 if S.C[d, 77] > S.O[d, 0] else -1) for d in range(S.D) if S.complete[d]]
    assert _intraday_violations(frame, sess, [("leaky", leaky)], PAIRS[:4])


def test_registration_is_deterministic_and_unique():
    a, b = grammar.enumerate_candidates(), grammar.enumerate_candidates()
    assert [c.id for c in a] == [c.id for c in b]
    assert len({c.id for c in a}) == len(a) == 492
    assert grammar.registration_hash(a) == grammar.registration_hash(b)


def test_costs_and_result_aggregation(sess):
    assert costs.MNQ.round_trip_points == pytest.approx(2 * 0.85 / 2 + 2 * 0.25)
    c = grammar.enumerate_candidates(["vwap"])[0]
    r = backtest.run(c, sess, costs.MNQ)
    assert r.n_trades > 0 and r.daily_net_pts.sum() == pytest.approx(r.trades.net_pts.sum())
    assert backtest.summary(r)["n_trades"] == r.n_trades
