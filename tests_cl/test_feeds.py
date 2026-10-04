# CL (Claude, Anthropic) — 2026-10-03 — tests for cl_lab.feeds and cl_lab.store (fixture bytes, no network)
import io
import json
import os
import zipfile

import numpy as np
import pandas as pd
import pytest

from cl_lab import store
from cl_lab.feeds import registry, sources
from cl_lab.feeds.http import FeedError


def test_fred_both_headers_and_missing_markers():
    a = sources.parse_fred(b"observation_date,DGS10\n2026-09-30,4.10\n2026-10-01,\n", "DGS10")
    b = sources.parse_fred(b"DATE,DGS10\n2026-09-30,4.10\n2026-10-01,.\n", "DGS10")
    for df in (a, b):
        assert list(df.index.strftime("%Y-%m-%d")) == ["2026-09-30", "2026-10-01"]
        assert df["DGS10"].iloc[0] == 4.10 and np.isnan(df["DGS10"].iloc[1])


def test_cboe_five_and_two_column_files():
    v = sources.parse_cboe(b"DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2026,15.1,16.0,14.9,15.5\n1/5/2026,15.5,17,15,16.2\n", "VIX")
    assert list(v.columns) == ["VIX_open", "VIX_high", "VIX_low", "VIX_close"] and v["VIX_close"].iloc[-1] == 16.2
    s = sources.parse_cboe(b"DATE,SKEW\n01/02/2026,140.5\n", "SKEW")
    assert list(s.columns) == ["SKEW_close"] and str(s.index[0].date()) == "2026-01-02"


def test_cftc_numeric_strings_and_missing_fields():
    recs = [{"report_date_as_yyyy_mm_dd": "2026-09-29T00:00:00.000", "cftc_contract_market_code": "209742",
             "market_and_exchange_names": "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE", "open_interest_all": "270554",
             "asset_mgr_positions_long": "100", "lev_money_positions_short": "55"},
            {"report_date_as_yyyy_mm_dd": "2026-09-22T00:00:00.000", "cftc_contract_market_code": "209742",
             "open_interest_all": "260000"}]
    df = sources.parse_cftc(json.dumps(recs).encode())
    assert df.index[0] < df.index[1] and df["open_interest_all"].iloc[1] == 270554.0
    assert np.isnan(df["asset_mgr_positions_long"].iloc[0])
    assert df.attrs["numeric_fields_found"] == ["asset_mgr_positions_long", "lev_money_positions_short"]


def test_coinbase_column_order_and_pagination(monkeypatch):
    raw = json.dumps([[1791086820, 84819.65, 84824.21, 84824.21, 84819.65, 0.09],
                      [1791086520, 84800.0, 84830.0, 84810.0, 84820.0, 1.5]]).encode()
    df = sources.parse_coinbase(raw)
    assert df.index.is_monotonic_increasing and df["open"].iloc[-1] == 84824.21 and df["low"].iloc[-1] == 84819.65
    calls = []
    monkeypatch.setattr(sources, "get_bytes", lambda url, params=None, **k: calls.append(params) or raw)
    end = pd.Timestamp("2026-10-04T00:00Z")
    sources.fetch_coinbase("BTC-USD", 300, start=end - pd.Timedelta(hours=60), end=end)
    assert len(calls) == 3  # 300 candles x 5 min = 25 h per page


def _zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("k.csv", "\n".join(",".join(map(str, r)) for r in rows))
    return buf.getvalue()


def test_binance_zip_ms_and_us_timestamps():
    r_ms = [1717372800000, 1, 2, 0.5, 1.5, 10, 1717373099999, 15, 3, 6, 9, 0]
    r_us = [1790812800000000, 1, 2, 0.5, 1.5, 10, 1790813099999999, 15, 3, 4, 6, 0]
    df = sources.parse_binance_zip(_zip([r_ms, r_us]))
    assert str(df.index[0]) == "2024-06-03 00:00:00+00:00" and str(df.index[1]) == "2026-10-01 00:00:00+00:00"
    assert list(df["taker_buy_volume"]) == [6.0, 4.0]


def test_merge_precedence_and_integrity_flags():
    idx = pd.to_datetime(["2026-01-01T00:00Z", "2026-01-01T00:05Z"]).rename("ts_open")
    old = pd.DataFrame({"open": [1.0, 2.0], "high": [1, 2], "low": [1, 2], "close": [1, 2], "volume": [1, 1]}, index=idx)
    new = old.iloc[1:].assign(close=2.0, open=1.9)
    m = store.merge_frames(old, new)
    assert len(m) == 2 and m["open"].iloc[1] == 1.9
    bad = old.copy()
    bad.loc[bad.index[0], ["low", "high"]] = [3.0, 2.0]
    bad.loc[bad.index[1], "open"] = 1.1
    rep = store.integrity(bad, tick_size=0.25)
    assert rep["ohlc_violations"] >= 1 and rep["off_tick"] >= 1


def test_refresh_all_isolates_failures_and_writes_only_cache(tmp_path, monkeypatch):
    daily = pd.DataFrame({"X": [1.0, 2.0]}, index=pd.DatetimeIndex(pd.to_datetime(["2026-09-30", "2026-10-01"]), name="date"))
    monkeypatch.setattr(sources, "fetch_fred", lambda s: daily.rename(columns={"X": s}))
    def boom(name):
        raise FeedError("HTTP 403 for test")
    monkeypatch.setattr(sources, "fetch_cboe", boom)
    cache = tmp_path / "cache"
    before = set(os.listdir(tmp_path))
    man = registry.refresh_all(str(cache), only={"fred_dgs10", "cboe_vix"}, now="2026-10-04T12:00Z")
    json.dumps(man)
    assert man["feeds"]["fred_dgs10"]["status"] == "ok" and man["feeds"]["cboe_vix"]["status"] == "error"
    assert set(os.listdir(tmp_path)) - before == {"cache"} and os.listdir(cache) == ["fred_dgs10.csv.gz"]
    back = store.load_frame(str(cache / "fred_dgs10.csv.gz"), intraday=False)
    assert list(back["DGS10"]) == [1.0, 2.0]


def test_binance_backfill_plan_skips_cached_months(monkeypatch):
    seen = []
    def fake(symbol, interval, period, market="spot"):
        seen.append(period)
        raise FeedError("HTTP 404")
    monkeypatch.setattr(sources, "fetch_binance_bulk", fake)
    old = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex(pd.to_datetime(["2024-09-30T23:55Z"]), name="ts_open"))
    _, used, notes = registry.refresh_binance(old, "BTCUSDT", "5m", pd.Timestamp("2024-11-03T12:00Z"))
    days_oct = [f"2024-10-{d:02d}" for d in range(1, 32)]
    assert seen == ["2024-10", *days_oct, "2024-11-01", "2024-11-02"] and used == 34 and len(notes) == 34
