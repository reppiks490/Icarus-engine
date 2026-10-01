import time
from types import SimpleNamespace
from pathlib import Path

from icarus_engine.assets import resolve
from icarus_engine.runtime import AssetRunner, Journal, RunnerConfig
from icarus_engine.strategy.inputs import Inputs
from icarus_engine.pine.timeframe import Bar
from icarus_engine import comparison_jobs


def test_raw_subbars_retain_out_of_session_bars_without_feeding_active_session():
    spec=resolve("NQ")
    spec.roll="none"
    spec.chart_tf="20"
    r=AssetRunner(RunnerConfig(spec=spec,inputs=Inputs()),Journal(":memory:"),{"yahoo":SimpleNamespace()})
    # 2026-09-14 12:00 UTC = 08:00 ET (outside RTH); 13:30 UTC = 09:30 ET.
    r.on_sub_bar(Bar(1789387200,100,101,99,100.5,10),1,False)
    assert len(r.raw_subbars)==1 and len(r.subbars)==0
    r.on_sub_bar(Bar(1789392600,101,102,100,101.5,10),1,False)
    assert len(r.raw_subbars)==2 and len(r.subbars)==1


def test_runtime_and_backtest_wire_raw_cross_session_cache():
    rt=Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    bt=Path("icarus_engine/backtest.py").read_text(encoding="utf-8")
    rs=Path("icarus_engine/research_service.py").read_text(encoding="utf-8")
    assert "self.raw_subbars" in rt and "replay_rows = list(self.raw_subbars or self.subbars)" in rt
    assert "raw_subbars=tuple(getattr(src, \"raw_subbars\"" in bt
    assert "subbars_scope" in bt
    assert '"raw_subbars"' in rs


def test_session_matrix_job_is_descriptive_and_execution_free(monkeypatch):
    runner=SimpleNamespace(warm=True,spec=SimpleNamespace(kind="futures",chart_type="real"),
                           cal=SimpleNamespace(session="rth"))
    port=SimpleNamespace(runners={"NQ":runner})
    monkeypatch.setattr(comparison_jobs,"freeze_replay_port",lambda p,s:p)
    def fake_run(_p,_s,session=None,chart_type=None,fill_on=None):
        n=1 if session=="rth" else 2
        return {"bars":100,"range":{"start":1,"end":2},
                "config":{"session":session,"chart_type":chart_type,"fill_on":fill_on,"tf":20,"pts_scale":1,
                          "historical_scale_asof_valid":True,
                          "reproducibility":{"subbars_scope":"raw_pre_session_filter","subbars_sha256":session+chart_type}},
                "summary":{"total_trades":{"all":n},"net_profit":{"all":10*n},"net_profit_pct":{"all":n},
                           "percent_profitable":{"all":50},"profit_factor":{"all":1.2},
                           "max_drawdown":{"all":5*n},"max_drawdown_pct":{"all":1},
                           "expectancy":{"all":2},"sharpe":{"all":1},"sortino":{"all":1.2},"cagr_pct":{"all":3}}}
    monkeypatch.setattr(comparison_jobs,"run_backtest",fake_run)
    job_id=comparison_jobs.start_matrix(port,"NQ")
    for _ in range(100):
        j=comparison_jobs.get_job(job_id)
        if j["status"]!="running": break
        time.sleep(.01)
    assert j["status"]=="done" and len(j["result"]["matrix"])==4
    assert j["result"]["interpretation"]=="DESCRIPTIVE_ONLY"
    assert j["result"]["execution_authorized"] is False


def test_server_and_dashboard_expose_session_matrix():
    s=Path("icarus_engine/server.py").read_text(encoding="utf-8")
    d=Path("icarus_engine/dashboard.html").read_text(encoding="utf-8")
    assert "/admin/research/session-matrix" in s
    assert "/api/research/session-matrix/" in s
    assert "Run RTH/ETH × Real/HA matrix" in d
    assert "No variant is selected or ranked automatically." in d


def test_determinism_locator_finds_first_trade_difference():
    a={"trades":[{"pnl":1},{"pnl":2}],"equity":[[1,100]],"drawdown":[],"buy_hold":[],"summary":{},"config":{}}
    b={"trades":[{"pnl":1},{"pnl":3}],"equity":[[1,100]],"drawdown":[],"buy_hold":[],"summary":{},"config":{}}
    d=comparison_jobs._first_replay_diff(a,b)
    assert d["surface"]=="trades" and d["index"]==1

def test_invalid_history_refuses_session_matrix():
    import pytest
    runner=SimpleNamespace(warm=True,warmup_quality_gate={"status":"INVALID","reasons":["NO_VALID_BARS"]},
                           spec=SimpleNamespace(kind="futures",chart_type="real"),cal=SimpleNamespace(session="rth"))
    port=SimpleNamespace(runners={"NQ":runner})
    with pytest.raises(ValueError,match="history quality is INVALID"):
        comparison_jobs.start_matrix(port,"NQ")
