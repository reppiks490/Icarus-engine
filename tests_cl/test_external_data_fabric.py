# ChatGPT — 2026-10-04 — tests for external multi-provider data fabric
import pandas as pd

from cl_lab.feeds import external_data_fabric as ext


def test_eodhd_parallel_array_tick_summary():
    payload = {
        "mkt": ["Q", "D", "Q"],
        "price": [100.0, 100.25, 100.5],
        "seq": [1, 2, 3],
        "shares": [100, 50, 25],
        "sl": ["@   ", "@F I", "@F I"],
        "sub_mkt": ["", "Q", ""],
        "ts": [1000, 1001, 1002],
    }
    s = ext.summarize_eodhd_ticks(payload)
    assert s["ticks"] == 3
    assert s["shares"] == 175
    assert s["price_first"] == 100.0
    assert s["price_last"] == 100.5
    assert round(s["off_exchange_share_pct"], 6) == round(100 * 50 / 175, 6)
    assert round(s["odd_lot_share_pct"], 6) == round(100 * 75 / 175, 6)
    assert s["venues"]["Q"] == 2


def test_tiingo_eod_summary_prefers_adjusted_close():
    rows = [
        {"date": "2026-01-02T00:00:00Z", "close": 100.0, "adjClose": 50.0, "volume": 10},
        {"date": "2026-01-05T00:00:00Z", "close": 110.0, "adjClose": 55.0, "volume": 20},
    ]
    s = ext.summarize_tiingo_eod(rows)
    assert s["rows"] == 2
    assert round(s["total_return_pct"], 8) == 10.0


def test_tiingo_intraday_summary():
    rows = [
        {"date": "2026-10-01T13:30:00Z", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10},
        {"date": "2026-10-01T13:35:00Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 12},
    ]
    s = ext.summarize_tiingo_intraday(rows)
    assert s["bars"] == 2
    assert s["first"].startswith("2026-10-01T13:30")
    assert s["range_pct"] > 0


def test_cross_provider_summary_is_research_only():
    fmp = {
        "provider": "fmp",
        "status": "ok",
        "datasets": {"earnings_calendar": {"focus": [{"symbol": "AAPL", "date": "2026-10-20"}]}},
    }
    eodhd = {
        "provider": "eodhd",
        "status": "ok",
        "datasets": {"tick_windows": {"rows": [
            {"symbol": "QQQ", "ticks": 10, "shares": 1000, "off_exchange_share_pct": 40.0},
            {"symbol": "QQQ", "ticks": 12, "shares": 500, "off_exchange_share_pct": 20.0},
        ]}},
    }
    tiingo = {"provider": "tiingo", "status": "ok", "datasets": {}}
    s = ext.build_cross_provider_summary(fmp, eodhd, tiingo)
    assert s["provider_status"] == {"fmp": "ok", "eodhd": "ok", "tiingo": "ok"}
    assert s["equity_tick_pressure"]["QQQ"]["ticks"] == 22
    assert round(s["equity_tick_pressure"]["QQQ"]["off_exchange_share_pct"], 8) == round((40*1000+20*500)/1500, 8)
    assert s["upcoming_focus_earnings"][0]["symbol"] == "AAPL"
    assert s["execution_authorized"] is False


def test_run_with_no_credentials_is_dormant(tmp_path, monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    monkeypatch.delenv("TIINGO_API_TOKEN", raising=False)
    out = tmp_path / "out.json"
    res = ext.run(str(tmp_path / "cache"), str(out), now="2026-10-05T02:00:00Z")
    assert out.exists()
    assert res["providers"]["fmp"]["status"] == "unconfigured"
    assert res["providers"]["eodhd"]["status"] == "unconfigured"
    assert res["providers"]["tiingo"]["status"] == "unconfigured"
    assert res["execution_authorized"] is False
