"""Real HTTP/SQLite/local-thread integration; all price history is synthetic."""
from datetime import datetime, timezone
import hashlib
import hmac
from http.client import HTTPConnection
import json
import threading
import time

import pytest

from icarus_engine.assets import AssetSpec
from icarus_engine.pine.timeframe import Bar
from icarus_engine.runtime import AssetRunner, Journal, Portfolio, RunnerConfig
from icarus_engine.strategy.inputs import Inputs
from icarus_engine.research_service import ResearchWorkspace
from icarus_engine.server import serve
from icarus_engine import research_service
from icarus_engine.research import Policy, Windows, run_search


@pytest.fixture
def portfolio(tmp_path):
    journal = Journal(":memory:")
    port = Portfolio(journal, str(tmp_path))
    spec = AssetSpec("NQ", "Synthetic fixture", "yahoo", "NQ", "crypto", .25, 1,
                     chart_tf="1", capital=100000, commission=1, roll="none")
    r = AssetRunner(RunnerConfig(spec, Inputs(use_tide=False, use_eod_flat=False),
                                pts_ref_price=0, fixed_pts_scale=1, mintick=.25), journal)
    r.paused = True
    for i in range(60):
        r.on_sub_bar(Bar(i * 60, 100, 102, 99, 101, 1), 1, live=False)
    r.warm = True
    port.runners["NQ"], port.order = r, ["NQ"]
    yield port
    journal.con.close()


def body():
    return {"asset": "NQ", "grid": {"conf_min_votes": [5]},
            "windows": {"train_start": 0, "train_end": 600, "validation_start": 660,
                        "validation_end": 1800, "holdout_start": 1860, "holdout_end": 3600},
            "policy": {"max_trials": 1, "max_seconds": 10}}


