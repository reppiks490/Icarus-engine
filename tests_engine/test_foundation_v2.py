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
