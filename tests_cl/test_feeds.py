# CL (Claude, Anthropic) — 2026-10-03 — tests for cl_lab.feeds and cl_lab.store (fixture bytes, no network)
import io
import json
import os
import zipfile

import numpy as np
import pandas as pd
import pytest

from cl_lab import store
from cl_lab.feeds import databento as databento_feed, registry, sources
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


class _FakeDBNStore:
    def __init__(self, frame):
        self._frame = frame

    def to_df(self):
        return self._frame.copy()


class _FakeMetadata:
    def __init__(self, cost):
        self.cost = cost
        self.calls = []

    def get_cost(self, **kwargs):
        self.calls.append(kwargs)
        return self.cost


class _FakeTimeseries:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def get_range(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeDBNStore(self.frame)


class _FakeHistorical:
    def __init__(self, frame, cost=0.25):
        self.metadata = _FakeMetadata(cost)
        self.timeseries = _FakeTimeseries(frame)


def test_databento_continuous_symbol_and_5m_resample(monkeypatch):
    monkeypatch.setenv("DATABENTO_ROLL_RULE", "v")
    assert databento_feed.continuous_symbol("mnq") == "MNQ.v.0"
    monkeypatch.setenv("DATABENTO_ROLL_RULE", "n")
    assert databento_feed.continuous_symbol("ES") == "ES.n.0"
    monkeypatch.setenv("DATABENTO_ROLL_RULE", "bad")
    with pytest.raises(ValueError):
        databento_feed.continuous_symbol("NQ")

    idx = pd.date_range("2026-10-01T13:30:00Z", periods=10, freq="1min")
    one = pd.DataFrame({
        "open": np.arange(10, dtype=float) + 100,
        "high": np.arange(10, dtype=float) + 101,
        "low": np.arange(10, dtype=float) + 99,
        "close": np.arange(10, dtype=float) + 100.5,
        "volume": np.ones(10),
    }, index=idx)
    five = databento_feed.resample_5m(one)
    assert len(five) == 2
    assert five.iloc[0]["open"] == 100.0
    assert five.iloc[0]["high"] == 105.0
    assert five.iloc[0]["low"] == 99.0
    assert five.iloc[0]["close"] == 104.5
    assert five.iloc[0]["volume"] == 5.0


def test_databento_fetch_estimates_cost_before_request(monkeypatch):
    monkeypatch.setenv("DATABENTO_ROLL_RULE", "v")
    monkeypatch.setenv("CL_DATABENTO_HISTORICAL_LAG_MINUTES", "0")
    monkeypatch.setenv("CL_DATABENTO_START", "2026-10-01T13:30:00Z")
    monkeypatch.setenv("CL_DATABENTO_MAX_USD_PER_FEED", "0.50")
    idx = pd.date_range("2026-10-01T13:30:00Z", periods=10, freq="1min")
    raw = pd.DataFrame({
        "open": np.arange(10, dtype=float) + 100,
        "high": np.arange(10, dtype=float) + 101,
        "low": np.arange(10, dtype=float) + 99,
        "close": np.arange(10, dtype=float) + 100.5,
        "volume": np.ones(10),
    }, index=idx)
    client = _FakeHistorical(raw, cost=0.25)
    df, meta = databento_feed.fetch_continuous_5m(
        "NQ", pd.DataFrame(), pd.Timestamp("2026-10-01T13:40:00Z"), client=client
    )
    assert len(client.metadata.calls) == 1
    assert len(client.timeseries.calls) == 1
    assert client.metadata.calls[0]["symbols"] == "NQ.v.0"
    assert client.metadata.calls[0]["stype_in"] == "continuous"
    assert client.metadata.calls[0]["schema"] == "ohlcv-1m"
    assert meta["estimated_cost_usd"] == 0.25
    assert meta["request_performed"] is True
    assert len(df) == 2

    expensive = _FakeHistorical(raw, cost=0.75)
    with pytest.raises(FeedError, match="exceeds"):
        databento_feed.fetch_continuous_5m(
            "NQ", pd.DataFrame(), pd.Timestamp("2026-10-01T13:40:00Z"), client=expensive
        )
    assert len(expensive.metadata.calls) >= 1          # CL: cap fitting may probe smaller windows (free)
    assert len(expensive.timeseries.calls) == 0


def test_databento_registry_covers_registered_futures_universe():
    assert set(registry.DATABENTO_FUTURES_ROOTS) == {
        "NQ", "MNQ", "ES", "MES", "YM", "MYM", "RTY", "M2K",
        "GC", "MGC", "SI", "SIL", "PL", "PA", "BTC", "MBT",
    }


def test_databento_registry_adds_context_markets_without_promoting_core():
    context = {(root, dataset, role) for root, dataset, role in registry.DATABENTO_INTELLIGENCE_FUTURES}
    assert ("VX", "XCBF.PITCH", "volatility") in context
    assert ("VXM", "XCBF.PITCH", "volatility") in context
    assert ("DX", "IFUS.IMPACT", "dollar_index") in context
    assert ("ZN", "GLBX.MDP3", "rates") in context
    assert ("CL", "GLBX.MDP3", "energy") in context
    assert ("HG", "GLBX.MDP3", "industrial_metals") in context
    assert len(context) == 19
    assert not (set(registry.DATABENTO_FUTURES_ROOTS) & {r for r, _, _ in context})


def test_databento_historical_watermark_lag_clamps_terminal_range(monkeypatch):
    monkeypatch.setenv("DATABENTO_ROLL_RULE", "v")
    monkeypatch.setenv("CL_DATABENTO_START", "2026-10-01T00:00:00Z")
    monkeypatch.setenv("CL_DATABENTO_HISTORICAL_LAG_MINUTES", "500")
    monkeypatch.setenv("CL_DATABENTO_MAX_USD_PER_FEED", "1.00")
    idx = pd.date_range("2026-10-01T00:00:00Z", periods=10, freq="1min")
    raw = pd.DataFrame({
        "open": np.arange(10, dtype=float) + 100,
        "high": np.arange(10, dtype=float) + 101,
        "low": np.arange(10, dtype=float) + 99,
        "close": np.arange(10, dtype=float) + 100.5,
        "volume": np.ones(10),
    }, index=idx)
    client = _FakeHistorical(raw, cost=0.25)
    databento_feed.fetch_continuous_5m(
        "NQ", pd.DataFrame(), pd.Timestamp("2026-10-01T12:00:00Z"), client=client
    )
    assert len(client.metadata.calls) == 1
    assert client.metadata.calls[0]["end"] == "2026-10-01T03:40:00+00:00"
    assert client.timeseries.calls[0]["end"] == "2026-10-01T03:40:00+00:00"


def test_databento_accepts_cfe_and_ice_us_continuous_datasets(monkeypatch):
    monkeypatch.setenv("CL_DATABENTO_HISTORICAL_LAG_MINUTES", "0")
    monkeypatch.setenv("CL_DATABENTO_START", "2026-10-01T13:30:00Z")
    monkeypatch.setenv("CL_DATABENTO_MAX_USD_PER_FEED", "1.00")
    idx = pd.date_range("2026-10-01T13:30:00Z", periods=10, freq="1min")
    raw = pd.DataFrame({
        "open": np.arange(10, dtype=float) + 100,
        "high": np.arange(10, dtype=float) + 101,
        "low": np.arange(10, dtype=float) + 99,
        "close": np.arange(10, dtype=float) + 100.5,
        "volume": np.ones(10),
    }, index=idx)
    for root, dataset in (("VX", "XCBF.PITCH"), ("DX", "IFUS.IMPACT")):
        client = _FakeHistorical(raw, cost=0.25)
        _, meta = databento_feed.fetch_continuous_5m(
            root, pd.DataFrame(), pd.Timestamp("2026-10-01T13:40:00Z"),
            client=client, dataset=dataset
        )
        assert client.metadata.calls[0]["dataset"] == dataset
        assert client.metadata.calls[0]["symbols"] == f"{root}.v.0"
        assert meta["dataset"] == dataset


def test_databento_registry_is_dormant_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    monkeypatch.setenv("DATABENTO_ROLL_RULE", "v")
    man = registry.refresh_all(
        str(tmp_path / "cache"),
        only={"databento_nq_5m", "databento_mgc_5m"},
        now="2026-10-04T12:00Z",
    )
    for name in ("databento_nq_5m", "databento_mgc_5m"):
        ent = man["feeds"][name]
        assert ent["status"] == "unconfigured"
        assert ent["dataset"] == "GLBX.MDP3"
        assert ent["continuous_symbol"].endswith(".v.0")
        assert ent["integrity"]["rows"] == 0


# ---- CL 2026-10-04: fit to the per-asset cap instead of refusing; retry vendor gateway errors ----
class _RateMetadata:
    def __init__(self, usd_per_day):
        self.rate, self.calls = usd_per_day, []

    def get_cost(self, **kw):
        self.calls.append(kw)
        days = (pd.Timestamp(kw["end"]) - pd.Timestamp(kw["start"])) / pd.Timedelta(days=1)
        return self.rate * days


class _FlakyTimeseries(_FakeTimeseries):
    def __init__(self, frame, failures=1):
        super().__init__(frame)
        self.failures = failures

    def get_range(self, **kwargs):
        if self.failures:
            self.failures -= 1
            raise RuntimeError("BentoServerError: 504 The remote gateway timed out")
        return super().get_range(**kwargs)


def _rate_client(rate, flaky=0):
    idx = pd.date_range("2026-09-01T13:30:00Z", periods=10, freq="1min")
    raw = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0}, index=idx)
    c = _FakeHistorical(raw)
    c.metadata = _RateMetadata(rate)
    if flaky:
        c.timeseries = _FlakyTimeseries(raw, flaky)
    return c


