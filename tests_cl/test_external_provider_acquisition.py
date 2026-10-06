import gzip
import json
from pathlib import Path

import pytest

from cl_lab.data_fabric.acquisition import (
    AcquisitionBudget,
    ProviderHttpError,
    collect_json_pages,
    download_binary_dates,
    extract_records,
    source_times,
)


def test_extract_records_handles_common_envelopes_and_singletons():
    assert extract_records([{"x": 1}]) == [{"x": 1}]
    assert extract_records({"data": [{"x": 1}]}) == [{"x": 1}]
    assert extract_records({"trades": [{"x": 2}], "next_page": "n"}) == [{"x": 2}]
    assert extract_records({"ticker": "AAPL", "value": 3}) == [{"ticker": "AAPL", "value": 3}]


def test_source_times_are_conservative_for_point_in_time():
    event, publication, availability = source_times(
        {"transaction_date": "2026-10-01", "disclosure_date": "2026-10-04"},
        "2026-10-06T20:00:00Z",
    )
    assert event == "2026-10-01T00:00:00Z"
    assert publication == "2026-10-04T00:00:00Z"
    assert availability == "2026-10-06T20:00:00Z"  # date-only disclosure time is unknown; stay conservative

    event, publication, availability = source_times(
        {"report_date": "2025-12-31"}, "2026-10-06T20:00:00Z"
    )
    assert event == "2025-12-31T00:00:00Z"
    assert publication is None
    assert availability == "2026-10-06T20:00:00Z"  # never pretend report date was availability


def test_collect_json_pages_persists_raw_and_silver_and_follows_next_page(tmp_path, monkeypatch):
    monkeypatch.setenv("ICARUS_DATA_FABRIC_FORCE_JSONL", "1")
    calls = []
    bodies = {
        None: {"data": [{"ticker": "AAPL", "date": "2026-10-01", "v": 1}], "next_page": "abc"},
        "abc": {"data": [{"ticker": "AAPL", "date": "2026-10-02", "v": 2}], "next_page": None},
    }

    def requester(url, headers, params):
        cursor = params.get("next_page") if params else None
        calls.append(cursor)
        body = json.dumps(bodies[cursor], separators=(",", ":")).encode()
        return 200, {"content-type": "application/json"}, body

    budget = AcquisitionBudget(5)
    out = collect_json_pages(
        provider="intrinio",
        dataset="prices",
        endpoint="/prices",
        url="https://example.test/prices",
        headers={"Authorization": "Bearer secret"},
        params={},
        pagination="next_page",
        output_root=tmp_path,
        requester=requester,
        budget=budget,
        retrieval_time="2026-10-06T20:00:00Z",
        license_class="provider-restricted",
    )
    assert out["calls"] == 2
    assert out["records"] == 2
    assert out["complete"] is True
    assert calls == [None, "abc"]
    bronze = list((tmp_path / "bronze" / "intrinio" / "prices").rglob("*.gz"))
    silver = list((tmp_path / "silver" / "intrinio" / "prices").rglob("*.jsonl.gz"))
    assert len(bronze) == 2
    assert len(silver) == 2
    rows = []
    for p in silver:
        rows.extend(json.loads(line) for line in gzip.decompress(p.read_bytes()).decode().splitlines())
    assert {r["payload"]["v"] for r in rows} == {1, 2}
    assert all(r["availability_time"] == "2026-10-06T20:00:00Z" for r in rows)
    assert all("secret" not in str(r) for r in rows)


def test_budget_stops_with_checkpoint_cursor(tmp_path, monkeypatch):
    monkeypatch.setenv("ICARUS_DATA_FABRIC_FORCE_JSONL", "1")

    def requester(url, headers, params):
        cursor = params.get("next_page") if params else None
        nxt = "b" if cursor is None else "c"
        return 200, {}, json.dumps({"data": [{"id": cursor or "a"}], "next_page": nxt}).encode()

    out = collect_json_pages(
        provider="intrinio", dataset="x", endpoint="/x", url="https://x", headers={}, params={},
        pagination="next_page", output_root=tmp_path, requester=requester,
        budget=AcquisitionBudget(1), retrieval_time="2026-10-06T20:00:00Z",
        checkpoint_path=tmp_path / "checkpoint.json",
    )
    assert out["complete"] is False
    assert out["next_cursor"] == "b"
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text())
    assert checkpoint["next_cursor"] == "b"


def test_http_error_redacts_secret(tmp_path):
    def requester(url, headers, params):
        return 403, {}, b"forbidden secret-token plan"

    with pytest.raises(ProviderHttpError) as exc:
        collect_json_pages(
            provider="unusual_whales", dataset="x", endpoint="/x", url="https://x",
            headers={"Authorization": "Bearer secret-token"}, params={}, pagination="none",
            output_root=tmp_path, requester=requester, budget=AcquisitionBudget(1),
            retrieval_time="2026-10-06T20:00:00Z", secrets=["secret-token"],
        )
    assert "secret-token" not in str(exc.value)
    assert "HTTP 403" in str(exc.value)


def test_binary_date_downloader_skips_weekends_and_persists_exact_bytes(tmp_path):
    calls = []

    def requester(url, headers, params):
        calls.append(url)
        return 200, {"content-type": "application/zip"}, b"PK-test-bytes"

    out = download_binary_dates(
        provider="unusual_whales", dataset="option_full_tape",
        url_template="https://example.test/{date}", headers={}, start_date="2026-10-02", end_date="2026-10-05",
        output_root=tmp_path, requester=requester, budget=AcquisitionBudget(10),
        retrieval_time="2026-10-06T20:00:00Z",
    )
    assert out["calls"] == 2  # Fri + Mon, weekend omitted
    assert out["dates"] == ["2026-10-02", "2026-10-05"]
    stored = list((tmp_path / "bronze" / "unusual_whales" / "option_full_tape").rglob("*.gz"))
    assert len(stored) == 1  # content-addressed exact duplicate body is de-duplicated
    assert gzip.decompress(stored[0].read_bytes()) == b"PK-test-bytes"


def test_completed_checkpoint_restarts_from_first_page_for_future_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ICARUS_DATA_FABRIC_FORCE_JSONL", "1")
    cp = tmp_path / "checkpoint.json"
    cp.write_text(json.dumps({"complete": True, "next_page_index": 9, "next_offset": 900, "next_cursor": "old"}))
    seen = []

    def requester(url, headers, params):
        seen.append(dict(params))
        return 200, {}, json.dumps({"data": [], "next_page": None}).encode()

    collect_json_pages(
        provider="unusual_whales", dataset="refresh", endpoint="/x", url="https://x",
        headers={}, params={"limit": 50}, pagination="page", output_root=tmp_path,
        requester=requester, budget=AcquisitionBudget(1), retrieval_time="2026-10-06T21:00:00Z",
        checkpoint_path=cp,
    )
    assert seen == [{"limit": 50, "page": 0}]
