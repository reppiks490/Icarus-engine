import json
from pathlib import Path
from types import SimpleNamespace
import threading

from icarus_engine.adaptation import AdaptationScheduler
from icarus_engine.pine.timeframe import Bar
from icarus_engine.strategy.inputs import Inputs


class Calendar:
    def bucket_start(self, ts, minutes):
        return ts // (minutes * 60) * minutes * 60

    def bucket_end(self, ts, minutes):
        return self.bucket_start(ts, minutes) + minutes * 60

    def intraday_open(self, ts):
        return True


class FakeWorkspace:
    def __init__(self, root):
        self.root = root / "research"
        self.root.mkdir()
        runner = SimpleNamespace(lock=threading.RLock(), warm=True, bars=[], chart_minutes=1,
                                 cal=Calendar(), inputs_base=Inputs(),
                                 subbars=[(Bar(i * 60, 1, 2, 1, 2, 10), 1) for i in range(12)])
        self.port = SimpleNamespace(runners={"NQ": runner})
        self.ledger = SimpleNamespace(events_as_of=lambda asset, now: [{"event_id": "real-event"}])
        self.analysis = SimpleNamespace(journal=SimpleNamespace(status=lambda: {
            "budget": {"max_context_bytes": 48000, "max_output_tokens": 2048,
                       "max_daily_calls": 25, "max_daily_reserved_tokens": 500000},
            "reserved_calls": 0, "reserved_tokens": 0}))
        self.started = []
        self.studies = {}

    def start(self, request):
        self.started.append(request)
        return {"job": "a" * 16}

    def job(self, ident):
        return self.studies[ident]


def configured(scheduler):
    scheduler.configure({"enabled": True, "train_bars": 2, "validation_bars": 2,
                         "holdout_bars": 2, "cadence_seconds": 60,
                         "grids": {"NQ": {"use_cycle": [False]}}})


def test_disabled_default_and_provider_gate_before_bars(tmp_path):
    ws = FakeWorkspace(tmp_path)
    scheduler = AdaptationScheduler(ws)
    assert scheduler.status()["config"]["enabled"] is False
    configured(scheduler)
    scheduler.tick()
    assert scheduler.status()["assets"]["NQ"]["status"] == "blocked"
    assert ws.started == []


def test_durable_study_intent_blocks_duplicate_after_uncertain_launch(tmp_path):
    ws = FakeWorkspace(tmp_path)
    scheduler = AdaptationScheduler(ws)
    configured(scheduler)
    scheduler._providers_ready = lambda: True
    def uncertain(request):
        ws.started.append(request)
        raise RuntimeError("unknown launch outcome")
    ws.start = uncertain
    scheduler.tick()
    assert len(ws.started) == 1
    assert scheduler.status()["active"]["stage"] == "study_intent"
    scheduler.tick()
    restarted = AdaptationScheduler(ws)
    restarted._providers_ready = lambda: True
    restarted.tick()
    assert len(ws.started) == 1
    assert restarted.status()["active"]["status"] == "unowned_launch"


def test_no_candidate_same_dataset_is_not_researched_again(tmp_path):
    ws = FakeWorkspace(tmp_path)
    scheduler = AdaptationScheduler(ws)
    configured(scheduler)
    scheduler._providers_ready = lambda: True
    scheduler.tick()
    assert len(ws.started) == 1
    ws.studies["a" * 16] = {"status": "no_candidate", "result": {"research_qualified": False}, "error": None}
    scheduler.tick()
    assert scheduler.status()["assets"]["NQ"]["status"] == "no_candidate"
    state = json.loads(scheduler.path.read_text())
    state["assets"]["NQ"]["next_due"] = 0
    scheduler.path.write_text(json.dumps(state))
    scheduler.tick()
    assert len(ws.started) == 1


def test_revealed_watermark_prevents_holdout_reuse(tmp_path):
    ws = FakeWorkspace(tmp_path)
    scheduler = AdaptationScheduler(ws)
    configured(scheduler)
    scheduler._providers_ready = lambda: True
    import sqlite3
    with sqlite3.connect(str(ws.root / "holdouts.sqlite3")) as con:
        con.execute("CREATE TABLE revealed (asset TEXT PRIMARY KEY, until_ts INTEGER NOT NULL)")
        con.execute("INSERT INTO revealed VALUES ('NQ', 999999)")
    scheduler.tick()
    assert not ws.started
    assert "watermark" in scheduler.status()["assets"]["NQ"]["reason"]


def test_two_scheduler_instances_claim_only_one_launch(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    ws = FakeWorkspace(tmp_path)
    first, second = AdaptationScheduler(ws), AdaptationScheduler(ws)
    configured(first)
    first._providers_ready = second._providers_ready = lambda: True
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda s: s.tick(), [first, second]))
    assert len(ws.started) == 1
    assert all(r["active"]["job"] == "a" * 16 for r in results)
    assert sum(r["active"].get("status") == "unowned" for r in results) == 1


def test_study_launch_binds_apply_and_completes_full_analysis_chain(tmp_path):
    ws = FakeWorkspace(tmp_path)
    scheduler = AdaptationScheduler(ws)
    configured(scheduler)
    scheduler._providers_ready = lambda: True
    scheduler.tick()
    scheduler.configure({"apply": False})
    requests = []
    ws.studies["a" * 16] = {"status": "complete", "result": {"research_qualified": True}}
    ws.analysis.start = lambda req: requests.append(req) or {"id": "workflow"}
    ws.analysis.job = lambda ident: {"status": "running"}
    scheduler.tick()
    assert requests[0]["apply"] is True
    assert scheduler.status()["active"]["stage"] == "analysis"
    ws.analysis.job = lambda ident: {"status": "complete", "result": {"applied": True}}
    scheduler.tick()
    assert scheduler.status()["active"] is None
    assert scheduler.status()["assets"]["NQ"]["last_workflow"] == "workflow"


def test_restart_abandons_confirmed_dead_owner_without_replaying_interval(tmp_path, monkeypatch):
    ws = FakeWorkspace(tmp_path)
    first = AdaptationScheduler(ws)
    configured(first)
    first._providers_ready = lambda: True
    first.tick()
    second = AdaptationScheduler(ws)
    second._providers_ready = lambda: True
    monkeypatch.setattr("icarus_engine.adaptation.process_identity", lambda pid: False)
    second.tick()
    state = second.status()
    assert state["active"] is None and state["assets"]["NQ"]["status"] == "interrupted"
    state["assets"]["NQ"]["next_due"] = 0
    second.path.write_text(json.dumps(state))
    second.tick()
    assert len(ws.started) == 1


def test_process_identity_is_stable_for_current_process():
    import os
    from icarus_engine.process_identity import identity
    assert identity(os.getpid()) not in (False, None)
    assert identity(os.getpid()) == identity(os.getpid())
