"""No network, no credentials, no runtime mutation: exercise the actual provider seam."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import hmac
import json
import sqlite3

import pytest

from icarus_engine import advisory
from icarus_engine.advisory import AdvisoryError, AdvisoryLedger, canonical_hash, strict_json

NOW = 1789560000.0


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def event(**changes):
    value = {"schema_version": 1, "source": "cftc", "source_event_id": "report-1", "revision_id": "v1",
             "source_url": "https://publicreporting.cftc.gov/report", "event_type": "cot", "asset_ids": ["NQ"],
             "instrument_id": "209742", "observed_at": iso(NOW - 86400), "published_at": iso(NOW - 60),
             "values": {"net_contracts": 12}, "units": {"net_contracts": "contracts"},
             "report_family": "disaggregated-futures-only"}
    return {**value, **changes}


@pytest.fixture
def ledger(tmp_path):
    return AdvisoryLedger(tmp_path / "research.sqlite3", {"cftc": ["publicreporting.cftc.gov"]})


def proposal(ledger, **changes):
    evidence = ledger.ingest_event(event(), now=NOW)
    value = {"schema_version": 1, "asset": "NQ", "inputs": {"tp1_pts": 20.0},
             "baseline_hash": "a" * 64, "dataset_hash": "b" * 64, "evidence_ids": [evidence["event_id"]],
             "decision_at": iso(NOW), "expires_at": iso(NOW + 600), "rationale": "Bounded paper research only",
             "validation": {"out_of_sample": True, "sample_count": 90, "costs_included": True}}
    return ledger.propose({**value, **changes}, now=NOW)


def test_delayed_older_revision_cannot_replace_newer_publication(ledger):
    newest = ledger.ingest_event(event(revision_id="v2", published_at=iso(NOW - 5)), now=NOW)
    p = proposal(ledger, evidence_ids=[newest["event_id"]])
    # Delivering v1 later does not make it newer than v2.
    ledger.ingest_event(event(revision_id="v0", published_at=iso(NOW - 120)), now=NOW + 10)
    assert ledger.events_as_of("NQ", iso(NOW + 10))[0]["event_id"] == newest["event_id"]
    assert ledger.get_proposal(p["proposal_id"], now=NOW + 10)["state"] == "proposed"


@pytest.fixture
def transport(monkeypatch):
    calls = []
    settings = {"decision": None, "hash": None, "model": None, "status": "completed", "stop_reason": "end_turn",
                "response_id": None, "raw": None, "callback": None}
    for name, value in {"OPENAI_API_KEY": "test-openai-secret-never-save", "ICARUS_OPENAI_MODEL": "gpt-test",
                        "ANTHROPIC_API_KEY": "test-claude-secret-never-save", "ICARUS_CLAUDE_MODEL": "claude-test"}.items():
        monkeypatch.setenv(name, value)

    class Response:
        status = 200

        def __init__(self, request):
            self.request = request

        def geturl(self):
            return self.request.full_url

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            if settings["callback"]:
                settings["callback"]()
            if settings["raw"] is not None:
                return settings["raw"]
            request = json.loads(self.request.data)
            is_openai = self.request.full_url.endswith("responses")
            context = json.loads(request["input"] if is_openai else request["messages"][0]["content"])
            result = {"candidate_hash": settings["hash"] or context["candidate"]["candidate_hash"],
                      "decision": settings["decision"] or ("recommend" if is_openai else "approve"),
                      "rationale": "Fixture review of exact candidate", "risk_flags": []}
            common = {"id": settings["response_id"] or ("resp-1" if is_openai else "msg-1"),
                      "model": settings["model"] or request["model"]}
            if is_openai:
                common.update(status=settings["status"], output=[{"type": "message", "role": "assistant",
                              "content": [{"type": "output_text", "text": json.dumps(result)}]}])
            else:
                common.update(type="message", role="assistant", stop_reason=settings["stop_reason"],
                              content=[{"type": "text", "text": json.dumps(result)}])
            return json.dumps(common).encode()

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert timeout == 30
            return Response(request)

    monkeypatch.setattr(advisory, "build_opener", lambda *args: Opener())
    return calls, settings


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}',
                                  b'[]', b'null', b'"x"', b'{' + b' ' * 131073 + b'}',
                                  ('{"x":' * 20 + '0' + '}' * 20).encode()], ids=range(9))
def test_strict_json_rejects_hostile_payload(raw):
    with pytest.raises(AdvisoryError):
        strict_json(raw)


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"source": "unknown"}, {"source_url": "https://evil.invalid/report"},
    {"source_url": "https://publicreporting.cftc.gov@evil.invalid"},
    {"source_url": "http://publicreporting.cftc.gov/report"}, {"source_url": "https://publicreporting.cftc.gov:999/report"},
    {"received_at": iso(NOW - 100)}, {"published_at": None}, {"published_at": "2026-09-16T01:00:00"},
    {"published_at": iso(NOW + 1)}, {"observed_at": iso(NOW + 1)}, {"observed_at": iso(NOW - 36 * 86400)},
    {"values": {"net_contracts": True}}, {"values": {"net_contracts": float("nan")}},
    {"asset_ids": ["NQ", "NQ"]}, {"asset_ids": ["typo"]}, {"approved": True}, {"role": "claude"},
    {"units": {}}, {"event_type": "correlation", "values": {"net_contracts": 1.01}},
])
def test_ingest_validation_and_rejection_audit(ledger, changes):
    with pytest.raises(AdvisoryError):
        ledger.ingest_event(event(**changes), now=NOW)
    assert ledger.status(now=NOW)["counts"] == {"events": 0, "proposals": 0, "reviews": 0, "rejections": 1}


def test_receipt_and_publication_are_both_required_as_of(ledger):
    original = ledger.ingest_event(event(), now=NOW)
    assert ledger.events_as_of("NQ", iso(NOW - 1)) == []
    assert ledger.events_as_of("ES", iso(NOW)) == []
    assert ledger.events_as_of("NQ", iso(NOW)) == [original]
    duplicate = ledger.ingest_event(event(), now=NOW + 10)
    assert duplicate["received_at"] == original["received_at"]
    revised = ledger.ingest_event(event(revision_id="v2", published_at=iso(NOW + 1)), now=NOW + 2)
    assert ledger.events_as_of("NQ", iso(NOW + 1)) == [original]
    assert ledger.events_as_of("NQ", iso(NOW + 2)) == [revised]
    with pytest.raises(AdvisoryError, match="different content"):
        ledger.ingest_event(event(values={"net_contracts": 99}), now=NOW)


def test_revision_at_identical_receipt_time_uses_insertion_order(ledger):
    original = ledger.ingest_event(event(), now=NOW)
    revised = ledger.ingest_event(event(revision_id="v2"), now=NOW)
    assert original["event_id"] != revised["event_id"]
    assert ledger.events_as_of("NQ", iso(NOW)) == [revised]


def test_evidence_unavailable_or_wrong_asset_cannot_enter_proposal(ledger):
    with pytest.raises(AdvisoryError, match="unavailable"):
        proposal(ledger, decision_at=iso(NOW - 1))
    with pytest.raises(AdvisoryError, match="unavailable"):
        proposal(ledger, asset="ES")


@pytest.mark.parametrize("patch", [{"tp1_pts": True}, {"tp1_pts": float("inf")}, {"qty_contracts": 1.0},
                                  {"qty_contracts": 0}, {"use_session": 1}, {"unknown": 1},
                                  {"point_value": "20"}, {"tp1_pts": 10**200}, {}])
def test_input_types_and_ranges(ledger, patch):
    with pytest.raises(AdvisoryError):
        proposal(ledger, inputs=patch)


def test_all_known_inputs_can_be_proposed_including_rate_settings(ledger):
    result = proposal(ledger, inputs={"rate_atr_len": 10, "use_session": True, "tp1_pts": 100.0})
    assert result["state"] == "proposed"


def test_no_implicit_provider_calls_and_no_manual_approval(ledger, transport):
    calls, _ = transport
    item = proposal(ledger)
    ledger.status(now=NOW)
    assert calls == []
    with pytest.raises(AdvisoryError):
        ledger.review(item["proposal_id"], "claude", now=NOW)
    with pytest.raises(AdvisoryError):
        ledger.review(item["proposal_id"], "anthropic", now=NOW)
    with pytest.raises(AdvisoryError):
        ledger.export_candidate(item["proposal_id"], "a" * 64, "b" * 64, now=NOW)
    assert calls == []


def test_dual_provider_review_exports_only_hash_bound_candidate(ledger, transport, tmp_path):
    calls, _ = transport
    live = tmp_path / "inputs.NQ.json"
    live.write_text('{"tp1_pts":15}', encoding="utf-8")
    item = proposal(ledger)
    pid = item["proposal_id"]
    assert ledger.review(pid, "openai", now=NOW)["state"] == "advised"
    assert ledger.review(pid, "anthropic", now=NOW)["state"] == "approved"
    artifact = ledger.export_candidate(pid, "a" * 64, "b" * 64, now=NOW)
    assert artifact["execution_authorized"] is False
    assert canonical_hash(artifact["candidate"]) == artifact["candidate_hash"] == pid
    assert [r["provider"] for r in artifact["reviews"]] == ["anthropic", "openai"]
    assert live.read_text(encoding="utf-8") == '{"tp1_pts":15}'
    assert [r.full_url for r in calls] == ["https://api.openai.com/v1/responses", "https://api.anthropic.com/v1/messages"]
    assert b"test-openai-secret-never-save" not in (tmp_path / "research.sqlite3").read_bytes()
    assert b"test-claude-secret-never-save" not in (tmp_path / "research.sqlite3").read_bytes()
    for baseline, dataset in [("c" * 64, "b" * 64), ("a" * 64, "c" * 64)]:
        with pytest.raises(AdvisoryError, match="differs"):
            ledger.export_candidate(pid, baseline, dataset, now=NOW)
    with pytest.raises(AdvisoryError):
        ledger.export_candidate(pid, "a" * 64, "b" * 64, now=NOW + 601)


@pytest.mark.parametrize("settings", [{"hash": "0" * 64}, {"model": "unconfigured-model"},
                                     {"decision": "approve"}, {"status": "incomplete"}, {"raw": b'{"approved":true}'}])
def test_forged_incomplete_or_wrong_candidate_provider_response_fails_closed(ledger, transport, settings):
    _, controls = transport
    controls.update(settings)
    pid = proposal(ledger)["proposal_id"]
    with pytest.raises(AdvisoryError):
        ledger.review(pid, "openai", now=NOW)
    assert ledger.get_proposal(pid, now=NOW)["reviews"] == []


def test_provider_rejection_is_final(ledger, transport):
    _, settings = transport
    settings["decision"] = "reject"
    pid = proposal(ledger)["proposal_id"]
    assert ledger.review(pid, "openai", now=NOW)["state"] == "rejected"
    with pytest.raises(AdvisoryError):
        ledger.review(pid, "anthropic", now=NOW)


def test_revision_and_clock_change_during_review_prevent_commit(ledger, transport):
    _, settings = transport
    pid = proposal(ledger)["proposal_id"]
    # Distinct receipt times establish the later revision unambiguously.
    settings["callback"] = lambda: ledger.ingest_event(event(revision_id="v2"), now=NOW + 1)
    with pytest.raises(AdvisoryError, match="changed or expired"):
        ledger.review(pid, "openai", now=NOW + 2)
    assert ledger.get_proposal(pid, now=NOW + 2)["state"] == "invalidated"


def test_actual_clock_rechecked_after_provider_delay(ledger, transport, monkeypatch):
    _, settings = transport
    pid = proposal(ledger)["proposal_id"]
    monkeypatch.setattr(advisory.time, "time", lambda: NOW)
    settings["callback"] = lambda: monkeypatch.setattr(advisory.time, "time", lambda: NOW + 601)
    with pytest.raises(AdvisoryError, match="changed or expired"):
        ledger.review(pid, "openai")
    assert ledger.get_proposal(pid)["reviews"] == []


def test_claude_truncation_and_model_identity_fail_closed(ledger, transport):
    _, settings = transport
    pid = proposal(ledger)["proposal_id"]
    ledger.review(pid, "openai", now=NOW)
    settings["stop_reason"] = "max_tokens"
    with pytest.raises(AdvisoryError, match="incomplete"):
        ledger.review(pid, "anthropic", now=NOW)
    settings["stop_reason"] = "end_turn"
    settings["model"] = "claude-forged"
    with pytest.raises(AdvisoryError, match="different model"):
        ledger.review(pid, "anthropic", now=NOW)
    assert len(ledger.get_proposal(pid, now=NOW)["reviews"]) == 1


def test_duplicate_provider_response_id_cannot_approve_another_proposal(ledger, transport):
    first = proposal(ledger)["proposal_id"]
    ledger.review(first, "openai", now=NOW)
    second = proposal(ledger, inputs={"tp1_pts": 30.0})["proposal_id"]
    with pytest.raises(AdvisoryError, match="duplicate"):
        ledger.review(second, "openai", now=NOW)
    assert ledger.get_proposal(second, now=NOW)["reviews"] == []


def test_immutable_ledger_and_tamper_detection(ledger):
    pid = proposal(ledger)["proposal_id"]
    with sqlite3.connect(ledger.path) as con:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            con.execute("UPDATE advisory_proposals SET body='{}'")
        con.execute("DROP TRIGGER advisory_proposals_update")
        con.execute("UPDATE advisory_proposals SET body='{}'")
    with pytest.raises(AdvisoryError, match="integrity"):
        ledger.get_proposal(pid, now=NOW)


def test_refuses_live_journal_database(tmp_path):
    path = tmp_path / "live.sqlite3"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE trades (id INTEGER)")
    with pytest.raises(AdvisoryError, match="separate"):
        AdvisoryLedger(path)
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("trades",)]


def test_concurrent_idempotent_ingest_closes_connections(ledger):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: ledger.ingest_event(event(), now=NOW), range(12)))
    assert len({item["event_id"] for item in results}) == 1
    assert ledger.status(now=NOW)["counts"]["events"] == 1
    with sqlite3.connect(ledger.path, timeout=0) as con:
        con.execute("BEGIN EXCLUSIVE")


def test_signed_ingest_timestamp_signature_and_replay(ledger):
    raw = json.dumps(event()).encode()
    secret, timestamp = "z" * 32, str(int(NOW))
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    result = ledger.ingest_signed_event(raw, timestamp, signature, secret, now=NOW)
    assert result["received_at"].endswith("Z")
    with pytest.raises(AdvisoryError, match="replay"):
        ledger.ingest_signed_event(raw, timestamp, signature, secret, now=NOW + 1)
    with pytest.raises(AdvisoryError, match="signature"):
        ledger.ingest_signed_event(raw + b" ", timestamp, signature, secret, now=NOW)
    with pytest.raises(AdvisoryError, match="window"):
        ledger.ingest_signed_event(raw, timestamp, signature, secret, now=NOW + 301)


def test_provider_unconfigured_and_error_do_not_leak_secrets(ledger, monkeypatch, transport):
    pid = proposal(ledger)["proposal_id"]
    monkeypatch.delenv("ICARUS_OPENAI_MODEL")
    with pytest.raises(AdvisoryError, match="configure"):
        ledger.review(pid, "openai", now=NOW)
    monkeypatch.setenv("ICARUS_OPENAI_MODEL", "gpt-test")

    class Failure:
        def open(self, *args, **kwargs):
            raise OSError("test-openai-secret-never-save")

    monkeypatch.setattr(advisory, "build_opener", lambda *args: Failure())
    with pytest.raises(AdvisoryError) as error:
        ledger.review(pid, "openai", now=NOW)
    assert "secret" not in str(error.value)
    assert ledger.status(now=NOW)["counts"]["reviews"] == 0


def test_cli_status_stays_offline_and_ascii(tmp_path, capsys):
    from icarus_engine.advisory_cli import main
    assert main(["--db", str(tmp_path / "advisory.sqlite3"), "status"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["execution_enabled"] is False
    assert result["counts"]["reviews"] == 0


def test_cli_explicit_review_pipeline(tmp_path, capsys, monkeypatch, transport):
    from icarus_engine.advisory_cli import main
    monkeypatch.setattr(advisory.time, "time", lambda: NOW)
    source_path, event_path, proposal_path = (tmp_path / name for name in ("sources.json", "event.json", "proposal.json"))
    source_path.write_text(json.dumps({"cftc": ["publicreporting.cftc.gov"]}), encoding="utf-8")
    event_path.write_text(json.dumps(event()), encoding="utf-8")
    args = ["--db", str(tmp_path / "ledger.sqlite3"), "--sources", str(source_path)]
    assert main(args + ["ingest", str(event_path)]) == 0
    event_id = json.loads(capsys.readouterr().out)["event_id"]
    proposal_path.write_text(json.dumps({
        "schema_version": 1, "asset": "NQ", "inputs": {"tp1_pts": 20}, "baseline_hash": "a" * 64,
        "dataset_hash": "b" * 64, "evidence_ids": [event_id], "decision_at": iso(NOW),
        "expires_at": iso(NOW + 600), "rationale": "CLI integration fixture",
    }), encoding="utf-8")
    assert main(args + ["propose", str(proposal_path)]) == 0
    pid = json.loads(capsys.readouterr().out)["proposal_id"]
    for provider, state in (("openai", "advised"), ("anthropic", "approved")):
        assert main(args + ["review", pid, "--provider", provider]) == 0
        assert json.loads(capsys.readouterr().out)["state"] == state
    assert main(args + ["export", pid, "--baseline-hash", "a" * 64, "--dataset-hash", "b" * 64]) == 0
    assert json.loads(capsys.readouterr().out)["execution_authorized"] is False