def test_databento_first_pull_fits_cap_keeping_recent_data(monkeypatch):
    monkeypatch.setenv("CL_DATABENTO_HISTORICAL_LAG_MINUTES", "0")
    monkeypatch.setenv("CL_DATABENTO_START", "2024-09-01T00:00:00Z")
    monkeypatch.setenv("CL_DATABENTO_MAX_USD_PER_FEED", "3.50")
    c = _rate_client(0.129)                                   # ~VX: $98 for the full range
    _, meta = databento_feed.fetch_continuous_5m("VX", pd.DataFrame(), pd.Timestamp("2026-10-05T00:00:00Z"),
                                                 client=c, dataset="XCBF.PITCH")
    assert len(c.timeseries.calls) == 1 and meta["estimated_cost_usd"] <= 3.50
    got = c.timeseries.calls[0]
    assert got["end"] == "2026-10-05T00:00:00+00:00"
    span = (pd.Timestamp(got["end"]) - pd.Timestamp(got["start"])) / pd.Timedelta(days=1)
    assert 26 <= span <= 27.2 and meta["fitted_to_cap"]["full_range_estimate_usd"] > 90


def test_databento_incremental_catch_up_never_opens_a_hole(monkeypatch):
    monkeypatch.setenv("CL_DATABENTO_HISTORICAL_LAG_MINUTES", "0")
    monkeypatch.setenv("CL_DATABENTO_MAX_USD_PER_FEED", "3.50")
    old = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
                       index=pd.DatetimeIndex(["2026-08-01T00:00:00Z"], name="ts_open"))
    c = _rate_client(0.129)
    databento_feed.fetch_continuous_5m("VX", old, pd.Timestamp("2026-10-05T00:00:00Z"), client=c, dataset="XCBF.PITCH")
    got = c.timeseries.calls[0]
    assert got["start"] == "2026-08-01T00:00:00+00:00" and pd.Timestamp(got["end"]) < pd.Timestamp("2026-08-29T00:00:00Z")


