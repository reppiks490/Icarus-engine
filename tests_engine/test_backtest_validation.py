"""Backtest requests are rejected before scheduling and cannot bypass the core guard."""
import copy
import json
import threading
import urllib.error
import urllib.request

import pytest

from icarus_engine import backtest, server
from icarus_engine.assets import AssetSpec
from icarus_engine.pine.timeframe import Bar
from icarus_engine.runtime import AssetRunner, Journal, Portfolio, RunnerConfig
from icarus_engine.strategy.inputs import Inputs


INVALID = [
    {"fill_on": "standard"}, {"fill_on": []},
    {"chart_type": "ha"}, {"chart_type": True},
    {"session": "24/7"}, {"session": {}},
    {"preset": True}, {"preset": []},
    {"slippage_ticks": -1}, {"slippage_ticks": 1.5}, {"slippage_ticks": "1.5"},
    {"slippage_ticks": float("nan")}, {"slippage_ticks": float("inf")}, {"slippage_ticks": False},
    {"commission": -0.01}, {"commission": float("nan")}, {"commission": float("inf")},
    {"commission": "nan"}, {"commission": "1e309"}, {"commission": True}, {"commission": []},
    {"capital": 0}, {"capital": -1}, {"capital": float("nan")}, {"capital": float("-inf")},
    {"capital": "inf"}, {"capital": False}, {"capital": 10 ** 400},
    {"leverage": 0}, {"leverage": -1}, {"leverage": float("inf")}, {"leverage": True},
    {"window_start": -1}, {"window_start": .1}, {"window_start": True},
    {"window_start": "tomorrow"}, {"window_start": float("nan")},
    {"window_end": -1}, {"window_end": 1.5}, {"window_end": float("inf")},
    {"window_end": 253402300800}, {"window_start": 2, "window_end": 1},
    {"window_start": "3", "window_end": "2"},
    {"inputs": []}, {"inputs": ""}, {"inputs": False},
    {"inputs": {"unknown_input": 1}}, {"inputs": {"_meta": {"capital": 0}}},
    {"inputs": {"qty_contracts": "2"}}, {"inputs": {"qty_contracts": 1.5}},
    {"inputs": {"qty_contracts": True}}, {"inputs": {"use_tide": 1}},
    {"inputs": {"tp1_pts": "80"}}, {"inputs": {"tp1_pts": False}},
    {"inputs": {"tp1_pts": float("inf")}}, {"inputs": {"tp1_pts": 10 ** 400}},
    {"inputs": {"htf_tf_1": 60}},
]


@pytest.fixture
def port(tmp_path):
    p = Portfolio(Journal(":memory:"), str(tmp_path))
    spec = AssetSpec("TEST", "Test", "yahoo", "TEST", "crypto", .25, 1,
                     chart_tf="1", capital=100000, commission=1, roll="none")
    r = AssetRunner(RunnerConfig(spec, Inputs(use_tide=False, use_eod_flat=False)), p.journal)
    r.subbars = [(Bar(k * 60, 100 + k, 101 + k, 99 + k, 100 + k, 1), 1) for k in range(10)]
    r.warm = True
    p.runners["TEST"] = r
    p.order = ["TEST"]
    return p


@pytest.mark.parametrize("params", INVALID)
def test_direct_replay_rejects_invalid_request_before_accessing_source(params):
    with pytest.raises(ValueError):
        backtest.run_backtest(None, "TEST", **params)


