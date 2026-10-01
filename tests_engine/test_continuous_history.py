import json, time
from pathlib import Path
from types import SimpleNamespace

from icarus_engine.continuous_history import archive_status, build_continuous, materialize
from icarus_engine import continuous_jobs


def _write_contract(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("ts,open,high,low,close,volume\n"+"\n".join(",".join(map(str,r)) for r in rows)+"\n",encoding="utf-8")


def _archive(tmp_path):
    root=tmp_path/"history"/"contracts"/"NQ"
    _write_contract(root/"NQH26.csv",[(60,100,102,99,101,10),(120,101,103,100,102,10)])
    _write_contract(root/"NQM26.csv",[(180,110,112,109,111,20),(240,111,113,110,112,20)])
    (root/"rolls.json").write_text(json.dumps({
        "schema_version":"icarus-continuous-roll-manifest-v1",
        "initial_contract":"NQH26",
        "rolls":[{"ts":180,"from":"NQH26","to":"NQM26","reason":"volume"}]
    }),encoding="utf-8")
    return root


def test_continuous_builder_preserves_raw_roll_and_back_adjusts_research_copy(tmp_path):
    _archive(tmp_path)
    raw,adj,meta=build_continuous(str(tmp_path),"NQ",1)
    assert [b.ts for b in raw]==[60,120,180,240]
    assert raw[1].c==102 and raw[2].o==110
    # gap is +8, so the old contract segment is shifted +8 in the back-adjusted research series.
    assert adj[1].c==110 and adj[2].o==110
    assert meta["roll_diagnostics"][0]["gap"]==8
    assert meta["adjustment"]=="DIFFERENCE_BACK_ADJUST_RESEARCH_ONLY"
    assert meta["execution_authorized"] is False


def test_continuous_materialization_is_separate_from_runtime_history(tmp_path):
    _archive(tmp_path)
    out=materialize(str(tmp_path),"NQ",1)
    assert (tmp_path/out["raw_path"]).is_file()
    assert (tmp_path/out["adjusted_path"]).is_file()
    assert "state/history/continuous" in out["raw_path"].replace("\\","/")
    assert out["execution_authorized"] is False
    s=archive_status(str(tmp_path),"NQ")
    assert s["configured"] and len(s["contract_files"])==2


def test_continuous_job_is_research_only(monkeypatch,tmp_path):
    _archive(tmp_path)
    runner=SimpleNamespace(spec=SimpleNamespace(kind="futures"),chart_minutes=1)
    port=SimpleNamespace(runners={"NQ":runner},base_dir=str(tmp_path))
    jid=continuous_jobs.start(port,"NQ")
    for _ in range(100):
        j=continuous_jobs.get(jid)
        if j["status"]!="running": break
        time.sleep(.01)
    assert j["status"]=="done"
    assert j["result"]["execution_authorized"] is False


def test_continuous_research_api_and_ui_are_wired():
    s=Path("icarus_engine/server.py").read_text(encoding="utf-8")
    ui=Path("icarus_engine/assurance-ui.js").read_text(encoding="utf-8")
    rt=Path("icarus_engine/runtime.py").read_text(encoding="utf-8")
    assert "/admin/research/continuous-history" in s
    assert "/api/research/continuous-history/" in s
    assert 'data-assurance-job="continuous-history"' in ui
    assert '"continuous_archive"' in rt
    assert "RESEARCH_ONLY" in Path("icarus_engine/continuous_history.py").read_text(encoding="utf-8")
