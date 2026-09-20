"""Causal vendor-snapshot and instrument tests; values below are synthetic."""
import json
import time
from urllib.parse import unquote, urlsplit

from icarus_engine.advisory import AdvisoryLedger
from icarus_engine.market_sources import MarketSources


def fixture(sources, monkeypatch, direction=1):
    now = int(time.time())
    base = now // 3600 * 3600 - 50 * 3600
    def fetch(url, headers=None):
        ticker = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        prices, value = [], 100.
        for i in range(50):
            change = (.003 if i % 2 else -.002) * (direction if ticker == "NQ=F" else 1)
            value *= 1 + change
            prices.append(value)
        # Forming bar must be omitted even when receipt is after its close.
        result = {"meta": {"symbol": ticker, "regularMarketTime": base + 49 * 3600 + 100},
                  "timestamp": [base + i * 3600 for i in range(50)],
                  "indicators": {"quote": [{"close": prices}]}}
        return json.dumps({"chart": {"result": [result]}}).encode(), {}, time.time_ns()
    monkeypatch.setattr(sources, "_fetch", fetch)
    return base


def test_signed_correlations_exclude_forming_and_keep_first_receipt(tmp_path, monkeypatch):
    ledger = AdvisoryLedger(tmp_path / "ledger.sqlite3", allowed_sources={"yahoo-dxy": ["query1.finance.yahoo.com"]})
    sources = MarketSources(tmp_path, ledger)
    base = fixture(sources, monkeypatch, direction=-1)
    report = sources.collect("yahoo-dxy", {"assets": ["NQ"]})
    assert report["status"] == "collected" and len(report["event_ids"]) == 1 and not report["warnings"]
    first = sources.records(asset="NQ")["records"][0]
    assert first["values"]["pearson"] < -.99999
    assert first["data"]["pairs"] == 48
    assert first["data"]["window_end"] == base + 49 * 3600
    assert first["published_at"] is None
    assert ledger.events_as_of("NQ", first["observed_at"]) == []
    again = sources.collect("yahoo-dxy", {"assets": ["NQ"]})
    assert again["event_ids"] == report["event_ids"]
    assert sources.records(asset="NQ")["records"] == [first]


def test_positive_correlation_and_insufficient_sample_are_distinct(tmp_path, monkeypatch):
    sources = MarketSources(tmp_path, None)
    fixture(sources, monkeypatch)
    sources.collect("yahoo-dxy", {"assets": ["NQ"]})
    first = sources.records(asset="NQ")["records"][0]
    assert first["values"]["pearson"] > .99999
    assert sources.collect("yahoo-dxy", {"assets": ["NQ"], "min_pairs": 100})["status"] == "collected"
    last = sources.records(asset="NQ")["records"][0]
    assert last["values"] == {} and last["data"]["correlation"] is None
    assert sources.advisory_event(last) is None


def test_instrument_mismatch_is_not_recorded(tmp_path, monkeypatch):
    sources = MarketSources(tmp_path, None)
    monkeypatch.setattr(sources, "_fetch", lambda *a, **kw: (
        json.dumps({"chart": {"result": [{"meta": {"symbol": "OTHER"}}]}}).encode(), {}, time.time_ns()))
    assert "instrument mismatch" in sources.collect("yahoo-dxy", {"assets": ["NQ"]})["error"]
    assert sources.records()["records"] == []
