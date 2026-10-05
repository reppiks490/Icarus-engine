# CL (Claude, Anthropic) — 2026-10-05 — tests for the history backfill on the owner's credit split
import pandas as pd
import pytest

from cl_lab.feeds import databento_budget as budget
from cl_lab.feeds import databento_history as dh


class _Store:
    def __init__(self, df):
        self.df = df

    def to_df(self):
        return self.df.copy()


class _Client:
    def __init__(self, usd_per_year=1.3, fail=None):
        self.rate, self.fail, self.cost_calls, self.range_calls = usd_per_year, fail, [], []
        self.metadata, self.timeseries = self, self

    def get_cost(self, **kw):
        self.cost_calls.append(kw)
        if self.fail:
            raise RuntimeError(self.fail)
        return self.rate * (pd.Timestamp(kw["end"]) - pd.Timestamp(kw["start"])) / pd.Timedelta(days=365)

    def get_range(self, **kw):
        self.range_calls.append(kw)
        idx = pd.date_range(pd.Timestamp(kw["start"]) + pd.Timedelta(hours=14), periods=20, freq="1min")
        df = pd.DataFrame(dict(open=100.0, high=101.0, low=99.0, close=100.5, volume=1.0, instrument_id=7), index=idx)
        df.index.name = "ts_event"
        return _Store(df.reset_index())


def _clients(rate=1.3, **kw):
    return {"primary": _Client(rate, **kw), "third": _Client(rate, **kw)}


def test_split_fits_every_account_and_routes_nq_to_key3_es_to_key1():
    budget.check_split()
    assert budget.LANES["history:NQ"]["account"] == "third" and budget.LANES["history:ES"]["account"] == "primary"
    c = dh.chunks()
    assert c[0][1] == dh.END and c[-1][0] == dh.START and len(c) == 15 and c[0][0] > c[-1][0]   # newest first


def test_full_history_fits_and_is_never_bought_twice(tmp_path):
    cache, led = str(tmp_path / "cache"), str(tmp_path / "spend")
    for i in range(4):
        res = dh.run(cache, led, clients=_clients(), now=f"2026-10-0{5 + i}T00:00Z")
    assert all(v["status"] in ("OK", "FINISHED") and v["finished"] for v in res.values())
    assert res["NQ"]["history_first"].startswith("2010-06-07") and res["ES"]["spent_usd"] < 25.0
    again = _clients()
    dh.run(cache, led, clients=again, now="2026-10-10T00:00Z")
    assert again["primary"].range_calls == [] and again["third"].range_calls == []


def test_cap_shortens_only_the_oldest_year(tmp_path):
    cache, led = str(tmp_path / "cache"), str(tmp_path / "spend")
    for i in range(6):                                            # $3/year: 25 buys ~8.3 of the ~14.2 years
        res = dh.run(cache, led, clients=_clients(rate=3.0), now=f"2026-10-0{1 + i}T00:00Z")
    nq = res["NQ"]
    assert nq["status"] in ("CAP_REACHED", "FINISHED") and nq["finished"] and nq["spent_usd"] <= 25.0 + 1e-9
    first = pd.Timestamp(nq["history_first"])
    assert pd.Timestamp("2015-12-01", tz="UTC") < first < pd.Timestamp("2016-12-31", tz="UTC")   # newest kept, oldest cut
    after = _clients(rate=3.0)
    dh.run(cache, led, clients=after, now="2026-10-09T00:00Z")
    assert after["third"].range_calls == []                       # nothing older is ever bought past the cap


def test_auth_failure_stops_after_one_call(tmp_path):
    cl = _clients(fail="BentoClientError: 403 auth_account_locked")
    res = dh.run(str(tmp_path / "c"), str(tmp_path / "s"), clients=cl, now="2026-10-05T00:00Z")
    assert res["NQ"]["status"].startswith("AUTH_FAILED") and len(cl["third"].cost_calls) == 1
    assert res["NQ"]["spent_usd"] == 0.0


def test_lane_ledger_survives_a_lost_commit(tmp_path):
    lane = budget.Lane("history:NQ", str(tmp_path / "repo"), mirror=str(tmp_path / "cache"))
    lane.record(7.5, "x", "2026-10-05T00:00Z")
    (tmp_path / "repo" / "history__NQ.json").unlink()
    again = budget.Lane("history:NQ", str(tmp_path / "repo"), mirror=str(tmp_path / "cache"))
    assert again.data["spent_usd"] == 7.5 and again.remaining == pytest.approx(17.5)


def test_finished_lane_never_buys_again_after_cache_loss(tmp_path):
    import shutil
    cache, led = str(tmp_path / "cache"), str(tmp_path / "spend")
    for i in range(4):
        res = dh.run(cache, led, clients=_clients(), now=f"2026-10-0{5 + i}T00:00Z")
    assert res["NQ"]["finished"] and budget.committed("history:NQ", led) == pytest.approx(res["NQ"]["spent_usd"])
    shutil.rmtree(cache)                                          # the freed cap may already be spent by the sweep
    again = _clients()
    res = dh.run(cache, led, clients=again, now="2026-10-12T00:00Z")
    assert res["NQ"]["status"] == "FINISHED" and again["third"].range_calls == [] and again["third"].cost_calls == []


def test_parse_failure_keeps_the_charge_and_holds_the_lane(tmp_path, monkeypatch):
    cache, led = str(tmp_path / "cache"), str(tmp_path / "spend")
    monkeypatch.setattr(dh.dbf, "_as_ohlcv_1m", lambda store: (_ for _ in ()).throw(ValueError("bad payload")))
    cl = _clients()
    res = dh.run(cache, led, clients=cl, now="2026-10-05T00:00Z")
    assert res["NQ"]["status"].startswith("PARSE_FAILED") and res["NQ"]["spent_usd"] > 0
    n = len(cl["third"].range_calls)
    res = dh.run(cache, led, clients=cl, now="2026-10-06T00:00Z")
    assert res["NQ"]["status"].startswith("HOLD") and len(cl["third"].range_calls) == n     # not bought again