def test_databento_retries_gateway_errors(monkeypatch):
    monkeypatch.setenv("CL_DATABENTO_HISTORICAL_LAG_MINUTES", "0")
    monkeypatch.setenv("CL_DATABENTO_START", "2026-10-01T00:00:00Z")
    monkeypatch.setenv("CL_DATABENTO_MAX_USD_PER_FEED", "3.50")
    monkeypatch.setattr(databento_feed.time, "sleep", lambda s: None)
    c = _rate_client(0.01, flaky=1)
    _, meta = databento_feed.fetch_continuous_5m("ZS", pd.DataFrame(), pd.Timestamp("2026-10-04T00:00:00Z"), client=c)
    assert meta["request_performed"] is True and len(c.timeseries.calls) == 1


def test_vxm_and_dx_use_key_2_for_15_months_and_vx_is_not_requested(monkeypatch):
    names = {f["name"]: f for f in registry.FEEDS if f["kind"] == "databento"}
    assert "databento_vx_5m" not in names
    for root in ("vxm", "dx"):
        f = names[f"databento_{root}_5m"]
        assert f["account"] == "secondary" and f["start"] == "2025-07-01T00:00:00Z" and f["max_usd"] == 20.0
    assert "account" not in names["databento_nq_5m"]                      # core stays on key #1
    monkeypatch.setenv("CL_DATABENTO_HISTORICAL_LAG_MINUTES", "0")
    monkeypatch.delenv("CL_DATABENTO_START", raising=False)
    monkeypatch.setenv("CL_DATABENTO_MAX_USD_PER_FEED", "3.50")
    c = _rate_client(0.04)                                               # ~VXM: $18 for 15 months > $3.50
    _, meta = databento_feed.fetch_continuous_5m("VXM", pd.DataFrame(), pd.Timestamp("2026-10-05T00:00:00Z"),
                                                 client=c, dataset="XCBF.PITCH", account="secondary",
                                                 start_default="2025-07-01T00:00:00Z", max_usd=20.0)
    assert c.timeseries.calls[0]["start"] == "2025-07-01T00:00:00+00:00" and meta["fitted_to_cap"] is None
    assert meta["account"] == "secondary" and meta["api_key_env"] == "DATABENTO_API_KEY_SECONDARY"


def test_secondary_lane_feeds_report_their_own_missing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABENTO_API_KEY", "x")
    monkeypatch.delenv("DATABENTO_API_KEY_SECONDARY", raising=False)
    man = registry.refresh_all(str(tmp_path), only={"databento_vxm_5m"}, now="2026-10-05T00:00Z")
    ent = man["feeds"]["databento_vxm_5m"]
    assert ent["status"] == "unconfigured" and "DATABENTO_API_KEY_SECONDARY" in ent["error"]
