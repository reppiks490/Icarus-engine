# CL (Claude, Anthropic) — 2026-10-05 — tests: leftover-credit sweep lanes, NQ MBP-10 sweep buyer, resilience reducer
import json
import os

import numpy as np
import pandas as pd
import pytest

db = pytest.importorskip("databento")
dbn = pytest.importorskip("databento_dbn")

from cl_lab import depth_resilience as dr
from cl_lab.feeds import databento_budget as budget
from cl_lab.feeds import databento_depth_sweep as sw
from cl_lab.feeds import registry

T0 = int(pd.Timestamp("2026-10-01T14:00:00Z").value)
S = 1_000_000_000


def _px(x):
    return int(round(x * 1e9))


def _rec(t, action, side, price, size, bid0, ask0, bsz0, asz0, last=True, te=None):
    levels = [dbn.BidAskPair(bid_px=_px(bid0 - 0.25 * i), ask_px=_px(ask0 + 0.25 * i), bid_sz=(bsz0 if i == 0 else 5),
                             ask_sz=(asz0 if i == 0 else 5), bid_ct=1, ask_ct=1) for i in range(10)]
    return bytes(dbn.MBP10Msg(publisher_id=1, instrument_id=7, ts_event=te or t, price=_px(price), size=size,
                              action=getattr(dbn.Action, action), side=getattr(dbn.Side, side), depth=0, ts_recv=t,
                              flags=(0x80 if last else 0), levels=levels))


def _header():
    return dbn.Metadata(dataset="GLBX.MDP3", schema=dbn.Schema.MBP_10, start=T0, stype_in=dbn.SType.CONTINUOUS,
                        stype_out=dbn.SType.INSTRUMENT_ID, symbols=["NQ.v.0"], partial=[], not_found=[],
                        mappings=[]).encode()


def scenario(t0=T0):
    """Buyer sweeps 2 levels at t0+10s; ask depth refills at +2s; spread back to 1 tick at +3s."""
    r = [_rec(t0, "ADD", "BID", 100.0, 1, 100.0, 100.25, 5, 6)]
    for k in range(1, 10):                                       # quiet book
        r.append(_rec(t0 + k * S, "ADD", "BID", 99.0, 1, 100.0, 100.25, 5, 6))
    te = t0 + 10 * S
    r.append(_rec(te, "TRADE", "BID", 100.25, 6, 100.0, 100.25, 5, 6, last=False, te=te))
    r.append(_rec(te + 10, "TRADE", "BID", 100.50, 2, 100.0, 100.25, 5, 6, last=False, te=te))
    r.append(_rec(te + 20, "CANCEL", "ASK", 100.25, 6, 100.0, 100.50, 5, 3, last=True, te=te))  # ask d5 26 -> 23
    r.append(_rec(te + 2 * S, "ADD", "ASK", 100.50, 3, 100.0, 100.50, 5, 6))                  # d5 back to 26
    r.append(_rec(te + 3 * S, "ADD", "BID", 100.25, 4, 100.25, 100.50, 4, 6))                 # spread 1 tick
    te2 = te + 20 * S
    r.append(_rec(te2, "TRADE", "ASK", 100.25, 1, 100.25, 100.50, 4, 6, te=te2))              # does not clear
    for k in range(21, 400, 7):
        r.append(_rec(te + k * S, "ADD", "BID", 99.0, 1, 100.25, 100.50, 4, 6))
    return _header() + b"".join(r)


def test_resilience_event_measurements():
    ev = dr.events(db.DBNStore.from_bytes(scenario()), chunk=7)   # tiny chunks: exercises the concatenation
    assert len(ev) == 1
    e = ev.iloc[0]
    assert e["dir"] == 1 and e["levels_swept"] == 2 and e["traded"] == 8 and e["n_trades"] == 2
    assert e["pre_spread"] == pytest.approx(1.0) and e["pre_touch"] == 6 and e["pre_d5"] == 26 and e["pre_d5_opp"] == 25
    assert e["refill_1s"] == pytest.approx(23 / 26) and e["refill_5s"] == pytest.approx(1.0)
    assert e["t_refill_ms"] == pytest.approx(2000.0, abs=1e-3) and e["t_spread_ms"] == pytest.approx(3000.0, abs=1e-3)
    assert e["move_5s"] == pytest.approx(1.0) and e["move_300s"] == pytest.approx(1.0)


