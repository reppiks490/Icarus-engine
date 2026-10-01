import time
from pathlib import Path
from types import SimpleNamespace
from icarus_engine import walkforward_jobs
from icarus_engine.pine.timeframe import Bar

def _res(start,end):
    net=float((end-start)%1000)
    return {"summary":{
        "total_trades":{"all":5},"net_profit":{"all":net},"profit_factor":{"all":1.2},
        "max_drawdown":{"all":10.0},"max_drawdown_pct":{"all":1.0},"expectancy":{"all":net/5},
        "percent_profitable":{"all":60.0}},
        "config":{"reproducibility":{"subbars_sha256":"abc"}}}

def test_walkforward_runs_frozen_rolling_oos_without_selection(monkeypatch):
    rows=tuple((Bar(100+i*60,1,2,.5,1.5,1),1) for i in range(300))
    frozen=SimpleNamespace(runners={"NQ":SimpleNamespace(raw_subbars=rows,subbars=rows)})
    runner=SimpleNamespace(warm=True,warmup_quality_gate={"status":"READY","reasons":[]})
    port=SimpleNamespace(runners={"NQ":runner})
    monkeypatch.setattr(walkforward_jobs,"freeze_replay_port",lambda p,s:frozen)
    monkeypatch.setattr(walkforward_jobs,"run_backtest",
                        lambda p,s,window_start=None,window_end=None:_res(window_start,window_end))
    jid=walkforward_jobs.start(port,"NQ",folds=3,train_fraction=.5)
    for _ in range(100):
        j=walkforward_jobs.get(jid)
        if j["status"]!="running": break
        time.sleep(.01)
    assert j["status"]=="done"
    assert len(j["result"]["folds"])==3
    assert j["result"]["interpretation"]=="DESCRIPTIVE_ROLLING_OUT_OF_SAMPLE"
    assert "selected" not in j["result"] and "winner" not in j["result"]
    assert j["result"]["execution_authorized"] is False

def test_walkforward_refuses_invalid_history():
    runner=SimpleNamespace(warm=True,warmup_quality_gate={"status":"INVALID","reasons":["bad"]})
    port=SimpleNamespace(runners={"NQ":runner})
    import pytest
    with pytest.raises(ValueError,match="history quality is INVALID"):
        walkforward_jobs.start(port,"NQ")

def test_walkforward_api_and_ui_are_wired():
    s=Path("icarus_engine/server.py").read_text(encoding="utf-8")
    ui=Path("icarus_engine/assurance-ui.js").read_text(encoding="utf-8")
    assert "/admin/research/walkforward" in s
    assert "/api/research/walkforward/" in s
    assert 'data-assurance-job="walkforward"' in ui
    assert "Rolling walk-forward" in ui
