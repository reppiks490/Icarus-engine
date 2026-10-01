from pathlib import Path
from icarus_engine.completion_gate import completion_status, source_classification

def _base(**kw):
    args=dict(
        warmup_loaded=6000,warmup_target=5000,
        warmup_gate={"status":"READY"},warmup_source="history/NQ_20m.csv",
        warmup_stitch={"source_kind":"exact","conflicts":0,"shards":2},
        temporal={"status":"PASS","violations":0},
        replay={"checkpoints":25,"divergences_this_run":0},
        recovery={"status":"MATCH","state_restore_enabled":False},
        provider={"status":"HEALTHY","primary":"yahoo","secondary":None,"failover_configured":False},
        continuous={"configured":True,"contract_files":["A.csv","B.csv"]},
        kind="futures",roll_mode="volume")
    args.update(kw)
    return completion_status(**args)

def test_completion_gate_ready_is_research_only():
    g=_base()
    assert g["status"]=="READY"
    assert g["hard_blocks"]==[] and g["warnings"]==[]
    assert g["source_quality"]["class"]=="EXACT_OPERATOR_HISTORY"
    assert g["execution_authorized"] is False
    assert g["trading_execution_authorized"] is False
    assert g["trading_permission"]=="UNCHANGED"

def test_completion_gate_blocks_temporal_and_replay_divergence():
    g=_base(temporal={"status":"VIOLATION","violations":1},
            replay={"checkpoints":10,"divergences_this_run":2})
    assert g["status"]=="BLOCKED"
    assert "TEMPORAL_LOOKAHEAD_EVIDENCE" in g["hard_blocks"]
    assert "REPLAY_DIVERGENCE" in g["hard_blocks"]

def test_completion_gate_warns_below_depth_and_proxy_history():
    g=_base(warmup_loaded=2500,
            warmup_source="data/mnq_20m.csv",
            warmup_stitch={"source_kind":"alias","conflicts":0,"shards":1},
            continuous={"configured":False,"contract_files":[]})
    assert g["status"]=="DEGRADED"
    assert "HISTORY_BELOW_TARGET" in g["warnings"]
    assert "COMPATIBLE_PRICE_PROXY_IN_USE" in g["warnings"]
    assert g["source_quality"]["class"]=="COMPATIBLE_PRICE_PROXY"
    assert g["source_quality"]["proxy_warning"] is True

def test_source_classification_network_and_unknown():
    assert source_classification("yahoo")["class"]=="NETWORK_PROVIDER"
    assert source_classification(None)["class"]=="UNKNOWN"

def test_runtime_and_interface_surface_completion_gate():
    rt=Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    ui=Path("icarus_engine/assurance-ui.js").read_text(encoding="utf-8")
    assert "completion_status(" in rt
    assert '"assurance_completion": completion_view' in rt
    assert "Assurance completion gate" in ui
    assert "READY does not authorize trading" in ui


def test_completion_gate_warns_degraded_history_quality():
    g=_base(warmup_gate={"status":"DEGRADED"})
    assert g["status"]=="DEGRADED"
    assert "HISTORY_QUALITY_DEGRADED" in g["warnings"]