def test_resilience_horizons_past_the_file_are_empty():
    raw = scenario()
    ev = dr.events(db.DBNStore.from_bytes(raw[: len(raw) - 368 * 50]))   # cut the tail: file ends ~+40 s
    e = ev.iloc[0]
    assert np.isnan(e["move_60s"]) and np.isnan(e["move_300s"]) and e["move_30s"] == pytest.approx(1.0)


# --------------------------------------------------------------------------------------------- budget


def _ledger(d, lane, spent, finished=False):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, lane.replace(":", "__") + ".json"), "w") as f:
        json.dump(dict(lane=lane, spent_usd=spent, finished=finished, entries=[]), f)


def test_sweep_cap_takes_everything_not_committed(tmp_path):
    led = str(tmp_path / "spend")
    budget.check_split()
    # primary: 56 - reserve 2 - history:ES cap 25 (unfinished) = 29
    assert budget.sweep_cap("primary", led) == pytest.approx(29.0)
    _ledger(led, "history:ES", 17.8, finished=True)                  # finished under cap: 7.2 flows to the sweep
    assert budget.sweep_cap("primary", led) == pytest.approx(56 - 2 - 17.8)
    _ledger(led, "corpus:primary", 0.3)
    assert budget.sweep_cap("primary", led) == pytest.approx(56 - 2 - 17.8 - 0.3)
    # third: 125 - 0.5 - NQ(25 until finished) - depth:diversifier 95 = 4.5
    assert budget.sweep_cap("third", led) == pytest.approx(4.5)
    _ledger(led, "history:NQ", 17.6, finished=True)
    assert budget.sweep_cap("third", led) == pytest.approx(125 - 0.5 - 17.6 - 95)
    # secondary: 98.5 - 1.5 - 93
    assert budget.sweep_cap("secondary", led) == pytest.approx(4.0)
    lane = budget.Lane("depth:sweep:secondary", led)
    lane.record(3.0, "x", "t")
    assert budget.Lane("depth:sweep:secondary", led).remaining == pytest.approx(1.0)
    # every account: committed + reserve never exceeds the estimated credit
    for acct in budget.ESTIMATED_REMAINING_USD:
        assert budget.headroom(acct, led) >= budget.RESERVE_USD[acct] - 1e-9 - 0  # sweep leaves the reserve


def test_corpus_guard_refuses_topups_past_the_account_credit(tmp_path, monkeypatch):
    led, cache = str(tmp_path / "spend"), str(tmp_path / "cache")
    _ledger(led, "depth:sweep:primary", 29.0)                        # sweep used everything but the reserve
    monkeypatch.setenv("DATABENTO_API_KEY", "x")
    monkeypatch.setenv("CL_DATABENTO_MAX_USD_PER_FEED", "3.50")
    calls = []

    def fake(root, old, now, **kw):
        calls.append(kw["max_usd"])
        idx = pd.date_range("2026-10-01T14:00Z", periods=3, freq="5min")
        df = pd.DataFrame(dict(open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0), index=idx)
        est = min(0.75, kw["max_usd"])
        kw["charge"](est, lambda: None)
        return df, dict(request_performed=True, estimated_cost_usd=est)

    monkeypatch.setattr(registry.databento_feed, "fetch_continuous_5m", fake)
    names = [f["name"] for f in registry.FEEDS if f["kind"] == "databento" and not f.get("account")][:4]
    man = registry.refresh_all(cache, only=set(names), now="2026-10-05T12:00Z", ledger_dir=led)
    # reserve $2: two pulls of $0.75 fit, the third is capped at the $0.50 left, the fourth is refused
    assert calls == pytest.approx([2.0, 1.25, 0.5])
    st = [man["feeds"][n]["status"] for n in names]
    assert st[:3] == ["ok", "ok", "ok"] and st[3] == "error" and "credit guard" in man["feeds"][names[3]]["error"]
    assert budget.Lane("corpus:primary", led).data["spent_usd"] == pytest.approx(2.0)
    assert budget.headroom("primary", led) == pytest.approx(0.0)


# --------------------------------------------------------------------------------------------- sweep buyer


