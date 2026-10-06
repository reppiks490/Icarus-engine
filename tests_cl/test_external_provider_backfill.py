import json

from cl_lab.data_fabric.backfill import run_backfill_cycle


def test_backfill_uses_only_accessible_rows_and_shared_budget(tmp_path):
    entitlement = {
        "providers": {
            "intrinio": {"status": "ok", "rows": [
                {"access": "ACCESSIBLE", "operation": "prices", "endpoint": "/securities/{identifier}/prices", "resolved_path": "/securities/AAPL/prices"},
                {"access": "RESTRICTED", "operation": "funds", "endpoint": "/funds"},
            ]},
            "unusual_whales": {"status": "ok", "rows": [
                {"access": "ACCESSIBLE", "name": "market_tide", "endpoint": "/api/market/market-tide", "resolved_path": "/api/market/market-tide"},
                {"access": "RESTRICTED", "name": "gex_levels", "endpoint": "/api/stock/{ticker}/gex-levels"},
            ]},
        }
    }
    calls = []
    def collector(**kw):
        calls.append((kw["provider"], kw["dataset"], kw["url"]))
        kw["budget"].consume()
        return {"calls": 1, "records": 2, "complete": True}

    out = run_backfill_cycle(
        providers=("intrinio", "unusual_whales"),
        env={"INTRINIO_API_KEY":"ik", "UNUSUAL_WHALES_API_TOKEN":"uw"},
        entitlement=entitlement,
        output_dir=tmp_path,
        max_calls=2,
        collector=collector,
        include_uw_full_tape=False,
        now="2026-10-06T20:00:00Z",
    )
    assert calls == [
        ("intrinio", "prices", "https://api-v2.intrinio.com/securities/AAPL/prices"),
        ("unusual_whales", "market_tide", "https://api.unusualwhales.com/api/market/market-tide"),
    ]
    assert out["budget"]["calls"] == 2
    assert "ik" not in json.dumps(out)
    assert "uw" not in json.dumps(out)
    assert (tmp_path / "manifests" / "backfill_latest.json").exists()


def test_backfill_isolates_dataset_failures_and_provider_unconfigured(tmp_path):
    entitlement = {"providers": {"intrinio": {"status":"ok", "rows":[
        {"access":"ACCESSIBLE", "operation":"bad", "endpoint":"/bad", "resolved_path":"/bad"},
    ]}}}
    def collector(**kw):
        raise RuntimeError("boom ik")
    out = run_backfill_cycle(
        providers=("intrinio","unusual_whales"),
        env={"INTRINIO_API_KEY":"ik"}, entitlement=entitlement, output_dir=tmp_path,
        max_calls=5, collector=collector, include_uw_full_tape=False,
        now="2026-10-06T20:00:00Z",
    )
    assert out["providers"]["intrinio"]["datasets"]["bad"]["status"] == "error"
    assert "ik" not in json.dumps(out)
    assert out["providers"]["unusual_whales"]["status"] == "unconfigured"


def test_full_tape_lane_is_explicit_and_uses_floor(tmp_path):
    entitlement = {"providers": {"unusual_whales": {"status":"ok", "rows":[]}}}
    seen = {}
    def binary_downloader(**kw):
        seen.update(kw)
        kw["budget"].consume()
        return {"calls":1,"dates":[kw["start_date"]],"complete":False}
    out = run_backfill_cycle(
        providers=("unusual_whales",), env={"UNUSUAL_WHALES_API_TOKEN":"uw"}, entitlement=entitlement,
        output_dir=tmp_path, max_calls=3, collector=lambda **kw: {}, binary_downloader=binary_downloader,
        include_uw_full_tape=True, historical_floor="2026-09-01", now="2026-10-06T20:00:00Z",
    )
    assert seen["start_date"] == "2026-09-01"
    assert seen["end_date"] == "2026-10-06"
    assert seen["url_template"].endswith("/api/option-trades/full-tape/{date}")
    assert out["providers"]["unusual_whales"]["datasets"]["option_full_tape"]["status"] == "ok"
