from copy import deepcopy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from tools import data_sentinel as ds

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def _receipt(root, name, **provider):
    p = root / "automation_intelligence/provider_collection_v1/latest" / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"completed_at_utc": "2026-10-11T11:00:00Z", "catalog": provider.pop("catalog", {}),
                             "providers": {name: provider}}))


def _external_fabric(root, providers, generated_at="2026-10-11T11:30:00Z"):
    p = root / "automation_intelligence/cl_lab/external_data_fabric.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"generated_at": generated_at, "providers": providers}))


def test_verdicts_follow_the_receipts(tmp_path):
    _receipt(tmp_path, "massive", credential_present=False, status="BLOCKED_MISSING_CREDENTIAL")
    _receipt(tmp_path, "fred", credential_present=True, status="COLLECTED", collected_rows=50)
    _receipt(tmp_path, "fmp", credential_present=True, status="COLLECTED_PARTIAL", collected_rows=9,
             catalog={"denied_operations": 3})
    _receipt(tmp_path, "tiingo", credential_present=True, status="COLLECTED_PARTIAL", collected_rows=0)
    _receipt(tmp_path, "bybit", credential_present=False, status="NO_READY_JOBS")
    got = {s["source"]: s["verdict"] for s in ds.build(tmp_path, now=NOW)["sources"]}
    assert got["provider:massive"] == "BLOCKED"
    assert got["provider:fred"] == "OK"
    assert got["provider:fmp"] == "DEGRADED"
    assert got["provider:tiingo"] == "DEGRADED"
    assert got["provider:bybit"] == "DEGRADED"


def test_dedicated_live_fabric_prevents_false_blocked_provider(tmp_path):
    _receipt(tmp_path, "fmp", credential_present=True, status="BLOCKED", collected_rows=0,
             catalog={"denied_operations": 85})
    _receipt(tmp_path, "eodhd", credential_present=True, status="BLOCKED", collected_rows=0,
             catalog={"denied_operations": 7})
    _external_fabric(tmp_path, {
        "fmp": {"status": "ok", "calls": 3, "datasets": {"earnings_calendar": {"status": "ok", "rows": 51}}},
        "eodhd": {"status": "ok", "calls": 11, "datasets": {"eod_1y": {"status": "ok", "symbols": {"AAPL": {"rows": 251}}}}},
    })

    got = {s["source"]: s for s in ds.build(tmp_path, now=NOW)["sources"]}
    assert got["provider:fmp"]["verdict"] == "DEGRADED"
    assert got["provider:eodhd"]["verdict"] == "DEGRADED"
    assert "dedicated" in got["provider:fmp"]["why"].lower()
    assert "85" in got["provider:fmp"]["why"]
    assert "dedicated" in got["provider:eodhd"]["why"].lower()
    assert got["provider:fmp"]["rows"] == 51
    assert got["provider:eodhd"]["rows"] == 251


@pytest.mark.parametrize("stamp", [
    (NOW - timedelta(hours=80, seconds=1)).isoformat(),
    (NOW + timedelta(seconds=1)).isoformat(),
    None, "invalid", "2026-10-11T11:30:00", 123,
])
def test_expired_or_unverifiable_dedicated_receipt_cannot_mask_authentication_failure(tmp_path, stamp):
    _receipt(tmp_path, "fmp", credential_present=True, status="BLOCKED_AUTHENTICATION", collected_rows=0)
    _external_fabric(tmp_path, {
        "fmp": {"status": "ok", "calls": 3,
                "datasets": {"calendar": {"status": "ok", "rows": 51}}},
    }, generated_at=stamp)
    row = next(s for s in ds.build(tmp_path, now=NOW)["sources"] if s["source"] == "provider:fmp")
    assert row["verdict"] == "BLOCKED"
    assert row["rows"] == 0


def test_dedicated_delivery_reports_age_and_path_of_its_actual_evidence(tmp_path):
    _receipt(tmp_path, "fmp", credential_present=True, status="BLOCKED_AUTHENTICATION", collected_rows=0)
    _external_fabric(tmp_path, {
        "fmp": {"status": "partial", "calls": 3,
                "datasets": {"calendar": {"status": "ok", "rows": 51}}},
    }, generated_at=(NOW - timedelta(hours=80)).isoformat())
    row = next(s for s in ds.build(tmp_path, now=NOW)["sources"] if s["source"] == "provider:fmp")
    assert row["verdict"] == "DEGRADED"
    assert row["rows"] == 51
    assert row["age_h"] == 80.0
    assert row["path"] == "automation_intelligence/cl_lab/external_data_fabric.json"