class _Client:
    def __init__(self, usd_per_hour=0.5):
        self.rate, self.cost_calls, self.range_calls = usd_per_hour, [], []
        self.metadata, self.timeseries = self, self

    def get_cost(self, **kw):
        self.cost_calls.append(kw)
        return self.rate * (pd.Timestamp(kw["end"]) - pd.Timestamp(kw["start"])) / pd.Timedelta(hours=1)

    def get_range(self, path=None, **kw):
        self.range_calls.append(kw)
        with open(path, "wb") as f:
            f.write(scenario(int(pd.Timestamp(kw["start"]).value)))
        return db.DBNStore.from_file(path)


def _corpus(cache, days):
    rows = []
    for d in days:
        a = pd.Timestamp(f"{d} 09:30", tz="America/New_York").tz_convert("UTC")
        rows.append(pd.DataFrame(dict(open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0),
                                 index=pd.date_range(a, periods=78, freq="5min")))
    os.makedirs(cache, exist_ok=True)
    from cl_lab import store
    store.save_frame(pd.concat(rows), os.path.join(cache, "databento_nq_5m.csv.gz"))


def test_sweep_buys_newest_days_splits_past_and_forward_and_never_repeats(tmp_path):
    cache, depth, led = str(tmp_path / "c"), str(tmp_path / "d"), str(tmp_path / "s")
    days = [d.date() for d in pd.bdate_range("2026-09-21", "2026-10-02")]
    _corpus(cache, days)
    cl = _Client(usd_per_hour=0.5)                                    # $3.50 per 7-hour window
    res = sw.run_account("secondary", cache_dir=cache, depth_cache=depth, ledger_dir=led, client=cl,
                         now="2026-10-05T12:00Z")
    # secondary sweep cap $4.00, past share 50% -> $2.00: one window shortened from its end to fit
    assert res["cap_usd"] == pytest.approx(4.0)
    assert len(res["bought"]) == 1 and res["bought"][0]["day"] == "2026-10-02" and res["bought"][0]["partial_window"]
    assert res["bought"][0]["estimated_cost_usd"] <= 2.0 + 1e-9 and res["bought"][0]["resilience_events"] == 1
    assert res["past_spent_usd"] <= 2.0 + 1e-9
    a = pd.Timestamp(cl.range_calls[0]["start"])
    assert a == pd.Timestamp("2026-10-02 09:15", tz="America/New_York").tz_convert("UTC")     # DST-aware window
    assert os.path.exists(os.path.join(depth, "resilience", "secondary", "nq", "2026-10-02.csv.gz"))
    assert not os.listdir(os.path.join(depth, "_raw_tmp"))                                     # raw deleted
    # a forward day arrives: it may use the rest of the cap; held days are never bought again
    _corpus(cache, days + [pd.Timestamp("2026-10-05").date()])
    cl2 = _Client(usd_per_hour=0.25)
    res2 = sw.run_account("secondary", cache_dir=cache, depth_cache=depth, ledger_dir=led, client=cl2,
                          now="2026-10-06T12:00Z")
    got = [b["day"] for b in res2["bought"]]
    assert got[0] == "2026-10-05" and "2026-10-02" not in got
    assert res2["spent_usd"] <= 4.0 + 1e-9
    # another account never re-buys a day held by this one
    res3 = sw.run_account("third", cache_dir=cache, depth_cache=depth, ledger_dir=led, client=_Client(0.25),
                          now="2026-10-06T12:00Z")
    assert not ({b["day"] for b in res3["bought"]} & set(got + ["2026-10-02"]))
    # the cache is lost: the committed ledgers still name every bought day, so none is bought again
    import shutil
    shutil.rmtree(depth)
    res4 = sw.run_account("third", cache_dir=cache, depth_cache=depth, ledger_dir=led, client=_Client(0.01),
                          now="2026-10-06T12:00Z")
    before = set(got) | {"2026-10-02"} | {b["day"] for b in res3["bought"]}
    assert not ({b["day"] for b in res4["bought"]} & before)


