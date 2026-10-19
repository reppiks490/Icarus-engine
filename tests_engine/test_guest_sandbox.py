"""Guest access is a capability-limited replay sandbox, never a live admin surface."""
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from icarus_engine import guest_server
from icarus_engine.assets import AssetSpec
from icarus_engine.pine.timeframe import Bar
from icarus_engine.runtime import AssetRunner, Journal, Portfolio, RunnerConfig
from icarus_engine.strategy.inputs import Inputs


GUEST_TOKEN = "guest-test-token-0123456789abcdef"


@pytest.fixture
def port(tmp_path):
    p = Portfolio(Journal(":memory:"), str(tmp_path))
    spec = AssetSpec("TEST", "Test", "yahoo", "TEST", "crypto", .25, 1,
                     chart_tf="1", capital=100000, commission=1, roll="none")
    r = AssetRunner(RunnerConfig(spec, Inputs(use_tide=False, use_eod_flat=False, qty_contracts=1)), p.journal)
    r.subbars = [(Bar(k * 60, 100 + k, 101 + k, 99 + k, 100 + k, 1), 1) for k in range(20)]
    r.raw_subbars = list(r.subbars)
    r.warm = True
    p.runners["TEST"] = r
    p.order = ["TEST"]
    return p


@pytest.fixture
def endpoint(port, monkeypatch):
    scheduled = []

    def schedule(p, params):
        assert p is port
        scheduled.append(params)
        return f"guest-job-{len(scheduled)}"

    monkeypatch.setattr(guest_server, "start_job", schedule)
    srv = guest_server.serve(port, 0, guest_token=GUEST_TOKEN, start=False)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as reply:
                raw = reply.read()
                return reply.status, json.loads(raw) if raw else None, reply.headers
        except urllib.error.HTTPError as ex:
            raw = ex.read()
            return ex.code, json.loads(raw) if raw else None, ex.headers

    yield call, scheduled
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def guest(path=""):
    suffix = path if path.startswith("/") or not path else "/" + path
    return f"/g/{GUEST_TOKEN}{suffix}"


def test_missing_or_wrong_capability_cannot_observe_guest_surface(endpoint):
    call, _ = endpoint
    assert call("GET", "/api/live/status")[0] in (401, 404)
    assert call("GET", "/g/wrong-token/api/live/status")[0] in (401, 404)
    assert call("GET", guest("/api/live/status"))[0] == 200


def test_live_status_is_viewable_but_guest_server_exposes_no_live_admin(endpoint):
    call, _ = endpoint
    status, body, _ = call("GET", guest("/api/live/status"))
    assert status == 200
    assert body["mode"] == "guest-sandbox"
    assert [a["symbol"] for a in body["assets"]] == ["TEST"]
    for path in ("/admin/pause", "/admin/resume", "/admin/flatten", "/admin/inputs",
                 "/admin/inputs/reset", "/admin/preset", "/admin/assets/add",
                 "/admin/assets/remove", "/admin/rewarm", "/admin/research/activation"):
        code, denied, _ = call("POST", guest(path), {"asset": "TEST", "confirm": True})
        assert code == 403, (path, code, denied)
        assert denied["detail"] == "guest access is isolated from live Icarus"


def test_guest_input_edits_change_only_guest_workspace(port, endpoint, tmp_path):
    call, _ = endpoint
    live_before = port.runners["TEST"].inputs.to_dict()
    code, state, _ = call("POST", guest("/api/experiment/inputs"), {
        "asset": "TEST", "values": {"qty_contracts": 2, "tp1_pts": 80}
    })
    assert code == 200
    assert state["asset"] == "TEST"
    assert state["inputs"]["qty_contracts"] == 2
    assert state["inputs"]["tp1_pts"] == 80
    assert port.runners["TEST"].inputs.to_dict() == live_before
    assert not os.path.exists(tmp_path / "inputs.TEST.json")
    assert not os.path.exists(tmp_path / "inputs.json")


