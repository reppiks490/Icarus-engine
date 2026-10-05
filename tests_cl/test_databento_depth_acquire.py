# ChatGPT — 2026-10-04 — tests for cost-gated Databento depth acquisition
import os

import pandas as pd

from cl_lab import store
from cl_lab.feeds import databento_depth_acquire as depth


def _bars(days=12):
    idx = pd.date_range("2026-09-01T00:00:00Z", periods=days * 24 * 12, freq="5min")
    day_num = ((idx - idx[0]).days).astype(float)
    base = 100.0 + day_num * 0.1
    minute = idx.hour * 60 + idx.minute
    wave = (minute / 1440.0)
    frame = pd.DataFrame({
        "open": base + wave,
        "high": base + wave + 0.5 + day_num * 0.01,
        "low": base + wave - 0.4 - day_num * 0.005,
        "close": base + wave + 0.1,
        "volume": 10.0 + day_num,
    }, index=idx)
    frame.index.name = "ts_open"
    return frame


def test_informative_days_uses_cached_regimes_and_is_unique(tmp_path, monkeypatch):
    monkeypatch.setenv("CL_DATABENTO_HISTORICAL_LAG_MINUTES", "0")
    cache = tmp_path / "cache"
    cache.mkdir()
    store.save_frame(_bars(), str(cache / "databento_nq_5m.csv.gz"))
    picks = depth.informative_days(
        str(cache), "NQ", 8, now="2026-10-01T12:00:00Z"
    )
    assert len(picks) == 8
    assert len({d for d, _ in picks}) == 8
    roles = {r for _, r in picks}
    assert "high_range_1" in roles
    assert "median" in roles
    assert "quiet" in roles


def test_informative_days_fallback_stays_behind_watermark(tmp_path, monkeypatch):
    monkeypatch.setenv("CL_DATABENTO_HISTORICAL_LAG_MINUTES", "500")
    picks = depth.informative_days(
        str(tmp_path), "GC", 3, now="2026-10-05T01:00:00Z"
    )
    # 01:00Z minus 8h20m => safe day boundary is Oct 4 00:00Z;
    # fallback begins the prior complete day and skips weekends.
    assert all(pd.Timestamp(d).tz_localize("UTC") < pd.Timestamp("2026-10-04T00:00:00Z") for d, _ in picks)
    assert len(picks) == 3


def test_allocator_gets_breadth_before_density_and_never_exceeds_budget():
    priced = [
        dict(root="NQ", schema="mbo", day="2026-09-01", status="ok",
             priority=1.0, value_score=1.3, value_per_usd=13.0, estimated_cost_usd=0.10),
        dict(root="NQ", schema="mbo", day="2026-09-02", status="ok",
             priority=1.0, value_score=1.2, value_per_usd=12.0, estimated_cost_usd=0.10),
        dict(root="ES", schema="mbo", day="2026-09-01", status="ok",
             priority=0.9, value_score=0.9, value_per_usd=1.8, estimated_cost_usd=0.50),
        dict(root="GC", schema="mbo", day="2026-09-01", status="ok",
             priority=0.8, value_score=0.8, value_per_usd=1.6, estimated_cost_usd=0.50),
    ]
    selected = depth.allocate(priced, 1.10)
    assert {r["root"] for r in selected} == {"NQ", "ES", "GC"}
    assert sum(float(r["estimated_cost_usd"]) for r in selected) <= 1.10 + 1e-12


class _Level:
    def __init__(self, bid, ask, bsz, asz):
        self.bid_px = int(bid * 1_000_000_000)
        self.ask_px = int(ask * 1_000_000_000)
        self.bid_sz = bsz
        self.ask_sz = asz


class _Rec:
    def __init__(self, ts, action, side, price, size, levels=None):
        self.ts_recv = ts
        self.ts_event = ts - 100
        self.action = action
        self.side = side
        self.price = int(price * 1_000_000_000)
        self.size = size
        if levels is not None:
            self.levels = levels


def test_streaming_feature_reduction_handles_mbo_and_mbp10():
    t0 = int(pd.Timestamp("2026-09-01T14:30:00Z").value)
    records = [
        _Rec(t0 + 1_000, "A", "B", 100.0, 4),
        _Rec(t0 + 2_000, "C", "A", 100.25, 2),
        _Rec(t0 + 3_000, "T", "A", 100.25, 1),
        _Rec(
            t0 + 4_000, "M", "B", 100.0, 3,
            levels=[_Level(100.0, 100.25, 10, 8), _Level(99.75, 100.50, 7, 6)],
        ),
    ]
    frame = depth.summarize_store(records)
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["events"] == 4
    assert row["add_events"] == 1
    assert row["cancel_events"] == 1
    assert row["trade_events"] == 1
    assert row["modify_events"] == 1
    assert row["spread_mean"] == 0.25
    assert row["depth10_bid_mean"] == 17
    assert row["depth10_ask_mean"] == 14
    assert row["latency_mean_ns"] == 100


def test_profiles_keep_credentials_and_market_lanes_isolated():
    assert depth.PROFILES["index"]["account"] == "secondary"
    assert depth.PROFILES["diversifier"]["account"] == "third"
    index_roots = {x[0] for x in depth.PROFILES["index"]["instruments"]}
    div_roots = {x[0] for x in depth.PROFILES["diversifier"]["instruments"]}
    assert {"NQ", "MNQ", "ES", "MES"} <= index_roots
    assert {"GC", "MGC", "VX", "VXM", "ZN", "DX"} <= div_roots
    assert not (index_roots & div_roots)
