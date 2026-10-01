from pathlib import Path
from icarus_engine.history_v2 import load_csv, stitch
from icarus_engine.assurance import compare_series, gate_attribution
from icarus_engine.research_lab import walk_forward_slices, parameter_neighborhood
from icarus_engine.checkpoint import save, load

def test_history_validation_dedup_and_gap(tmp_path):
    p=tmp_path/"x.csv"; p.write_text("ts,open,high,low,close,volume\n0,1,2,0.5,1.5,1\n60,1.5,2,1,1.8,2\n60,1.5,2,1,1.9,3\n300,1,0.5,2,1,1\n",encoding="utf-8")
    bars,r=load_csv(str(p),60)
    assert len(bars)==2 and r.duplicates==1 and r.rejected==1 and r.gaps==0

def test_stitch_prefers_later_source_on_overlap(tmp_path):
    a=tmp_path/"a.csv"; b=tmp_path/"b.csv"
    a.write_text("ts,open,high,low,close,volume\n60,1,2,1,1.5,1\n",encoding="utf-8")
    b.write_text("ts,open,high,low,close,volume\n60,1,3,1,2.5,2\n120,2.5,3,2,2.8,1\n",encoding="utf-8")
    bars,reports=stitch([str(a),str(b)],60)
    assert len(bars)==2 and bars[0].c==2.5 and len(reports)==2

def test_checkpoint_is_non_authoritative_and_atomic(tmp_path):
    p=tmp_path/"c"/"s.json"; save(str(p),symbol="NQ",last_bar_ts=123,state={"x":1},provenance={"sha":"a"})
    q=load(str(p)); assert q["state"]["x"]==1 and q["execution_authorized"] is False

def test_assurance_finds_first_divergence_and_gate_snapshot():
    d=compare_series([1,2,3],[1,2.1,3]); assert not d["equal"] and d["first_divergence"]==1
    assert gate_attribution({"entry_allowed":False,"junk":1})=={"entry_allowed":False,"in_session":None,"gate_long":None,"gate_short":None,"diverge_veto_l":None,"diverge_veto_s":None,"final_l":None,"final_s":None,"eff_thresh":None,"rate_regime":None,"shock_mult":None}

def test_research_helpers():
    assert len(walk_forward_slices(100,40,20,20))==2
    assert len(parameter_neighborhood({"a":10.0,"flag":True}))==3

def test_runtime_wires_quality_readiness_and_attribution():
    text = Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    assert "load_history_csv" in text and "write_history_manifest" in text
    assert '"warmup_quality"' in text and '"warmup_readiness"' in text
    assert '"decision_attribution"' in text and "gate_attribution(st)" in text

def test_dashboard_surfaces_history_quality():
    text = Path("icarus_engine/dashboard.html").read_text(encoding="utf-8")
    assert "History readiness" in text
    for field in ("warmup_readiness","bars_valid","duplicates","rejected","gaps"):
        assert field in text


def test_history_discovery_and_strict_stitch(tmp_path):
    from icarus_engine.history_v2 import discover_history_sources, stitch_strict
    h=tmp_path/"history"; h.mkdir()
    a=h/"NQ_20m_2019.csv"; b=h/"NQ_20m_2020.csv"
    a.write_text("ts,open,high,low,close,volume\n60,1,2,1,1.5,1\n120,1.5,2,1,1.8,2\n",encoding="utf-8")
    b.write_text("ts,open,high,low,close,volume\n120,1.5,2,1,1.8,9\n180,1.8,2.2,1.7,2,3\n",encoding="utf-8")
    d=discover_history_sources(str(tmp_path),"NQ",20)
    assert d["exact"]==[str(a),str(b)]
    bars,reports,meta=stitch_strict(d["exact"],1200)
    assert len(bars)==3 and len(reports)==2 and meta["overlaps"]==1

def test_strict_stitch_refuses_conflicting_overlap(tmp_path):
    import pytest
    from icarus_engine.history_v2 import stitch_strict
    a=tmp_path/"a.csv"; b=tmp_path/"b.csv"
    a.write_text("ts,open,high,low,close,volume\n60,1,2,1,1.5,1\n",encoding="utf-8")
    b.write_text("ts,open,high,low,close,volume\n60,1,3,1,2.5,1\n",encoding="utf-8")
    with pytest.raises(ValueError,match="conflicting OHLC"):
        stitch_strict([str(a),str(b)],1200)

def test_history_quality_gate_is_research_only():
    from icarus_engine.history_v2 import HistoryReport, assess_quality
    q=assess_quality(HistoryReport("x",rows_read=100,bars_valid=95,rejected=5),100)
    assert q["status"]=="DEGRADED" and q["execution_authorized"] is False


def test_history_discovery_never_mixes_rth_and_eth(tmp_path):
    from icarus_engine.history_v2 import discover_history_sources
    h=tmp_path/"history"; h.mkdir()
    generic=h/"NQ_20m_2019.csv"
    rth=h/"NQ_20m_rth_2020.csv"
    eth=h/"NQ_20m_eth_2020.csv"
    for p in (generic,rth,eth):
        p.write_text("ts,open,high,low,close,volume\n60,1,2,1,1.5,1\n",encoding="utf-8")
    dr=discover_history_sources(str(tmp_path),"NQ",20,"rth")
    de=discover_history_sources(str(tmp_path),"NQ",20,"eth")
    assert dr["exact"]==[str(rth)]
    assert de["exact"]==[str(eth)]
    assert str(eth) in dr["ignored_session_mismatch"]
    assert str(rth) in de["ignored_session_mismatch"]

def test_history_discovery_falls_back_to_generic_when_session_label_absent(tmp_path):
    from icarus_engine.history_v2 import discover_history_sources
    h=tmp_path/"history"; h.mkdir()
    generic=h/"NQ_20m_2019.csv"
    generic.write_text("ts,open,high,low,close,volume\n60,1,2,1,1.5,1\n",encoding="utf-8")
    d=discover_history_sources(str(tmp_path),"NQ",20,"rth")
    assert d["exact"]==[str(generic)]
    assert d["requested_session"]=="rth"
