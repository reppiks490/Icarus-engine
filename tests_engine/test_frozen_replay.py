"""Replays freeze the live source once, including scale and temporary inputs."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from icarus_engine import backtest
from icarus_engine.assets import AssetSpec
from icarus_engine.feeds import Coinbase
from icarus_engine.feeds.yahoo import Yahoo
from icarus_engine.pine.timeframe import Bar
from icarus_engine.runtime import AssetRunner, Journal, RunnerConfig
from icarus_engine.strategy.inputs import Inputs


@pytest.fixture
def source(tmp_path, monkeypatch):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("replay cannot access a live feed")
    monkeypatch.setattr(Yahoo, "daily_volume", forbidden)
    monkeypatch.setattr(Yahoo, "ticker", forbidden)
    monkeypatch.setattr(Yahoo, "candles", forbidden)
    monkeypatch.setattr(Coinbase, "mintick", forbidden)
    monkeypatch.setattr(Coinbase, "ticker", forbidden)
    monkeypatch.setattr(Coinbase, "candles", forbidden)
    spec = AssetSpec("TEST", "Test", "yahoo", "TEST", "crypto", .25, 1,
                     chart_tf="1", capital=100000, commission=1, roll="none")
    cfg = RunnerConfig(spec, Inputs(use_tide=False, use_eod_flat=False),
                       pts_ref_price=400, fixed_pts_scale=.25, sources=["original source"])
    r = AssetRunner(cfg, Journal(":memory:"))
    # An active non-persistent override can differ from the original cfg/file.
    r.inputs_base = replace(r.inputs_base, tp1_pts=37)
    r.paused = True
    for i in range(10):
        r.on_sub_bar(Bar(i * 60, 100 + i, 101 + i, 99 + i, 100 + i, 1), 1, live=False)
    r.deep = {2: [(Bar(-120, 100, 100, 100, 100, 1), 1)]}
    (tmp_path / "inputs.TEST.json").write_text('{"tp1_pts": 999}')
    (tmp_path / "presets").mkdir()
    port = SimpleNamespace(runners={"TEST": r}, preset_for=lambda _: None,
                           base_dir=str(tmp_path), profile="nq", feeds={"yahoo": r.feed})
    return port, r, calls


def test_replay_keeps_temporary_inputs_and_never_refetches_scale(source):
    port, r, calls = source
    result = backtest.run_backtest(port, "TEST")
    config = result["config"]
    evidence = config["reproducibility"]
    assert not calls
    assert config["pts_scale"] == .25
    assert evidence["effective_config"]["base_inputs"]["tp1_pts"] == 37
    assert evidence["effective_config"]["effective_inputs"]["tp1_pts"] == 37 * .25
    assert evidence["source_config"]["base_inputs"]["tp1_pts"] == 37
    assert config["historical_scale_asof_valid"] is False
    assert evidence["historical_scale_asof_valid"] is False
    assert "not recorded before" in evidence["scale_caveat"]
    assert evidence["subbars_count"] == len(r.subbars)
    for key in ("source_config_sha256", "effective_config_sha256", "subbars_sha256", "deep_sha256"):
        assert len(evidence[key]) == 64


def test_explicit_overrides_apply_on_top_of_frozen_base(source):
    port, _, calls = source
    result = backtest.run_backtest(port, "TEST", inputs={"tp1_pts": 80}, commission=3, fill_on="chart")
    effective = result["config"]["reproducibility"]["effective_config"]
    assert not calls
    assert effective["base_inputs"]["tp1_pts"] == 80
    assert effective["effective_inputs"]["tp1_pts"] == 20
    assert effective["spec"]["commission"] == 3 and effective["spec"]["fill_on"] == "chart"


def test_scaled_forward_window_requires_actual_prior_knowledge(source):
    port, runner, calls = source
    runner.cfg.scale_known_at = 240
    before = backtest.run_backtest(port, "TEST", window_start=180, window_end=600)["config"]
    after = backtest.run_backtest(port, "TEST", window_start=240, window_end=600)["config"]
    assert before["historical_scale_asof_valid"] is False
    assert after["historical_scale_asof_valid"] is True
    assert after["reproducibility"]["scale_known_at"] == 240
    assert after["reproducibility"]["scale_source"] == "frozen source scale"
    assert after["reproducibility"]["source_config"]["runner_config"]["scale_known_at"] == 240
    assert not calls


def test_scale_initialization_records_receipt_not_historical_bar_time(source, monkeypatch):
    _, runner, _ = source
    runner.cfg.fixed_pts_scale = None
    monkeypatch.setattr(runner, "_asset_ref_price", lambda price: 100)
    monkeypatch.setattr("icarus_engine.runtime.time.time", lambda: 1234.5)
    runner._init_strategy(100)
    assert runner.pts_scale == .25 and runner.cfg.scale_known_at == 1235
    runner.cfg.fixed_pts_scale = runner.pts_scale
    monkeypatch.setattr("icarus_engine.runtime.time.time", lambda: 9999)
    runner._init_strategy(900)
    assert runner.cfg.scale_known_at == 1235


def test_explicit_preset_is_resolved_with_explicit_overrides(source, tmp_path):
    port, _, calls = source
    (tmp_path / "presets" / "requested.json").write_text(json.dumps({
        "tp2_pts": 140, "_meta": {"capital": 23456, "chart_type": "heikin_ashi"}}))
    result = backtest.run_backtest(port, "TEST", preset="requested", inputs={"tp1_pts": 80})
    effective = result["config"]["reproducibility"]["effective_config"]
    assert effective["base_inputs"]["tp1_pts"] == 80 and effective["base_inputs"]["tp2_pts"] == 140
    assert effective["spec"]["capital"] == 23456 and effective["spec"]["chart_type"] == "heikin_ashi"
    assert not calls


def test_crypto_replay_uses_frozen_tick_without_product_metadata(source):
    port, r, calls = source
    r.spec.feed = "coinbase"
    r.mintick = .01
    result = backtest.run_backtest(port, "TEST")
    assert not calls
    assert result["config"]["reproducibility"]["effective_config"]["mintick"] == .01


def test_one_frozen_context_is_stable_across_live_and_file_changes(source, tmp_path):
    port, r, calls = source
    frozen = backtest.freeze_replay_port(port, "TEST")
    first = backtest.run_backtest(frozen, "TEST", inputs={"tp1_pts": 80})
    with r.lock:
        r.spec.capital = 42
        r.cfg.warmup_bars = 9
        r.inputs_base.tp2_pts = 999
        r.pts_scale = .75
        r.deep[2].append((Bar(-60, 900, 900, 900, 900, 1), 1))
        r.subbars.append((Bar(600, 900, 900, 900, 900, 1), 1))
    (tmp_path / "inputs.TEST.json").write_text('{"tp1_pts": 111}')
    repeated = backtest.run_backtest(frozen, "TEST", inputs={"tp1_pts": 80})
    assert first == repeated
    assert not calls
    assert backtest.freeze_replay_port(frozen, "TEST") is frozen
    assert isinstance(frozen.runners["TEST"].subbars, tuple)


def test_configuration_and_bars_are_frozen_before_replay_construction(source, monkeypatch):
    port, r, calls = source
    original = backtest.AssetRunner
    def mutating_constructor(*args, **kwargs):
        with r.lock:
            r.spec.capital = 7
            r.inputs_base.tp1_pts = 999
            r.pts_scale = .8
            r.subbars.clear()
            r.deep.clear()
        return original(*args, **kwargs)
    monkeypatch.setattr(backtest, "AssetRunner", mutating_constructor)
    result = backtest.run_backtest(port, "TEST")
    evidence = result["config"]["reproducibility"]
    assert result["bars"] == 10
    assert result["config"]["capital"] == 100000 and result["config"]["pts_scale"] == .25
    assert evidence["source_config"]["base_inputs"]["tp1_pts"] == 37
    assert evidence["deep_counts"] == {"2": 1}
    assert not calls


def test_parameter_trials_share_data_and_source_hashes(source):
    port, _, _ = source
    frozen = backtest.freeze_replay_port(port, "TEST")
    a = backtest.run_backtest(frozen, "TEST", inputs={"tp1_pts": 80})["config"]["reproducibility"]
    b = backtest.run_backtest(frozen, "TEST", inputs={"tp1_pts": 90})["config"]["reproducibility"]
    assert a["source_config_sha256"] == b["source_config_sha256"]
    assert a["subbars_sha256"] == b["subbars_sha256"] and a["deep_sha256"] == b["deep_sha256"]
    assert a["effective_config_sha256"] != b["effective_config_sha256"]


def test_missing_requested_htf_cache_rejects_replay(source):
    port, _, calls = source
    with pytest.raises(ValueError, match="cached history unavailable.*720"):
        backtest.run_backtest(port, "TEST", inputs={"htf_tf_1": "720"})
    assert not calls


def test_unscaled_reference_has_no_historical_scaling_dependency(source):
    port, r, calls = source
    r.cfg.pts_ref_price = 0
    r.cfg.fixed_pts_scale = None
    r.pts_scale = 1
    result = backtest.run_backtest(port, "TEST")
    evidence = result["config"]["reproducibility"]
    assert result["config"]["historical_scale_asof_valid"] is True
    assert evidence["scale_caveat"] is None and evidence["scale_source"].startswith("literal points")
    assert not calls
