from types import SimpleNamespace

import pytest

from icarus_engine import backtest
from icarus_engine.assets import AssetSpec
from icarus_engine.pine.timeframe import Bar
from icarus_engine.replay_readiness import assess_requested_timeframes
from icarus_engine.runtime import AssetRunner, Journal, RunnerConfig
from icarus_engine.strategy.inputs import Inputs


def bars(sub, start=0, count=10):
    return [(Bar(start+i*sub*60,100,101,99,100,1),sub) for i in range(count)]


def test_20m_source_cannot_claim_5m_or_15m_replay_coverage():
    raw=bars(20,count=100)
    r=assess_requested_timeframes(raw,{},[5,15,60,240,1440],chart_minutes=20)
    assert r["status"]=="BLOCKED"
    assert r["blocked_minutes"]==[5,15]
    by={x["minutes"]:x for x in r["timeframes"]}
    assert by[5]["reasons"]==["NO_COMPATIBLE_SUBBARS"]
    assert by[15]["reasons"]==["NO_COMPATIBLE_SUBBARS"]
    assert by[60]["status"]=="READY" and by[60]["raw_source_minutes"]==[20]
    assert r["execution_authorized"] is False


def test_1m_source_can_build_requested_timeframes_for_window():
    raw=bars(1,count=2000)
    r=assess_requested_timeframes(raw,{},[5,15,60,240,1440],chart_minutes=20,
                                  window_start=600,window_end=60000)
    assert r["status"]=="READY"
    assert r["blocked_minutes"]==[]


def test_partial_lower_timeframe_source_is_blocked_for_earlier_window():
    raw=bars(20,start=0,count=100)+bars(1,start=100000,count=1000)
    r=assess_requested_timeframes(raw,{},[15],chart_minutes=20,window_start=0,window_end=150000)
    assert r["status"]=="BLOCKED"
    row=r["timeframes"][0]
    assert "STARTS_AFTER_WINDOW" in row["reasons"]


def test_backtest_rejects_chain_object_without_compatible_history(tmp_path):
    spec=AssetSpec("TEST","Test","yahoo","TEST","crypto",.25,1,chart_tf="20",capital=100000,commission=1,roll="none")
    runner=AssetRunner(RunnerConfig(spec,Inputs(htf_tf_1="5",htf_tf_2="15",use_tide=False,use_eod_flat=False)),Journal(":memory:"))
    runner.raw_subbars=bars(20,count=100)
    runner.subbars=list(runner.raw_subbars)
    runner.warm=True
    port=SimpleNamespace(runners={"TEST":runner},base_dir=str(tmp_path),profile="nq",preset_for=lambda _:None)
    with pytest.raises(ValueError,match=r"cached history unavailable.*5.*15"):
        backtest.run_backtest(port,"TEST")
