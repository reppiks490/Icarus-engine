# CL (Claude, Anthropic) — 2026-10-04 — tests for cl_lab.watch (verdict logic and event-contract scan, offline)
import hashlib
import json
import os

from cl_lab import watch

OK = dict(conclusion="success", at="2026-10-04T12:00:00Z", sha="abc1234", url="u", event="push")


def test_verdicts():
    st = dict(canonical_gate=OK, engine_event_contract=OK, engine_tests=OK, peer_packet_age_s=60, malformed_events=[])
    assert watch.assess(st) == ("GREEN", [])
    assert watch.assess({**st, "peer_packet_age_s": 3557})[0] == "DEGRADED"
    v, r = watch.assess({**st, "canonical_gate": {**OK, "conclusion": "failure"}, "malformed_events": ["x"]})
    assert v == "RED" and len(r) == 2


def _blob(raw):
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def test_malformed_scan_honours_contract_and_exact_legacy(tmp_path):
    mi = tmp_path / "automation_intelligence/mcp_interface"
    (mi / "events").mkdir(parents=True)
    (mi / "contract.json").write_text(json.dumps({"required_fields": ["event_id", "at_utc", "surface"]}))
    good = json.dumps({"event_id": "a", "at_utc": "t", "surface": "s", "source": "FLOW_AUTOMATION"}).encode()
    bad = json.dumps({"event_id": "b", "source": "OMEGA_AUTOMATION"}).encode()
    legacy = json.dumps({"event_id": "c", "source": "AION_AUTOMATION"}).encode()
    other = json.dumps({"event_id": "d", "source": "SOMEONE_ELSE"}).encode()
    for n, raw in (("g.json", good), ("b.json", bad), ("l.json", legacy), ("o.json", other)):
        (mi / "events" / n).write_bytes(raw)
    (mi / "icarus_consumer_contract.json").write_text(json.dumps({
        "accepted_sources": ["FLOW_AUTOMATION", "OMEGA_AUTOMATION", "AION_AUTOMATION"],
        "event_validation": {"legacy_relaxed_blob_shas": [_blob(legacy)]}}))
    assert watch.malformed_events(str(tmp_path)) == ["b.json: missing at_utc,surface"]