def test_stale_dedicated_evidence_does_not_override_missing_credential(tmp_path):
    _receipt(tmp_path, "fmp", credential_present=False, status="BLOCKED_MISSING_CREDENTIAL", collected_rows=0)
    _external_fabric(tmp_path, {"fmp": {"status": "ok", "calls": 3}})
    got = {s["source"]: s for s in ds.build(tmp_path, now=NOW)["sources"]}
    assert got["provider:fmp"]["verdict"] == "BLOCKED"
    assert "no key" in got["provider:fmp"]["why"].lower()


def test_provider_manifest_points_to_real_external_fabric_evidence():
    root = Path(__file__).parents[1]
    manifest = json.loads((root / "config/data_ingestion_manifest.json").read_text(encoding="utf-8"))
    sources = {item["id"]: item for item in manifest["sources"]}
    expected = "automation_intelligence/cl_lab/external_data_fabric.json"
    for provider in ("fmp", "eodhd", "tiingo"):
        assert expected in sources[provider]["evidence_paths"]
        assert "automation_intelligence/external_data_fabric_v1/latest.json" not in sources[provider]["evidence_paths"]


def test_problems_sort_first_and_markdown_is_one_line_per_source(tmp_path):
    _receipt(tmp_path, "fred", credential_present=True, status="COLLECTED", collected_rows=50)
    feeds = tmp_path / "automation_intelligence/cl_lab/feeds_manifest.json"
    feeds.parent.mkdir(parents=True, exist_ok=True)
    feeds.write_text(json.dumps({"feeds": {"x": {"status": "error", "error": "422 | bad\nrange"}}}))
    report = ds.build(tmp_path, now=NOW)
    assert report["sources"][0]["verdict"] == "FAILING"
    md = ds.markdown(report)
    row = [line for line in md.splitlines() if line.startswith("| feed:x")][0]
    assert "\n" not in row and row.count("|") == 4


def test_missing_files_never_crash(tmp_path):
    report = ds.build(tmp_path, now=NOW)
    assert report["execution_authorized"] is False
    assert report["research"]["champions"] == 0


def test_rewrites_only_on_change_or_daily(tmp_path):
    _receipt(tmp_path, "fred", credential_present=True, status="COLLECTED", collected_rows=50)
    first = ds.build(tmp_path, now=NOW)
    later = ds.build(tmp_path, now=NOW.replace(hour=15))
    assert not ds.changed(first, later)
    assert ds.changed(first, ds.build(tmp_path, now=NOW.replace(day=12, hour=13)))
    _receipt(tmp_path, "fred", credential_present=False, status="BLOCKED_MISSING_CREDENTIAL")
    assert ds.changed(first, ds.build(tmp_path, now=NOW.replace(hour=13)))


def test_provider_row_count_change_triggers_refresh_with_same_verdict(tmp_path):
    _receipt(tmp_path, "fred", credential_present=True, status="COLLECTED", collected_rows=50)
    first = ds.build(tmp_path, now=NOW)
    refreshed = deepcopy(first)
    provider = next(source for source in refreshed["sources"] if source["source"] == "provider:fred")
    provider["rows"] += 1

    assert provider["verdict"] == next(
        source["verdict"] for source in first["sources"] if source["source"] == "provider:fred"
    )
    assert refreshed["generated_at"] == first["generated_at"]
    assert ds.changed(first, refreshed)


def test_report_carries_the_claude_chatgpt_mailbox(tmp_path):
    msg = tmp_path / "coordination/inbox/to-claude/20261011T0500Z-chatgpt-ask.md"
    msg.parent.mkdir(parents=True)
    msg.write_text("From: ChatGPT\nTo: Claude\nDate: 2026-10-11\nSubject: Ask\nReply-needed: yes\n\nBody\n")
    report = ds.build(tmp_path, now=NOW)
    assert report["coordination"]["awaiting_reply"]["claude"] == ["20261011T0500Z-chatgpt-ask.md"]
    assert "## Coordination (Claude, ChatGPT, Atlas)" in ds.markdown(report)
    quiet = ds.build(tmp_path, now=NOW)
    reply = tmp_path / "coordination/inbox/to-chatgpt/20261011T0600Z-claude-answer.md"
    reply.parent.mkdir(parents=True)
    reply.write_text(
        "From: Claude\nTo: ChatGPT\nDate: 2026-10-11\nSubject: Answer\nReply-needed: no\n"
        "Re: 20261011T0500Z-chatgpt-ask.md\n\nBody\n")
    assert ds.changed(quiet, ds.build(tmp_path, now=NOW))