def test_sweep_auth_error_stops_at_once(tmp_path):
    cache = str(tmp_path / "c")
    _corpus(cache, [d.date() for d in pd.bdate_range("2026-09-28", "2026-10-02")])

    class Locked(_Client):
        def get_cost(self, **kw):
            self.cost_calls.append(kw)
            raise RuntimeError("403 auth_account_locked")

    cl = Locked()
    res = sw.run_account("third", cache_dir=cache, depth_cache=str(tmp_path / "d"), ledger_dir=str(tmp_path / "s"),
                         client=cl, now="2026-10-05T12:00Z")
    assert res["status"].startswith("AUTH_FAILED") and len(cl.cost_calls) == 1 and res["spent_usd"] == 0.0


def test_failed_download_without_bytes_is_reversed_and_retried(tmp_path):
    cache, depth, led = str(tmp_path / "c"), str(tmp_path / "d"), str(tmp_path / "s")
    _corpus(cache, [pd.Timestamp("2026-10-02").date()])

    class Down(_Client):
        def get_range(self, path=None, **kw):
            raise RuntimeError("503 service unavailable")

    res = sw.run_account("secondary", cache_dir=cache, depth_cache=depth, ledger_dir=led, client=Down(0.1),
                         now="2026-10-05T12:00Z")
    assert res["errors"][0]["status"] == "download_error" and res["spent_usd"] == pytest.approx(0.0)
    assert "2026-10-02" not in sw.held_days(depth, led)
    res2 = sw.run_account("secondary", cache_dir=cache, depth_cache=depth, ledger_dir=led, client=_Client(0.1),
                          now="2026-10-05T13:00Z")
    assert [b["day"] for b in res2["bought"]] == ["2026-10-02"]


class _Refused(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.http_status = status


def test_paid_request_charges_first_and_refunds_only_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(budget.time, "sleep", lambda s: None)
    lane = budget.Lane("history:NQ", str(tmp_path))
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _Refused(503)
        return "data"

    assert budget.paid_request(lane, 1.0, "x", "t", flaky) == "data" and len(calls) == 3
    assert lane.data["spent_usd"] == pytest.approx(1.0)                 # two refusals refunded, one charge stands
    with pytest.raises(TimeoutError):
        budget.paid_request(lane, 2.0, "y", "t", lambda: (_ for _ in ()).throw(TimeoutError("read timed out")))
    assert lane.data["spent_usd"] == pytest.approx(3.0)                 # a timeout may have been served: kept
    with pytest.raises(_Refused):
        budget.paid_request(lane, 4.0, "z", "t", lambda: (_ for _ in ()).throw(_Refused(422)))
    assert lane.data["spent_usd"] == pytest.approx(3.0)                 # 4xx refusal: refunded, not retried


def test_failed_reduction_keeps_raw_stops_spending_and_is_retried(tmp_path, monkeypatch):
    cache, depth, led = str(tmp_path / "c"), str(tmp_path / "d"), str(tmp_path / "s")
    _corpus(cache, [d.date() for d in pd.bdate_range("2026-09-21", "2026-10-02")])
    real = sw.acq.summarize_store
    monkeypatch.setattr(sw.acq, "summarize_store", lambda dbn: (_ for _ in ()).throw(RuntimeError("bug")))
    cl = _Client(0.01)
    res = sw.run_account("third", cache_dir=cache, depth_cache=depth, ledger_dir=led, client=cl, now="2026-10-05T12:00Z")
    assert len(cl.range_calls) == 1 and res["status"].startswith("STOPPED") and res["spent_usd"] > 0   # one day, then stop
    assert os.listdir(os.path.join(depth, "_retry_raw")) == ["third__2026-10-02.dbn.zst"]
    cl2 = _Client(0.01)
    res = sw.run_account("third", cache_dir=cache, depth_cache=depth, ledger_dir=led, client=cl2, now="2026-10-05T13:00Z")
    assert res["status"].startswith("REDUCTION_PENDING") and cl2.range_calls == []                    # still broken
    monkeypatch.setattr(sw.acq, "summarize_store", real)
    res = sw.run_account("third", cache_dir=cache, depth_cache=depth, ledger_dir=led, client=_Client(0.01),
                         now="2026-10-05T14:00Z")
    assert res["bought"][0]["day"] == "2026-10-02" and res["bought"][0]["reduced_on_retry"]
    assert "2026-10-02" not in [b["day"] for b in res["bought"][1:]] and len(res["bought"]) <= 1 + sw.MAX_DAYS_PER_RUN
    assert not os.listdir(os.path.join(depth, "_retry_raw"))