def wait_job(ws, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = ws.job(job_id)
        if job["status"] != "running":
            return job
        time.sleep(.01)
    pytest.fail("research job did not finish")


def test_real_frozen_study_does_not_change_live_runner(portfolio):
    ws = ResearchWorkspace(portfolio)
    r = portfolio.runners["NQ"]
    before = (r.inputs_base.to_dict(), r.em, len(r.em.fills), r.paused)
    job = wait_job(ws, ws.start(body())["job"])
    assert job["status"] == "no_candidate" and job["result"]["holdout"] is None
    assert (r.inputs_base.to_dict(), r.em, len(r.em.fills), r.paused) == before
    assert not list(ws.root.parent.glob("inputs*.json"))
    assert ResearchWorkspace(portfolio).job(job["id"]) == job


def test_one_job_cancel_and_interrupted_disk_recovery(portfolio, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def search(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"status": "cancelled" if kwargs["cancelled"]() else "complete"}
    monkeypatch.setattr(research_service, "run_search", search)
    ws = ResearchWorkspace(portfolio)
    try:
        job_id = ws.start(body())["job"]
        assert entered.wait(5)
        with pytest.raises(ValueError, match="one research"):
            ws.start(body())
        assert ResearchWorkspace(portfolio).job(job_id)["status"] == "interrupted"
        ws.cancel(job_id)
    finally:
        release.set()
    assert wait_job(ws, job_id)["status"] == "cancelled"


def test_bad_study_does_not_start_or_write(portfolio):
    ws = ResearchWorkspace(portfolio)
    for change in ({"windows": {}}, {"grid": {"tp1_pts": [True]}}, {"asset": "MISSING"},
                   {"policy": {"max_trials": 1001}}):
        with pytest.raises((ValueError, TypeError)):
            ws.start({**body(), **change})
    with pytest.raises(ValueError, match="requires"):
        ws.start({})
    assert ws._active is None and not ws.root.exists()


def qualified(ws):
    # Deterministic workflow fixture, never represented as a market result.
    frozen, dataset, baseline, config = ws.fingerprints("NQ", 3600)
    def evaluate(patch, start, end, **costs):
        # Actual replay provenance; injected returns ONLY for workflow-state tests.
        result = research_service.run_backtest(frozen, "NQ", inputs=patch, fill_on="real",
                                              window_start=start, window_end=end, **costs)
        pnl = (60 if patch else 1) - max(0, costs.get("commission", 1) - 1) - costs.get("slippage_ticks", 0)
        result.update(trades=[{"type": "long", "entry_ts": start + i * 2, "entry_px": 100,
                               "entry_signal": "L", "exit_ts": start + i * 2 + 1,
                               "pnl": pnl, "open": False} for i in range(30)],
                      summary={"max_drawdown": {"all": 1}},
                      equity=[[start, 100000], [end, 100000 + 30 * pnl]])
        return result
    ws.root.mkdir(exist_ok=True)
    result = run_search("NQ", {"conf_min_votes": [5]}, Windows(**body()["windows"]), evaluate,
                        dataset_hash=dataset, baseline_hash=baseline,
                        holdout_ledger=ws.root / "holdouts.sqlite3", policy=Policy(), stress_evaluate=evaluate)
    job = {"id": "a" * 16, "status": "complete", "asset": "NQ", "baseline": config,
           "dataset_hash": dataset, "baseline_hash": baseline, "result": result, "data_cutoff": 3600}
    ws._save(job)
    return job


def event():
    now = time.time()
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
    return {"schema_version": 1, "source": "cftc", "source_event_id": "fixture", "revision_id": "1",
            "source_url": "https://publicreporting.cftc.gov/fixture", "event_type": "cot",
            "asset_ids": ["NQ"], "instrument_id": "000001", "observed_at": iso(now - 86400),
            "published_at": iso(now - 60), "values": {"net": 3}, "units": {"net": "contracts"},
            "report_family": "fixture-only"}


def test_proposal_binds_qualified_study_and_current_source(portfolio):
    ws = ResearchWorkspace(portfolio)
    job = qualified(ws)
    evidence = ws.ledger.ingest_event(event())
    request = {"job": job["id"], "evidence_ids": [evidence["event_id"]], "rationale": "Test fixture"}
    p = ws.propose_study(request)
    assert p["candidate"]["inputs"] == job["result"]["selected"]
    assert p["candidate"]["validation"]["study_id"] == job["id"] and p["state"] == "proposed"
    with pytest.raises(ValueError, match="requires.*approval"):
        ws.export(p["proposal_id"])
    with pytest.raises(ValueError, match="only"):
        ws.propose_study({**request, "inputs": {"tp1_pts": 9}})
    portfolio.runners["NQ"].inputs_base.tp1_pts += 1
    with pytest.raises(ValueError, match="differs"):
        ws.propose_study(request)


@pytest.mark.parametrize("clock_value", [1789596961.6983159, 1789596993.3191075])
def test_claimed_model_validation_cannot_replace_study(portfolio, monkeypatch, clock_value):
    # A frozen sub-microsecond clock must not round the decision into the future.
    monkeypatch.setattr(time, "time", lambda: clock_value)
    ws = ResearchWorkspace(portfolio)
    job = qualified(ws)
    evidence = ws.ledger.ingest_event(event())
    p = ws.propose_study({"job": job["id"], "evidence_ids": [evidence["event_id"]], "rationale": "Fixture"})
    job["result"]["research_qualified"] = False
    ws._save(job)
    with pytest.raises(ValueError, match="qualified study"):
        ws.export(p["proposal_id"])


@pytest.fixture
def http(portfolio):
    srv = serve(portfolio, 0, "test-token", start=False)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    def request(method, path, raw=None, headers=None):
        conn = HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
        try:
            conn.request(method, path, body=raw, headers=headers or {})
            response = conn.getresponse()
            content = response.read()
            return response.status, content
        finally:
            conn.close()
    yield request
    srv.shutdown(); srv.server_close(); thread.join(5)


def test_http_auth_static_json_validation_and_no_provider_calls(http, monkeypatch):
    import icarus_engine.advisory as advisory
    monkeypatch.setattr(advisory, "_provider_review", lambda *a: pytest.fail("unexpected model call"))
    assert http("GET", "/api/research")[0] == 401
    status, data = http("GET", "/api/research", headers={"Authorization": "Bearer test-token"})
    assert status == 200
    data = json.loads(data)
    assert data["execution_authorized"] is False and data["assets"][0]["warm"] is True
    assert http("GET", "/research-ui.js")[0] == 200
    assert http("GET", "/", headers={"Host": "evil.example"})[0] == 403
    auth = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}
    for raw in (b'{}', b'{"asset":"NQ","asset":"NQ"}', b'[]'):
        assert http("POST", "/admin/research/studies", raw, auth)[0] == 400
    assert http("POST", "/admin/research/proposals", b'{"validation":{"approved":true}}', auth)[0] == 400


def test_http_adaptation_lifecycle_is_authenticated_and_opt_in(http, monkeypatch):
    from icarus_engine.advisory import _PROVIDERS
    for _, key, _ in _PROVIDERS.values():
        monkeypatch.delenv(key, raising=False)
    auth = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}
    assert http("GET", "/api/research/adaptation")[0] == 401
    code, raw = http("GET", "/api/research/adaptation", headers=auth)
    assert code == 200 and json.loads(raw)["running"] is False
    assert http("POST", "/admin/research/adaptation", b'{"enabled":true}')[0] == 401
    code, raw = http("POST", "/admin/research/adaptation", b'{"enabled":true}', auth)
    assert code == 200 and json.loads(raw)["running"] is True
    code, raw = http("POST", "/admin/research/adaptation", b'{"enabled":false}', auth)
    assert code == 200 and json.loads(raw)["running"] is False
    assert http("POST", "/admin/research/adaptation", b'{"enabled":"true"}', auth)[0] == 400
    assert http("GET", "/sources-ui.js")[0] == 200


def test_http_signed_ingestion_replay_and_unconfigured_receiver(http, monkeypatch):
    monkeypatch.delenv("ICARUS_INGEST_SECRET", raising=False)
    raw = json.dumps(event()).encode()
    assert http("POST", "/research/events", raw)[0] == 503
    secret, timestamp = "x" * 32, str(int(time.time()))
    monkeypatch.setenv("ICARUS_INGEST_SECRET", secret)
    assert http("POST", "/research/events", raw)[0] == 401
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    headers = {"X-Icarus-Timestamp": timestamp, "X-Icarus-Signature": signature}
    status, data = http("POST", "/research/events", raw, headers)
    assert status == 200 and json.loads(data)["execution_authorized"] is False
    assert http("POST", "/research/events", raw, headers)[0] == 400
    assert http("GET", "/api/research/events?asset=NQ")[0] == 401
    status, data = http("GET", "/api/research/events?asset=NQ", headers={"Authorization": "Bearer test-token"})
    assert status == 200
    record = json.loads(data)["events"][0]
    assert record["source_event_id"] == "fixture" and record["received_at"]
