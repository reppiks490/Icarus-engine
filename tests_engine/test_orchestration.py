"""Workflow state/provenance tests. Model responses and returns are fixtures."""
import copy
import threading
import time
from http.client import IncompleteRead

import pytest

from icarus_engine import advisory
from icarus_engine.advisory import canonical_hash, AdvisoryError, ProviderOutcomeUnknown
from icarus_engine.orchestration import Budget, WorkflowJournal
from icarus_engine.pine.timeframe import Bar
from icarus_engine.research_service import ResearchWorkspace
from tests_engine.test_research_service import portfolio, qualified, event


@pytest.fixture
def models(monkeypatch):
    for key, value in {"OPENAI_API_KEY": "fixture-openai", "ANTHROPIC_API_KEY": "fixture-claude",
                       "ICARUS_OPENAI_MODEL": "exact-openai", "ICARUS_CLAUDE_MODEL": "claude-exact"}.items():
        monkeypatch.setenv(key, value)
    calls = []
    def answer(provider, candidate, evidence, prior, *, analysis_role=None):
        calls.append(analysis_role or provider)
        return {"candidate_hash": candidate["candidate_hash"], "provider": provider,
                "model": "exact-openai" if provider == "openai" else "claude-exact",
                "response_id": "response-" + candidate["candidate_hash"] + "-" + provider,
                "decision": "recommend" if provider == "openai" else "approve",
                "rationale": "Synthetic transport fixture", "risk_flags": []}
    monkeypatch.setattr(advisory, "_provider_review", answer)
    return calls


def finished(ws, ident):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        row = ws.analysis.job(ident)
        if row["status"] not in ("running", "queued", "unowned"):
            return row
        time.sleep(.01)
    pytest.fail("analysis worker did not finish")


def request(ws, apply=False):
    job = qualified(ws)
    evidence = ws.ledger.ingest_event(event())
    return {"job": job["id"], "evidence_ids": [evidence["event_id"]],
            "rationale": "Synthetic integration fixture", "apply": apply}


def test_real_ledger_five_stages_paper_activation_and_rollback(portfolio, models):
    ws = ResearchWorkspace(portfolio)
    r = portfolio.runners["NQ"]
    old = (r.em, r.em.closed, r.em.fills, r.em.netprofit, r.inputs_base.to_dict())
    body = request(ws, apply=True)
    done = finished(ws, ws.analysis.start(body)["id"])
    assert done["status"] == "complete", done
    assert set(models[:3]) == {"source-auditor", "risk-auditor", "regime-analyst"}
    assert models[3:] == ["openai", "anthropic"]
    assert done["result"]["applied"] is True
    assert (r.em, r.em.closed, r.em.fills, r.em.netprofit) == old[:4]
    assert r._activation_version_id == done["result"]["proposal_id"]
    restored = ws.rollback({"asset": "NQ", "operation_id": "test-rollback"})
    assert restored["status"] == "rolled_back"
    assert r.inputs_base.to_dict() == old[4]
    assert not list(ws.root.parent.glob("inputs*.json"))


def test_completed_analysis_is_idempotent_and_new_bars_do_not_invalidate_history(portfolio, models):
    ws = ResearchWorkspace(portfolio)
    body = request(ws)
    done = finished(ws, ws.analysis.start(body)["id"])
    assert done["status"] == "complete", done
    assert ws.analysis.start(body)["id"] == done["id"]
    assert len(models) == 5
    portfolio.runners["NQ"].on_sub_bar(Bar(3600, 101, 102, 100, 101, 1), 1, live=False)
    assert ws.export(done["result"]["proposal_id"])["research_qualified"]


def test_specialist_bundle_cannot_be_transplanted_to_different_study(portfolio, models):
    ws = ResearchWorkspace(portfolio)
    body = request(ws)
    done = finished(ws, ws.analysis.start(body)["id"])
    assert done["status"] == "complete", done
    artifact = done["result"]["artifact"]
    other_job = copy.deepcopy(ws.job(body["job"]))
    other_job["id"] = "b" * 16
    ws._save(other_job)
    candidate = copy.deepcopy(artifact["candidate"])
    candidate.pop("evidence_hash")
    candidate["validation"] = {**ws._validation(other_job), "analysis": candidate["validation"]["analysis"]}
    p = ws.ledger.propose(candidate)
    ws.ledger.review(p["proposal_id"], "openai")
    ws.ledger.review(p["proposal_id"], "anthropic")
    with pytest.raises(ValueError, match="exact study"):
        ws.export(p["proposal_id"])


def test_atomic_stage_budget_duplicate_and_uncertain_no_retry(tmp_path, models):
    journal = WorkflowJournal(tmp_path, Budget(max_daily_calls=1))
    ident, created = journal.create({"study": "fixture"})
    assert created and journal.claim(ident)
    entered, release = threading.Event(), threading.Event()
    calls, errors = [], []
    def transport():
        calls.append(1); entered.set(); assert release.wait(5)
        return {"ok": True}
    def work():
        try:
            journal.run_stage(ident, "one", {}, "openai", transport)
        except Exception as ex:
            errors.append(ex)
    worker = threading.Thread(target=work); worker.start()
    try:
        assert entered.wait(5)
        with pytest.raises(ValueError, match="already attempted"):
            journal.run_stage(ident, "one", {}, "openai", transport)
        with pytest.raises(ValueError, match="budget"):
            journal.run_stage(ident, "two", {}, "openai", transport)
    finally:
        release.set(); worker.join(5)
    assert calls == [1] and not errors
    assert journal.run_stage(ident, "one", {}, "openai", lambda: pytest.fail("duplicate")) == {"ok": True}
    ident2, _ = journal.create({"study": "cancel"})
    assert journal.cancel(ident2)["status"] == "cancelled"
    assert not journal.claim(ident2)


def test_first_observed_macro_is_explicit_and_never_backdated(portfolio):
    ws = ResearchWorkspace(portfolio)
    value = event()
    value.update(source="bls", source_url="https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0",
                 event_type="macro", observed_at=advisory._iso(time.time() - 90 * 86400),
                 published_at=None, timing_basis="first_observed")
    saved = ws.ledger.ingest_event(value)
    assert saved["published_at"] is None and "publication_time_unknown" in saved["quality_flags"]
    assert ws.ledger.events_as_of("NQ", advisory._iso(time.time() - 10)) == []
    assert ws.ledger.ingest_event(value)["received_at"] == saved["received_at"]


def test_truncated_http_response_is_uncertain_and_cannot_repeat(portfolio, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai")
    monkeypatch.setenv("ICARUS_OPENAI_MODEL", "exact-openai")
    ws = ResearchWorkspace(portfolio)
    body = request(ws)
    p = ws.propose_study({k: body[k] for k in ("job", "evidence_ids", "rationale")})
    calls = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def geturl(self): return "https://api.openai.com/v1/responses"
        def read(self, *args): raise IncompleteRead(b"partial", 100)
    class Opener:
        def open(self, *args, **kwargs): calls.append(1); return Response()
    monkeypatch.setattr(advisory, "build_opener", lambda *args: Opener())
    with pytest.raises(ProviderOutcomeUnknown):
        ws.ledger.review(p["proposal_id"], "openai")
    with pytest.raises(AdvisoryError, match="already attempted"):
        ws.ledger.review(p["proposal_id"], "openai")
    assert calls == [1]