def test_start_job_rejects_invalid_request_before_creating_job_or_thread(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid backtest must not allocate or schedule a job")
    monkeypatch.setattr(backtest.uuid, "uuid4", forbidden)
    before = dict(backtest.JOBS)
    for params in INVALID:
        with pytest.raises(ValueError):
            backtest.start_job(None, {"asset": "TEST", **params})
    assert backtest.JOBS == before


@pytest.fixture
def endpoint(port, monkeypatch):
    scheduled = []
    def schedule(p, params):
        assert p is port
        scheduled.append(params)
        return "validated-job"
    monkeypatch.setattr(server, "start_job", schedule)
    srv = server.serve(port, 0, token="test-token", start=False)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    def post(params):
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/admin/backtest",
                                     data=json.dumps({"asset": "TEST", **params}).encode(),
                                     headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as reply:
                return reply.status, json.load(reply)
        except urllib.error.HTTPError as ex:
            return ex.code, json.load(ex)
    yield post, scheduled
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def test_http_invalid_requests_never_reach_job_scheduler(endpoint):
    post, scheduled = endpoint
    for params in INVALID:
        status, response = post(params)
        assert status == 400 and response.get("detail"), (params, status, response)
        assert not scheduled


def test_http_keeps_valid_costs_modes_windows_and_input_types(endpoint):
    post, scheduled = endpoint
    params = {"fill_on": "chart", "chart_type": "heikin_ashi", "session": "eth", "slippage_ticks": "2",
              "commission": "0", "capital": "100000.5", "leverage": 1, "window_start": 0, "window_end": "300",
              "inputs": {"qty_contracts": 2.0, "use_tide": False, "tp1_pts": 80}}
    status, response = post(params)
    assert status == 200 and response["job"] == "validated-job"
    assert scheduled == [{"asset": "TEST", **params, "slippage_ticks": 2, "commission": 0.0, "capital": 100000.5,
                           "leverage": 1.0, "window_end": 300,
                           "inputs": {"qty_contracts": 2, "use_tide": False, "tp1_pts": 80}}]
    assert type(scheduled[0]["inputs"]["qty_contracts"]) is int


def test_http_optional_defaults_and_zero_costs_are_valid(endpoint):
    post, scheduled = endpoint
    assert post({})[0] == 200
    assert scheduled[-1] == {"asset": "TEST"}
    assert post({"preset": None, "fill_on": "", "commission": None, "capital": "", "inputs": None})[0] == 200
    assert scheduled[-1] == {"asset": "TEST"}
    assert post({"slippage_ticks": 0, "commission": 0, "window_start": 0, "window_end": 0, "inputs": {}})[0] == 200
    assert scheduled[-1] == {"asset": "TEST", "slippage_ticks": 0, "commission": 0.0,
                             "window_start": 0, "window_end": 0, "inputs": {}}


def test_http_preset_path_validation_still_rejects_before_scheduling(endpoint):
    post, scheduled = endpoint
    assert post({"preset": "../outside"})[0] == 400
    assert post({"preset": "missing"})[0] == 404
    assert not scheduled


def test_valid_direct_replay_honors_normalized_parameters_without_mutating_request(port):
    inputs = {"qty_contracts": 2.0, "use_tide": False, "tp1_pts": 80}
    before = copy.deepcopy(inputs)
    result = backtest.run_backtest(port, "TEST", inputs=inputs, fill_on="chart", chart_type="heikin_ashi",
                                   slippage_ticks="2", commission="0", capital="100000.5", leverage="1",
                                   window_start="0", window_end="300")
    cfg = result["config"]
    assert result["bars"] == 5 and result["range"]["end"] == 300
    assert cfg["fill_on"] == "chart" and cfg["chart_type"] == "heikin_ashi"
    assert cfg["slippage_ticks"] == 2 and cfg["commission"] == 0 and cfg["capital"] == 100000.5
    assert cfg["leverage"] == 1 and cfg["window_start"] == 0
    effective = cfg["reproducibility"]["effective_config"]["effective_inputs"]
    assert effective["qty_contracts"] == 2 and effective["use_tide"] is False and effective["tp1_pts"] == 80
    assert inputs == before and type(inputs["qty_contracts"]) is float


def test_direct_optional_defaults_and_zero_length_window_remain_valid(port):
    default = backtest.run_backtest(port, "TEST")
    optional = backtest.run_backtest(port, "TEST", preset="", inputs=None, fill_on=None, capital="", commission=None,
                                     leverage=None, window_start="", window_end=None)
    assert default == optional
    zero = backtest.run_backtest(port, "TEST", slippage_ticks=0, commission=0, window_start=0, window_end=0)
    assert zero["bars"] == 0 and zero["config"]["window_end"] == 0
