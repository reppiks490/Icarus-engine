import json
from datetime import datetime, timezone

from tools import data_sentinel as ds

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def _receipt(root, name, **provider):
    p = root / "automation_intelligence/provider_collection_v1/latest" / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"completed_at_utc": "2026-10-11T11:00:00Z", "catalog": provider.pop("catalog", {}),
                             "providers": {name: provider}}))


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
