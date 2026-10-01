"""Async, read-only comparison jobs for session/chart research matrices."""
from __future__ import annotations
import threading, time, uuid
from typing import Any, Dict
from .backtest import freeze_replay_port, run_backtest

MATRIX_JOBS: Dict[str,Dict[str,Any]]={}
_LOCK=threading.Lock()
_MAX=12

def _all(summary,key):
    v=summary.get(key) or {}
    return v.get("all")

def _compact(result):
    s=result["summary"]
    keys=("total_trades","net_profit","net_profit_pct","percent_profitable","profit_factor",
          "max_drawdown","max_drawdown_pct","expectancy","sharpe","sortino","cagr_pct")
    return {"bars":result.get("bars"),"range":result.get("range"),
            "config":{k:result["config"].get(k) for k in ("session","chart_type","fill_on","tf","pts_scale","historical_scale_asof_valid")},
            "metrics":{k:_all(s,k) for k in keys},
            "source_scope":((result["config"].get("reproducibility") or {}).get("subbars_scope")),
            "dataset_digest":((result["config"].get("reproducibility") or {}).get("subbars_sha256"))}

def start_matrix(port,symbol:str) -> str:
    symbol=str(symbol).upper()
    if symbol not in port.runners: raise ValueError("unknown asset")
    src=port.runners[symbol]
    if not src.warm: raise ValueError("asset is still warming")
    if src.spec.kind!="futures": raise ValueError("session matrix currently applies to futures assets")
    frozen=freeze_replay_port(port,symbol)
    job_id=uuid.uuid4().hex[:12]
    job={"id":job_id,"asset":symbol,"status":"running","started":time.time(),"progress":0,
         "result":None,"error":None,"execution_authorized":False}
    with _LOCK:
        MATRIX_JOBS[job_id]=job
        if len(MATRIX_JOBS)>_MAX:
            for k in sorted(MATRIX_JOBS,key=lambda x:MATRIX_JOBS[x]["started"])[:len(MATRIX_JOBS)-_MAX]:
                MATRIX_JOBS.pop(k,None)
    def work():
        try:
            rows=[]; combos=[("rth","real"),("rth","heikin_ashi"),("eth","real"),("eth","heikin_ashi")]
            for i,(session,chart_type) in enumerate(combos,1):
                r=run_backtest(frozen,symbol,session=session,chart_type=chart_type,fill_on="real")
                rows.append({"session":session,"chart_type":chart_type,**_compact(r)})
                job["progress"]=i
            # No winner/ranking: surface deltas relative to the current asset configuration only.
            current_session=getattr(src.cal,"session",src.spec.session); current_chart=src.spec.chart_type
            baseline=next((x for x in rows if x["session"]==current_session and x["chart_type"]==current_chart),rows[0])
            base=baseline["metrics"]
            for x in rows:
                x["delta_vs_current"]={k:(x["metrics"][k]-base[k] if isinstance(x["metrics"].get(k),(int,float)) and isinstance(base.get(k),(int,float)) else None)
                                       for k in ("net_profit","max_drawdown","total_trades","expectancy")}
            job["result"]={"asset":symbol,"current":{"session":current_session,"chart_type":current_chart},
                           "matrix":rows,"interpretation":"DESCRIPTIVE_ONLY","execution_authorized":False,
                           "limitations":["Comparison uses retained raw cached bars when available.","Native deep HTF seed history may inherit the source runner's originally cached seed scope."]}
            job["status"]="done"
        except Exception as ex:
            job["error"]=f"{type(ex).__name__}: {ex}"; job["status"]="error"
        job["finished"]=time.time()
    threading.Thread(target=work,daemon=True,name=f"session-matrix-{job_id}").start()
    return job_id

def get_job(job_id:str):
    with _LOCK:
        j=MATRIX_JOBS.get(str(job_id))
        if not j: raise ValueError("unknown session matrix job")
        return j
