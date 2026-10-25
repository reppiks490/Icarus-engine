# CL (Claude, Anthropic) — 2026-10-11 — FR-1 required tests (docs/FRONTIER_PREREG_FR1.md §9), synthetic data only
import json
import math
import multiprocessing as mp
import os
import time

import numpy as np
import pandas as pd
import pytest

from cl_lab import bars, frontier as fr, grammar, integrity, sessions, trial_ledger

ET = "America/New_York"


# --------------------------------------------------------------------------- synthetic raw tapes

def make_adf(start="2024-03-01", n_days=60, seed=1, sd_ticks=8, rolls=(), drift=None, drift_ticks=6,
             drift_bars=6, base=20000.0, with_iid=True):
    """Annotated RAW tape: 12 overnight bars (19:00-19:55 ET the evening before) + 78 RTH bars per session.
    ``rolls``: (session index, delta) — the new contract starts at that session's first overnight bar and
    trades ``delta`` higher (instrument_id changes there). ``drift``: {(session index, bar): direction} adds
    ``drift_ticks`` per bar for ``drift_bars`` RTH bars starting at that bar."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_days)
    roll_at = dict(rolls)
    drift = drift or {}
    rows, idx, iid = [], [], []
    px, contract, shift = base, 1, 0.0
    for di, day in enumerate(days):
        prev_eve = (day - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        stamps = [pd.Timestamp(f"{prev_eve} 19:00", tz=ET) + pd.Timedelta(minutes=5 * k) for k in range(12)]
        stamps += [pd.Timestamp(f"{day.strftime('%Y-%m-%d')} 09:30", tz=ET) + pd.Timedelta(minutes=5 * k) for k in range(78)]
        for b, ts in enumerate(stamps):
            o = px
            if b == 0 and di in roll_at:
                contract += 1
                o = px + roll_at[di]
            step = rng.normal(0.0, sd_ticks) * 0.25
            j = b - 12
            for (dd, start_bar), sgn in drift.items():
                if dd == di and start_bar <= j < start_bar + drift_bars:
                    step += sgn * drift_ticks * 0.25
            c = o + step
            h = max(o, c) + abs(rng.normal(0.0, 2)) * 0.25
            lo = min(o, c) - abs(rng.normal(0.0, 2)) * 0.25
            q = lambda x: round(x / 0.25) * 0.25
            rows.append((q(o), q(h), q(lo), q(c), 1.0))
            idx.append(ts.tz_convert("UTC"))
            iid.append(contract)
            px = q(c)
    df = pd.DataFrame(rows, columns=list(bars.COLUMNS), index=pd.DatetimeIndex(idx, name="ts_open"))
    df["open"] = np.minimum(np.maximum(df["open"], df["low"]), df["high"])
    if with_iid:
        df["instrument_id"] = iid
    return bars.annotate(df)


def tape_of(adf, ix=None):
    return fr.build_tape(adf, ix)


def truncate(adf, last_date):
    return adf[adf["session_date"] <= last_date]


def one_day_tape(O, H, L, C):
    """A Tape holding one session of hand-written bars (78 slots; unspecified slots repeat the last close)."""
    arr = {k: np.full((1, 78), np.nan) for k in "OHLC"}
    for k, v in zip("OHLC", (O, H, L, C)):
        arr[k][0, :len(v)] = v
        arr[k][0, len(v):] = C[-1]
    return fr.Tape(adf=pd.DataFrame(), index_close=None, dates=np.array([pd.Timestamp("2025-01-02").date()]),
                   O=arr["O"], H=arr["H"], L=arr["L"], C=arr["C"], P=np.zeros((1, 78), dtype=np.int64),
                   rth_start=np.zeros(1, dtype=np.int64), complete=np.ones(1, bool))


def sim1(tape, e, dirn, tp, sl, nb):
    r = fr.simulate(tape, [0], [e], [dirn], [tp], [sl], [nb])
    return {k: v[0] for k, v in r.items()}


# --------------------------------------------------------------------------- §9.1 causality from raw input

def test_context_matches_sessions_and_noiseboundary_without_rolls():
    adf = make_adf(n_days=40, with_iid=False)
    tape = tape_of(adf)
    ctx = fr.build_context(tape, (10, 14))
    sess = sessions.build_sessions(adf)
    assert list(sess.dates) == list(tape.dates)
    np.testing.assert_allclose(ctx.prev_close, sess.prev_close, equal_nan=True)
    np.testing.assert_allclose(ctx.atr14, sess.atr14, equal_nan=True)
    for lb in (10, 14):
        np.testing.assert_allclose(ctx.sigma[lb], grammar.NoiseBoundary.sigma(sess, lb), equal_nan=True)


def test_as_of_view_shifts_history_into_the_days_contract_and_keeps_the_day_raw():
    delta = 150.0
    adf = make_adf(n_days=40, rolls=[(25, delta)])
    tape = tape_of(adf)
    ctx = fr.build_context(tape, (10,))
    raw = sessions.build_sessions(adf)
    # day 25 is the first new-contract session: the switch sits in its overnight, known before its RTH
    assert ctx.switches_known[25] == 1 and ctx.switches_known[24] == 0
    assert ctx.prev_close[25] == pytest.approx(raw.prev_close[25] + delta)
    assert ctx.prev_close[24] == pytest.approx(raw.prev_close[24])
    # day 30: history fully in the new contract equals the back-adjusted tape's context
    adj = sessions.build_sessions(integrity.back_adjust(adf, integrity.detect_rolls(adf)))
    for d in (30, 35, 39):
        assert ctx.prev_close[d] == pytest.approx(adj.prev_close[d])
        assert ctx.atr14[d] == pytest.approx(adj.atr14[d])
        np.testing.assert_allclose(ctx.sigma[10][d], grammar.NoiseBoundary.sigma(adj, 10)[d])
    # every RTH price a trade uses is raw
    assert np.array_equal(tape.O, raw.O, equal_nan=True) and np.array_equal(tape.C, raw.C, equal_nan=True)


def _all_results(adf, g, n_sets=20):
    tape = tape_of(adf)
    ctx = fr.build_context(tape, (10,))
    sig = fr.signals(tape, ctx, fr.SOURCES["S1"])
    real = fr.real_trades(tape, ctx, sig, g)
    nul = fr.null_trades(tape, ctx, real, g, "005e61b86b3d", n_sets)
    return tape, ctx, sig, real, nul


def test_truncating_the_raw_tape_after_day_d_changes_nothing_up_to_d():
    adf = make_adf(n_days=70, rolls=[(30, 120.0), (55, -80.0)], seed=3, sd_ticks=14)
    g = dict(tp=0.05, sl=0.20, T=120)
    tape, ctx, sig, real, nul = _all_results(adf, g)
    for cut in (40, 54, 60):
        d_last = tape.dates[cut]
        t2, c2, s2, r2, n2 = _all_results(truncate(adf, d_last), g)
        np.testing.assert_array_equal(c2.prev_close, ctx.prev_close[:cut + 1])
        np.testing.assert_array_equal(c2.atr14, ctx.atr14[:cut + 1])
        np.testing.assert_array_equal(c2.sigma[10], ctx.sigma[10][:cut + 1])
        np.testing.assert_array_equal(s2, sig[:cut + 1])
        keep = real["d"] <= cut
        for k in ("d", "e", "dir", "k", "reason"):
            np.testing.assert_array_equal(r2[k], real[k][keep])
        np.testing.assert_array_equal(r2["gross"], real["gross"][keep])
        n = keep.sum()
        np.testing.assert_array_equal(n2["e"], nul["e"][:, :n])
        np.testing.assert_array_equal(n2["net"], nul["net"][:, :n])


def test_a_synthetic_roll_after_day_d_changes_nothing_about_day_d():
    g = dict(tp=0.035, sl=0.10, T=60)
    a = make_adf(n_days=60, seed=5, sd_ticks=14)
    b = make_adf(n_days=60, seed=5, sd_ticks=14, rolls=[(45, 200.0)])
    ta, ca, sa, ra, na = _all_results(a, g)
    tb, cb, sb, rb, nb_ = _all_results(b, g)
    upto = 44
    np.testing.assert_array_equal(cb.prev_close[:upto + 1], ca.prev_close[:upto + 1])
    np.testing.assert_array_equal(cb.sigma[10][:upto + 1], ca.sigma[10][:upto + 1])
    np.testing.assert_array_equal(sb[:upto + 1], sa[:upto + 1])
    ka, kb = ra["d"] <= upto, rb["d"] <= upto
    np.testing.assert_array_equal(rb["gross"][kb], ra["gross"][ka])
    assert ca.prev_close[46] != cb.prev_close[46]          # the roll is real after it happens


def test_signals_use_closed_bars_only():
    adf = make_adf(n_days=40, seed=7, sd_ticks=20)
    tape = tape_of(adf)
    ctx = fr.build_context(tape, (10,))
    sig = fr.signals(tape, ctx, fr.SOURCES["S1"])
    d = int(np.flatnonzero((sig != 0).any(axis=1))[-1])
    j = int(np.flatnonzero(sig[d])[0])
    tape.C[d, j + 1:] += 500.0                                # rewrite everything after check j
    tape.H[d, j + 1:] += 500.0
    tape.L[d, j + 1:] -= 500.0
    sig2 = fr.signals(tape, ctx, fr.SOURCES["S1"])
    np.testing.assert_array_equal(sig2[d, :j + 1], sig[d, :j + 1])


# --------------------------------------------------------------------------- §9.2 fills

def test_target_needs_trade_through_and_touch_is_not_a_fill():
    O = [100.0] * 10
    H = [100.0, 101.0, 101.25, 100.0, 100, 100, 100, 100, 100, 100]
    L = [99.75] * 10
    C = [100.0] * 10
    t = one_day_tape(O, H, L, C)
    r = sim1(t, 0, 1, 4, 40, 48)                               # target 101.00: touched in bar 1, through in 2
    assert r["reason"] == 0 and r["k"] == 2 and r["exit"] == 101.0 and r["hold"] == 15


def test_gapped_stop_fills_at_the_open_and_favourable_gap_at_the_target():
    O = [100.0, 100.0, 97.0, 100.0]
    H = [100.25, 100.25, 97.5, 100.0]
    L = [99.75, 99.75, 96.0, 100.0]
    C = [100.0, 100.0, 97.0, 100.0]
    r = sim1(one_day_tape(O, H, L, C), 0, 1, 40, 8, 48)       # stop 98.00, bar 2 opens at 97.00
    assert r["reason"] == 1 and r["exit"] == 97.0 and r["k"] == 2
    O = [100.0, 100.0, 104.0]
    H = [100.25, 100.25, 104.5]
    L = [99.75, 99.75, 103.5]
    C = [100.0, 100.0, 104.0]
    r = sim1(one_day_tape(O, H, L, C), 0, 1, 8, 40, 48)       # target 102.00, bar 2 opens at 104.00
    assert r["reason"] == 0 and r["exit"] == 102.0
    r = sim1(one_day_tape(O, H, L, C), 0, -1, 40, 8, 48)      # short: stop 102.00 gapped at 104.00
    assert r["reason"] == 1 and r["exit"] == 104.0


def test_bar_reaching_both_is_the_stop():
    O = [100.0, 100.0]
    H = [100.25, 103.0]
    L = [99.75, 97.0]
    C = [100.0, 100.0]
    r = sim1(one_day_tape(O, H, L, C), 0, 1, 4, 4, 48)
    assert r["reason"] == 1 and r["exit"] == 99.0 and r["k"] == 1


def test_tick_rounding_is_up_on_the_grid_and_at_least_one():
    assert fr.ticks(1.0) == 4 and fr.ticks(1.01) == 5 and fr.ticks(0.0) == 1 and fr.ticks(0.26) == 2
    assert fr.ticks(0.05 * 20.0) == 4                          # float product of an exact multiple
    t = one_day_tape([100.0] * 3, [100.25] * 3, [99.75] * 3, [100.0] * 3)
    r = fr.simulate(t, [0], [0], [1], [fr.ticks(0.3)], [fr.ticks(0.3)], [48])
    assert (r["exit"][0] - 100.0) % 0.25 == 0


def test_time_stop_end_of_day_and_hold_minutes():
    flat = one_day_tape([100.0] * 78, [100.25] * 78, [99.75] * 78, [100.0] * 78)
    r = sim1(flat, 10, 1, 40, 40, 12)                          # T = 60 min: time stop at the open of bar 22
    assert r["reason"] == 2 and r["k"] == 22 and r["hold"] == 60
    r = sim1(flat, 70, 1, 40, 40, 48)                          # runs past the day: end of day at bar 77's close
    assert r["reason"] == 3 and r["k"] == 77 and r["hold"] == 5 * (78 - 70)
    r = sim1(flat, 66, 1, 40, 40, 12)                          # e + T/5 = 78: no bar 78, so end of day
    assert r["reason"] == 3 and r["hold"] == 60


# --------------------------------------------------------------------------- §9.3 occupancy

def test_occupancy_no_overlap_opposites_ignored_and_reentry_after_exit():
    adf = make_adf(n_days=30, seed=11)
    tape = tape_of(adf)
    ctx = fr.build_context(tape, (10,))
    d = int(np.flatnonzero(np.isfinite(ctx.atr14) & tape.complete)[0])
    sig = np.zeros((tape.D, 78), dtype=np.int8)
    sig[d, 5], sig[d, 11], sig[d, 17], sig[d, 23] = 1, -1, -1, 1
    tape.O[d], tape.H[d], tape.L[d], tape.C[d] = 100.0, 100.25, 99.75, 100.0   # flat day: only time stops
    real = fr.real_trades(tape, ctx, sig, dict(tp=0.08, sl=0.35, T=60))
    on = real["d"] == d
    e, k, dirs = real["e"][on], real["k"][on], real["dir"][on]
    assert e[0] == 6 and k[0] == 18 and dirs[0] == 1           # opposite signal at 11 and the one at 17 ignored
    assert e[1] == 24 and dirs[1] == 1                         # first check after the exit bar is 23
    assert all(e[i + 1] > k[i] for i in range(len(e) - 1))


def test_null_obeys_occupancy_and_buckets():
    adf = make_adf(n_days=50, seed=13, sd_ticks=16)
    g = dict(tp=0.05, sl=0.10, T=240)
    tape, ctx, sig, real, nul = _all_results(adf, g, n_sets=50)
    assert len(real["d"]) > 10
    for s in range(50):
        for i in range(len(real["d"])):
            if not nul["taken"][s, i]:
                continue
            b = real["e"][i] // fr.BUCKET
            assert b * fr.BUCKET <= nul["e"][s, i] <= min(b * fr.BUCKET + 11, 77)
            prev = [j for j in range(i) if real["d"][j] == real["d"][i] and nul["taken"][s, j]]
            if prev:
                assert nul["e"][s, i] > nul["k"][s, prev[-1]]


# --------------------------------------------------------------------------- §9.4 / §9.5 planted edge vs none

def _injected(n_days, seed, planted, start="2025-06-02"):
    rng = np.random.default_rng(seed)
    plan = {}
    for di in range(n_days):
        for j in sorted(rng.choice([5, 23, 41, 59], size=2, replace=False)):
            plan[(di, int(j))] = int(rng.choice([-1, 1]))
    drift = {(di, j + 1): s for (di, j), s in plan.items()} if planted else None
    adf = make_adf(start=start, n_days=n_days, seed=seed, sd_ticks=12, drift=drift, drift_ticks=12, with_iid=False)
    tape = tape_of(adf)
    sig = np.zeros((tape.D, 78), dtype=np.int8)
    for (di, j), s in plan.items():
        sig[di, j] = s
    return tape, sig


def test_planted_edge_is_selected_with_a_small_null_p_and_confirmed_on_hold():
    tape, sig = _injected(170, 21, planted=True)
    res = fr.evaluate(tape, dict(total=0), n_sets=200, sources={"P": dict(id="planted", lookback=10, signals=sig)})
    r = res["sources"]["P"]
    assert r["eligible"] >= 1 and r["status"] == "HOLD_CONFIRMED"
    sel = r["selected_tune"]
    assert sel["win_rate"] >= 0.82 and sel["trades"] >= 100 and sel["null"]["p"] <= 0.05
    assert r["hold"]["null"]["p"] <= 0.05


def test_no_edge_no_confirmation():
    tape, sig = _injected(170, 22, planted=False)
    res = fr.evaluate(tape, dict(total=0), n_sets=200, sources={"R": dict(id="random", lookback=10, signals=sig)})
    assert res["sources"]["R"]["status"] in ("NO_REGION", "REJECTED")


# --------------------------------------------------------------------------- §9.6 the null p-value

def test_null_p_is_b_plus_one_over_n_plus_one_with_ties_against():
    nulls = np.r_[np.full(190, 0.5), np.full(10, 1.0)]
    assert fr.null_p(1.0, nulls) == (11 / 201, 10)
    assert fr.null_p(2.0, np.zeros(200)) == (1 / 201, 0)      # never 0
    assert fr.null_p(1.0, np.r_[np.full(199, 0.0), np.nan])[1] == 1   # an empty set counts against
    assert fr.null_p(1.0, np.zeros(200))[0] <= 0.05 and fr.null_p(1.0, np.r_[np.zeros(190), np.ones(10)])[0] > 0.05


# --------------------------------------------------------------------------- §9.7 ledger

def _fake_sources(root, n_rules=492, n_explore=2160):
    cl = root / trial_ledger.CL
    (cl / "history").mkdir(parents=True)
    (cl / "candidates_latest.jsonl").write_text("".join(json.dumps(dict(asset="MNQ", id=f"r{i}", t=0.1, run_id="cl-lab-1")) + "\n"
                                                        for i in range(n_rules)))
    summary = dict(run_id="cl-lab-1", candidates=n_rules,
                   assets={"MNQ": dict(status="EVALUATED", diagnostics=dict(candidates=n_rules))})
    (cl / "latest.json").write_text(json.dumps(summary))
    (cl / "history" / "cl-lab-1.json").write_text(json.dumps(summary))
    (cl / "explore_ledger.jsonl").write_text("".join(json.dumps(dict(asset="MNQ", id=f"x{i}")) + "\n"
                                                     for i in range(n_explore)))
    (cl / "boos_records.jsonl").write_text(json.dumps(dict(family="cl-g1", id="b1")) + "\n")
    (cl / "boos_latest.json").write_text(json.dumps(dict(records=1, fingerprint="synthetic-boos")))
    (cl / "pulse_latest.json").write_text(json.dumps(dict(fingerprint="synthetic-pulse", variants=dict(A={}, B={}))))
    (cl / "depth_d1_latest.json").write_text(json.dumps({"D1-A": dict(status="INSUFFICIENT_DATA"),
                                                          "D1-B": dict(status="EVALUATED", p=0.4),
                                                          "fingerprint": "synthetic-depth"}))
    return cl


def test_ledger_import_is_idempotent_and_snapshot_is_stable(tmp_path):
    _fake_sources(tmp_path)
    led = tmp_path / "ledger.jsonl"
    a = trial_ledger.import_historical(tmp_path, led)
    assert a["status"] == "OK" and a["added"] == 492 + 2160 + 1 + 2 + 1
    s1 = trial_ledger.snapshot(led)
    b = trial_ledger.import_historical(tmp_path, led)
    assert b["added"] == 0 and trial_ledger.snapshot(led) == s1
    assert s1["by_source"]["depth-d1"] == 1                    # only the D1 test that has run


def test_unreadable_or_short_sources_block(tmp_path):
    cl = _fake_sources(tmp_path)
    (cl / "explore_ledger.jsonl").write_text("{not json\n")
    r = trial_ledger.import_historical(tmp_path, tmp_path / "l.jsonl")
    assert r["status"] == "BLOCKED" and not (tmp_path / "l.jsonl").exists()
    other = tmp_path / "o"
    _fake_sources(other, n_explore=2000)
    r = trial_ledger.import_historical(other, other / "l.jsonl")
    assert r["status"] == "BLOCKED" and "2160" in r["blockers"][0]


def test_run_is_blocked_before_any_computation_when_a_source_is_missing(tmp_path, monkeypatch):
    _fake_sources(tmp_path)
    (tmp_path / trial_ledger.CL / "pulse_latest.json").unlink()
    called = []
    monkeypatch.setattr(fr, "load_raw_mnq", lambda *a, **k: called.append(1))
    out = fr.run(str(tmp_path / "cache"), str(tmp_path / "out.json"), str(tmp_path / "l.jsonl"), root=str(tmp_path),
                 snapshot_path=str(tmp_path / "snap.json"))
    assert out["status"] == "BLOCKED" and called == []
    assert json.loads((tmp_path / "out.json").read_text())["status"] == "BLOCKED"


def _concurrent_run_worker(root, out_path, ledger_path, snapshot_path, active_path, overlap, start_barrier):
    """Run against synthetic sources while marking the real run's loader boundary."""
    def slow_synthetic_loader(*_args, **_kwargs):
        try:
            fd = os.open(active_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            owns_marker = True
        except FileExistsError:
            overlap.set()
            fd = None
            owns_marker = False
        time.sleep(0.25)
        if fd is not None:
            os.close(fd)
        if owns_marker:
            os.unlink(active_path)
        return make_adf(start="2024-03-01", n_days=60, seed=81), None, {}

    fr.load_raw_mnq = slow_synthetic_loader
    start_barrier.wait(timeout=10)
    result = fr.run("unused", out_path, ledger_path, root=root, snapshot_path=snapshot_path, n_sets=2)
    if result["status"] != "EVALUATED":
        raise AssertionError(f"synthetic run did not complete: {result}")


def test_complete_fr1_runs_are_serialized_across_processes(tmp_path):
    pytest.importorskip("fcntl")  # The research ledger currently requires a POSIX advisory lock.
    _fake_sources(tmp_path)
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    overlap = ctx.Event()
    paths = [str(tmp_path / name) for name in ("out.json", "ledger.jsonl", "snapshot.json", "active")]
    workers = [ctx.Process(target=_concurrent_run_worker,
                           args=(str(tmp_path), *paths, overlap, barrier)) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
        if worker.is_alive():
            worker.terminate()
            worker.join()
    assert [worker.exitcode for worker in workers] == [0, 0]
    assert not overlap.is_set(), "two complete FR-1 runs entered their source/evaluation phase together"


def test_rerun_of_unchanged_inputs_adds_no_fr1_trials(tmp_path):
    tape, sig = _injected(60, 31, planted=True, start="2025-07-01")
    src = {"P": dict(id="planted", lookback=10, signals=sig)}
    a = fr.evaluate(tape, dict(total=0), n_sets=20, sources=src)
    led = tmp_path / "l.jsonl"
    first = trial_ledger.append(led, a["trials"])
    assert first == len(fr.geometries()) + (1 if "hold" in a["sources"]["P"] else 0)
    b = fr.evaluate(tape, dict(total=0), n_sets=20, sources=src)
    assert trial_ledger.append(led, b["trials"]) == 0


# --------------------------------------------------------------------------- §9.8 determinism

def test_same_inputs_same_null_draws_and_results():
    adf = make_adf(n_days=45, seed=41, sd_ticks=16)
    g = dict(tp=0.02, sl=0.20, T=60)
    a = _all_results(adf, g, n_sets=30)
    b = _all_results(adf, g, n_sets=30)
    for k in ("e", "net", "taken"):
        np.testing.assert_array_equal(a[4][k], b[4][k])
    np.testing.assert_array_equal(a[3]["gross"], b[3]["gross"])
    assert fr.null_seed("005e61b86b3d", g, 0) != fr.null_seed("005e61b86b3d", g, 1)
    assert fr.null_seed("005e61b86b3d", g, 0) != fr.null_seed("c00aeb927f0b", g, 0)


def test_selection_ties_prefer_smaller_stop_then_target_then_time():
    order = [(g["sl"], g["tp"], g["T"]) for g in fr.geometries()]
    assert order == sorted(order) and len(order) == 60


@pytest.mark.parametrize('change', ['instrument_id', 'overnight', 'index_close', 'prior_window'])
def test_data_version_binds_causal_inputs(change):
    a = make_adf(start='2025-08-01', n_days=65, seed=3, rolls=[(25, 150.)])
    ix = pd.Series(np.arange(65, dtype=float), index=pd.bdate_range('2025-08-01', periods=65))
    before = fr.build_tape(a, ix)
    b, other_ix = a.copy(), ix.copy()
    if change == 'instrument_id':
        b['instrument_id'] = 1
    elif change == 'overnight':
        b.loc[b.index[0], 'open'] += 1
    elif change == 'index_close':
        other_ix.iloc[20] += 10
    else:
        # HOLD geometry depends on TUNE's trailing history even if HOLD OHLC is unchanged.
        stamp = b[(b.session_date < fr.HOLD_START) & b.rth].index[-1]
        b.loc[stamp, 'high'] += 10
    win = 'HOLD' if change == 'prior_window' else 'TUNE'
    assert fr.data_version(before, win) != fr.data_version(fr.build_tape(b, other_ix), win)


def test_future_extension_preserves_tune_and_hold_versions():
    a = make_adf(start='2025-09-01', n_days=310, seed=8)
    full = fr.build_tape(a)
    short = fr.build_tape(a[a.session_date < fr.FORWARD_START])
    for win in ('TUNE', 'HOLD'):
        assert len(fr.window_days(short, win)) > 0
        assert fr.data_version(full, win) == fr.data_version(short, win)


def _mixed_contract_adf(switch_slot=40):
    a = make_adf(n_days=30, seed=3)
    a.loc[:, ['open', 'close']] = 100.
    a['high'], a['low'] = 125., 75.
    day = sorted(set(a[a.rth].session_date))[25]
    a.loc[a.session_date == day, ['open', 'high', 'low', 'close']] = 100.
    switch = a[(a.session_date == day) & a.rth].index[switch_slot]
    a.loc[a.index >= switch, ['open', 'high', 'low', 'close']] += 150.
    a.loc[a.index >= switch, 'instrument_id'] = 2
    return a


@pytest.mark.parametrize('switch_slot', [0, 40])
def test_mixed_contract_dataset_is_rejected_before_evaluation(switch_slot):
    with pytest.raises(ValueError, match='mixed.contract'):
        fr.evaluate(fr.build_tape(_mixed_contract_adf(switch_slot)), dict(total=0), n_sets=2)


@pytest.mark.parametrize('switch_slot', [0, 40])
def test_run_rejects_mixed_contracts_before_any_ledger_write(tmp_path, monkeypatch, switch_slot):
    _fake_sources(tmp_path)
    a = _mixed_contract_adf(switch_slot)
    monkeypatch.setattr(fr, 'load_raw_mnq', lambda *args: (a, None, {}))
    def forbid_evaluation(*args, **kwargs):
        raise AssertionError('unsafe contract context must be rejected before evaluation')
    monkeypatch.setattr(fr, 'evaluate', forbid_evaluation)
    ledger = tmp_path / 'ledger.jsonl'
    snap = tmp_path / 'snapshot.json'
    out = fr.run('unused', str(tmp_path / 'out.json'), str(ledger), root=str(tmp_path), snapshot_path=str(snap))
    assert out['status'] == 'BLOCKED'
    assert 'mixed-contract' in ' '.join(out['blockers'])
    assert not ledger.exists() and not snap.exists()


def test_missing_hold_p_does_not_shrink_reached_family(monkeypatch):
    tape, sig = _injected(170, 21, planted=True)
    original = fr.trade_stats
    def controlled_stats(tape, real, mask, days):
        result = original(tape, real, mask, days)
        if len(days) and fr.window_of(tape.dates[days[0]]) == 'HOLD':
            result['nw_p'] = .03 if result['trades'] else math.nan
        return result
    monkeypatch.setattr(fr, 'trade_stats', controlled_stats)
    tune_only = sig.copy()
    tune_only[np.array([fr.window_of(d) != 'TUNE' for d in tape.dates])] = 0
    sources = {'A': dict(id='a', lookback=10, signals=sig),
               'B': dict(id='b', lookback=10, signals=tune_only)}
    out = fr.evaluate(tape, dict(total=0), n_sets=20, sources=sources)
    assert out['sources']['A']['hold']['holm_p'] == pytest.approx(.06)
    assert out['sources']['A']['status'] == 'REJECTED'
    assert out['sources']['B']['status'] == 'REJECTED'


def test_changed_historical_snapshot_blocks_before_ledger_mutation(tmp_path, monkeypatch):
    cl = _fake_sources(tmp_path)
    a = make_adf(n_days=5)
    calls = []
    monkeypatch.setattr(fr, 'load_raw_mnq', lambda *args: (a, None, {}))
    def evaluate(*args, **kwargs):
        calls.append(True)
        return dict(trials=[], sources={})
    monkeypatch.setattr(fr, 'evaluate', evaluate)
    ledger, snap = tmp_path/'ledger.jsonl', tmp_path/'snapshot.json'
    args = ('unused', str(tmp_path/'out.json'), str(ledger))
    opts = dict(root=str(tmp_path), snapshot_path=str(snap))
    assert fr.run(*args, **opts)['status'] == 'EVALUATED'
    before = ledger.read_bytes()
    path = cl/'depth_d1_latest.json'
    source = json.loads(path.read_text()); source['fingerprint'] = 'changed-input'
    path.write_text(json.dumps(source))
    result = fr.run(*args, **opts)
    assert result['status'] == 'BLOCKED'
    assert 'frozen snapshot' in ' '.join(result['blockers'])
    assert calls == [True] and ledger.read_bytes() == before


def test_fr1_records_do_not_invalidate_frozen_historical_snapshot(tmp_path, monkeypatch):
    _fake_sources(tmp_path)
    a = make_adf(n_days=5)
    monkeypatch.setattr(fr, 'load_raw_mnq', lambda *args: (a, None, {}))
    monkeypatch.setattr(fr, 'evaluate', lambda *args, **kwargs: dict(trials=[], sources={}))
    ledger, snap = tmp_path/'ledger.jsonl', tmp_path/'snapshot.json'
    args = ('unused', str(tmp_path/'out.json'), str(ledger))
    opts = dict(root=str(tmp_path), snapshot_path=str(snap))
    assert fr.run(*args, **opts)['status'] == 'EVALUATED'
    trial_ledger.append(ledger, [dict(trial_id='fr-1:synthetic', source='fr-1', source_path='synthetic', row_sha256='x')])
    assert fr.run(*args, **opts)['status'] == 'EVALUATED'
