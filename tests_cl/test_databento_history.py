# CL (Claude, Anthropic) — 2026-10-04 — tests for the CL long-history backfill lane (4th Databento key)
import json

import numpy as np
import pandas as pd

from cl_lab.feeds import databento_history as dh


class _Store:
    def __init__(self, df):
        self.df = df

    def to_df(self):
        return self.df.copy()


class _Client:
    def __init__(self, usd_per_year=1.3):
        self.rate, self.cost_calls, self.range_calls = usd_per_year, [], []
        self.metadata, self.timeseries = self, self

    def get_cost(self, **kw):
        self.cost_calls.append(kw)
        return self.rate * (pd.Timestamp(kw["end"]) - pd.Timestamp(kw["start"])) / pd.Timedelta(days=365)

    def get_range(self, **kw):
        self.range_calls.append(kw)
        idx = pd.date_range(pd.Timestamp(kw["start"]) + pd.Timedelta(days=3, hours=14), periods=20, freq="1min")
        df = pd.DataFrame(dict(open=100.0, high=101.0, low=99.0, close=100.5, volume=1.0,
                               instrument_id=7), index=idx)
        df.index.name = "ts_event"
        return _Store(df.reset_index())


def test_chunks_cover_2010_06_to_2024_09_by_year():
    c = dh.chunks()
    assert c[0][0] == dh.START and c[-1][1] == dh.END and len(c) == 15
    assert all(a < b for a, b in c) and all(c[i][1] == c[i + 1][0] for i in range(len(c) - 1))


def test_backfill_respects_run_and_lifetime_caps_and_never_pays_twice(tmp_path):
    led_path = str(tmp_path / "out" / "history_ledger.json")
    cache = str(tmp_path / "cache")
    c = _Client(usd_per_year=1.3)
    led = dh.run(cache, led_path, client=c, now="2026-10-05T00:00Z")
    assert led["run_status"] == "BUDGET_PAUSED" and led["spent_estimated_usd"] <= dh.MAX_USD_PER_RUN
    first_requests = len(c.range_calls)
    assert first_requests >= 10
    total = 0
    for i in range(10):                                          # later runs finish and then stop paying
        c2 = _Client(usd_per_year=1.3)
        led = dh.run(cache, led_path, client=c2, now=f"2026-10-0{6 + i % 3}T00:00Z")
        total += len(c2.range_calls)
    assert led["run_status"] == "OK" and first_requests + total == 2 * len(dh.chunks())
    assert led["spent_estimated_usd"] <= dh.MAX_USD_LIFETIME
    again = _Client()
    dh.run(cache, led_path, client=again, now="2026-10-10T00:00Z")
    assert again.range_calls == []                               # everything cached: no spend
    # a lost committed ledger does not reset the spend: the cached copy wins
    (tmp_path / "out" / "history_ledger.json").unlink()
    led2 = dh.run(cache, led_path, client=_Client(), now="2026-10-11T00:00Z")
    assert led2["spent_estimated_usd"] == led["spent_estimated_usd"]


def test_over_request_cap_and_unconfigured(tmp_path, monkeypatch):
    led = dh.run(str(tmp_path / "c"), str(tmp_path / "l.json"), client=_Client(usd_per_year=40.0), now="2026-10-05T00:00Z")
    assert led["chunks"] and all(v["status"] == "OVER_REQUEST_CAP" for v in led["chunks"].values())
    monkeypatch.delenv("DATABENTO_API_KEY_FOURTH", raising=False)
    led = dh.run(str(tmp_path / "c2"), str(tmp_path / "l2.json"), now="2026-10-05T00:00Z")
    assert led["run_status"].startswith("UNCONFIGURED") and json.load(open(tmp_path / "l2.json"))["execution_authorized"] is False


def test_locked_account_stops_after_one_call(tmp_path):
    class _Locked(_Client):
        def get_cost(self, **kw):
            self.cost_calls.append(kw)
            raise RuntimeError("BentoClientError: 403 auth_account_locked Your account has been locked")
    c = _Locked()
    led = dh.run(str(tmp_path / "c"), str(tmp_path / "l.json"), client=c, now="2026-10-05T05:00Z")
    assert led["run_status"].startswith("AUTH_FAILED") and len(c.cost_calls) == 1 and c.range_calls == []
    assert led["spent_estimated_usd"] == 0.0
