"""Date-window replay and reporting, using the real aggregator and emulator."""
from types import SimpleNamespace
import threading

import pytest

from icarus_engine import backtest
from icarus_engine.assets import AssetSpec
from icarus_engine.pine.timeframe import Bar
from icarus_engine.runtime import AssetRunner, RunnerConfig
from icarus_engine.strategy.inputs import Inputs


@pytest.fixture
def replay(monkeypatch, tmp_path):
    runners = []

    class ScriptedRunner(AssetRunner):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.seen = []
            self.deep_seen = []
            runners.append(self)

        def _push_deep(self, chain, bar, minutes):
            self.deep_seen.append(bar.ts)
            super()._push_deep(chain, bar, minutes)

        def _on_chart_bar(self, bar, live):
            assert live is False
            self.seen.append(bar.ts)
            self.bar_index += 1
            self.em.process_bar(bar, self.bar_index)
            if bar.ts == 0:
                self.em.entry("old", 1, 1)
                self.em.entry("carry", 1, 1)
            elif bar.ts == 60:
                self.em.close("old")
            elif bar.ts == 120:
                self.em.entry("new", 1, 2)
            elif bar.ts == 180:
                # FIFO closes the pre-window carry before one new contract.
                self.em.exit("partial", "new", qty=2, limit=140)
            elif bar.ts == 240:
                self.em.close("new")
            elif bar.ts == 300:
                self.em.entry("future", 1, 1)

    monkeypatch.setattr(backtest, "AssetRunner", ScriptedRunner)
    monkeypatch.setattr(backtest, "resolve_inputs", lambda *args: (Inputs(), {}, []))
    spec = AssetSpec("TEST", "Test", "yahoo", "TEST", "crypto", 1, 1,
                     chart_tf="1", capital=100000, commission=1, roll="none")
    bars = [(Bar(i * 60, p, p, p, p, 1), 1) for i, p in enumerate(range(100, 180, 10))]
    src = SimpleNamespace(spec=spec, cfg=RunnerConfig(spec, Inputs()),
                          lock=threading.RLock(), deep={2: bars.copy()}, subbars=bars)
    port = SimpleNamespace(runners={"TEST": src}, preset_for=lambda src: None,
                           base_dir=str(tmp_path), profile="nq", feeds={})

    def run(chart_tf="1", **kwargs):
        spec.chart_tf = chart_tf
        result = backtest.run_backtest(port, "TEST", **kwargs)
        return result, runners[-1]

    return run


def test_end_stops_replay_and_keeps_future_exit_open(replay):
    result, runner = replay(window_start=180, window_end=300)
    assert runner.seen == [0, 60, 120, 180, 240]
    assert runner.deep_seen == runner.seen
    assert [(t["entry_signal"], t["qty"], t["open"], t["exit_ts"]) for t in result["trades"]] == [
        ("new", 1, False, 240), ("new", 1, True, None)]
    assert [t["pnl"] for t in result["trades"]] == [8, 9]
    assert result["summary"]["net_profit"]["all"] == 8
    assert result["summary"]["open_pnl"]["all"] == 9
    assert result["summary"]["commission_paid"]["all"] == 3
    assert result["equity"] == [[180, 99998], [240, 100017]]
    assert result["drawdown"] == [[180, -2], [240, 0]]
    assert result["buy_hold"] == [[180, 100000], [240, 107690]]
    assert result["summary"]["buy_and_hold_pnl"]["all"] == 7690
    assert result["bars"] == 2
    assert result["range"] == {"start": 180, "end": 300, "first_trade": 180, "last_trade": 240}
    assert "future" not in result["csv"] and "carry" not in result["csv"]


@pytest.mark.parametrize("end", [300, 329, 359])
def test_incomplete_final_bar_cannot_supply_prices_or_fills(replay, end):
    result, runner = replay(window_start=180, window_end=end)
    assert runner.seen[-1] == 240
    assert result["trades"][-1]["open"] is True
    assert result["equity"][-1] == [240, 100017]
    assert result["range"]["end"] == 300


def test_start_preserves_positions_but_excludes_their_pnl(replay):
    result, runner = replay(window_start=180, window_end=360)
    assert any(t.entry_id == "carry" for t in runner.em.closed)
    assert [t["entry_signal"] for t in result["trades"]] == ["new", "new"]
    assert result["summary"]["net_profit"]["all"] == 26
    assert result["equity"][-1] == [300, 100026]
    assert result["buy_hold"][-1] == [300, 115380]


def test_pre_start_open_position_is_not_reported(replay):
    result, runner = replay(window_start=180, window_end=240)
    assert [t.entry_id for t in runner.em.open] == ["carry", "new"]
    assert [t["entry_signal"] for t in result["trades"]] == ["new"]
    assert result["summary"]["open_pnl"]["all"] == -2
    assert result["equity"] == [[180, 99998]]


def test_end_inside_aggregated_chart_bar_does_not_flush_it(replay):
    result, runner = replay(chart_tf="2", window_end=180)
    assert runner.seen == [0]
    assert runner.deep_seen == [0, 60, 120]
    assert result["bars"] == 1
    assert result["range"]["end"] == 120
    assert result["trades"] == []


def test_start_only_uses_matching_closes_through_available_end(replay):
    result, _ = replay(window_start=180)
    assert result["bars"] == 5
    assert result["buy_hold"] == [[t, 100000 + i * 7690] for i, t in enumerate(range(180, 480, 60))]
    assert result["range"]["end"] == 480
    assert result["equity"][-1][1] == 100000 + sum(t["pnl"] for t in result["trades"])


@pytest.mark.parametrize("window", [{"window_end": 0}, {"window_start": 1000},
                                     {"window_start": 181, "window_end": 240}])
def test_empty_window_has_no_stale_marks_or_ranges(replay, window):
    result, _ = replay(**window)
    assert result["bars"] == 0
    assert result["trades"] == result["equity"] == result["drawdown"] == result["buy_hold"] == []
    assert result["range"] == dict(start=None, end=None, first_trade=None, last_trade=None)


def test_zero_start_and_unbounded_replay_agree(replay):
    unbounded, _ = replay()
    zero, _ = replay(window_start=0)
    for key in ("trades", "equity", "buy_hold", "summary", "range"):
        assert zero[key] == unbounded[key]
    assert unbounded["equity"][-1][1] == 100000 + sum(t["pnl"] for t in unbounded["trades"])


def test_reversed_window_is_rejected(replay):
    with pytest.raises(ValueError, match="window_start"):
        replay(window_start=1, window_end=0)
