"""Guest experiments must not fan out compute or read owner/admin replay jobs."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from icarus_engine import guest_server
from icarus_engine.assets import AssetSpec
from icarus_engine.pine.timeframe import Bar
from icarus_engine.runtime import AssetRunner, Journal, Portfolio, RunnerConfig
from icarus_engine.strategy.inputs import Inputs

TOKEN = "resource-lock-guest-token-0123456789"


@pytest.fixture
def locked_endpoint(tmp_path, monkeypatch):
    port = Portfolio(Journal(":memory:"), str(tmp_path))
    spec = AssetSpec("TEST", "Test", "yahoo", "TEST", "crypto", .25, 1,
                     chart_tf="1", capital=100000, commission=1, roll="none")
    runner = AssetRunner(RunnerConfig(spec, Inputs(use_tide=False, use_eod_flat=False)), port.journal)
    runner.subbars = [(Bar(k * 60, 100, 101, 99, 100, 1), 1) for k in range(20)]
    runner.raw_subbars = list(runner.subbars)
    runner.warm = True
    port.runners["TEST"] = runner
    port.order = ["TEST"]

    started = []
    def schedule(p, params):
        job_id = f"guest-lock-{len(started)+1}"
        started.append((job_id, params))
        return job_id
    monkeypatch.setattr(guest_server, "start_job", schedule)

    srv = guest_server.serve(port, 0, guest_token=TOKEN, start=False)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/g/{TOKEN}"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path,
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as ex:
            return ex.code, json.load(ex)

    yield call, started
    for job_id, _ in started:
        guest_server.JOBS.pop(job_id, None)
    guest_server.JOBS.pop("owner-private-job", None)
    srv.shutdown(); srv.server_close(); thread.join(5)


def test_guest_cannot_read_non_guest_backtest_job(locked_endpoint, monkeypatch):
    call, _ = locked_endpoint
    monkeypatch.setitem(guest_server.JOBS, "owner-private-job", {
        "id": "owner-private-job", "status": "done", "result": {"secret_owner_result": 123}
    })
    code, body = call("GET", "/api/experiment/jobs/owner-private-job")
    assert code == 404
    assert body["detail"] == "unknown job"


def test_guest_can_read_only_job_it_started(locked_endpoint, monkeypatch):
    call, started = locked_endpoint
    code, body = call("POST", "/api/experiment/backtest", {"asset": "TEST"})
    assert code == 200 and started
    job_id = body["job"]
    monkeypatch.setitem(guest_server.JOBS, job_id, {
        "id": job_id, "status": "done", "result": {"summary": {"net_profit": 12}}
    })
    code, result = call("GET", f"/api/experiment/jobs/{job_id}")
    assert code == 200
    assert result["result"]["summary"]["net_profit"] == 12


def test_guest_has_hard_single_active_replay_lock(locked_endpoint, monkeypatch):
    call, started = locked_endpoint
    code, first = call("POST", "/api/experiment/backtest", {"asset": "TEST"})
    assert code == 200
    first_id = first["job"]
    monkeypatch.setitem(guest_server.JOBS, first_id, {"id": first_id, "status": "running"})

    code, denied = call("POST", "/api/experiment/rewarm", {"asset": "TEST"})
    assert code == 429
    assert "experiment already running" in denied["detail"]
    assert len(started) == 1

    guest_server.JOBS[first_id]["status"] = "done"
    code, second = call("POST", "/api/experiment/rewarm", {"asset": "TEST"})
    assert code == 200
    assert second["job"] != first_id
    assert len(started) == 2