def test_guest_backtest_uses_workspace_overrides_without_mutating_live_runner(port, endpoint):
    call, scheduled = endpoint
    live_before = port.runners["TEST"].inputs.to_dict()
    assert call("POST", guest("/api/experiment/inputs"), {
        "asset": "TEST", "values": {"qty_contracts": 2, "tp1_pts": 75}
    })[0] == 200
    code, body, _ = call("POST", guest("/api/experiment/backtest"), {
        "asset": "TEST", "fill_on": "real", "session": "rth", "commission": 0
    })
    assert code == 200 and body["job"] == "guest-job-1"
    assert scheduled == [{
        "asset": "TEST", "inputs": {"qty_contracts": 2, "tp1_pts": 75},
        "fill_on": "real", "session": "rth", "commission": 0.0,
    }]
    assert port.runners["TEST"].inputs.to_dict() == live_before


def test_guest_rewarm_is_an_isolated_replay_not_live_runner_warmup(port, endpoint, monkeypatch):
    call, scheduled = endpoint
    assert call("POST", guest("/api/experiment/inputs"), {
        "asset": "TEST", "values": {"qty_contracts": 3}
    })[0] == 200

    def forbidden_live_warmup(*args, **kwargs):
        pytest.fail("guest rewarm must never call the live runner warmup")

    monkeypatch.setattr(port.runners["TEST"], "warmup", forbidden_live_warmup)
    code, body, _ = call("POST", guest("/api/experiment/rewarm"), {"asset": "TEST"})
    assert code == 200
    assert body["job"] == "guest-job-1"
    assert body["isolated"] is True
    assert scheduled == [{"asset": "TEST", "inputs": {"qty_contracts": 3}}]


def test_guest_reset_discards_only_guest_overrides(port, endpoint):
    call, _ = endpoint
    live_before = port.runners["TEST"].inputs.to_dict()
    assert call("POST", guest("/api/experiment/inputs"), {
        "asset": "TEST", "values": {"qty_contracts": 4}
    })[0] == 200
    code, state, _ = call("POST", guest("/api/experiment/reset"), {"asset": "TEST"})
    assert code == 200
    assert state["inputs"] == {}
    assert port.runners["TEST"].inputs.to_dict() == live_before


def test_guest_preset_is_sandbox_only_and_validated(port, endpoint, tmp_path):
    call, _ = endpoint
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "guest-safe.json").write_text('{"qty_contracts": 2}', encoding="utf-8")
    code, state, _ = call("POST", guest("/api/experiment/preset"), {
        "asset": "TEST", "preset": "guest-safe"
    })
    assert code == 200 and state["preset"] == "guest-safe"
    assert port.runners["TEST"].cfg.preset is None
    assert call("POST", guest("/api/experiment/preset"), {"asset": "TEST", "preset": "../escape"})[0] == 400
    assert call("POST", guest("/api/experiment/preset"), {"asset": "TEST", "preset": "missing"})[0] == 404


def test_guest_job_results_are_readable_but_unknown_or_admin_paths_are_not(endpoint, monkeypatch):
    call, _ = endpoint
    monkeypatch.setitem(guest_server.JOBS, "abc", {"status": "done", "result": {"metrics": {"net_profit": 12}}})
    code, body, _ = call("GET", guest("/api/experiment/jobs/abc"))
    assert code == 200 and body["status"] == "done"
    assert call("GET", guest("/api/experiment/jobs/nope"))[0] == 404
    assert call("POST", guest("/not-an-experiment"), {})[0] == 403


def test_guest_root_is_explicit_about_isolation(endpoint):
    call, _ = endpoint
    code, _, headers = call("GET", guest("/api/live/status"))
    assert code == 200
    assert headers["X-Content-Type-Options"] == "nosniff"
    req = urllib.request.Request("http://127.0.0.1:1/")  # construction only: avoid accidental network call
    assert req.full_url
