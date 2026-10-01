"""Async, read-only comparison jobs for session/chart research matrices."""
from __future__ import annotations
import threading, time, uuid
from typing import Any, Dict
from .backtest import freeze_replay_port, run_backtest
from .research_extensions import regression_digest, robustness_value

MATRIX_JOBS: Dict[str,Dict[str,Any]]={}
_LOCK=threading.Lock()
_MAX=12

def _history_assurance(src):
    gate=getattr(src,"warmup_quality_gate",None) or {}
    status=str(gate.get("status") or getattr(src,"warmup_readiness","UNKNOWN"))
    reasons=list(gate.get("reasons") or [])
    if status=="INVALID":
        raise ValueError("research replay refused: history quality is INVALID" + (": "+", ".join(reasons) if reasons else ""))
    return {"status":status,"reasons":reasons,"execution_authorized":False}

def _all(summary,key):
    v=summary.get(key) or {}
    return v.get("all")

def _first_replay_diff(a,b):
    """Locate the first stable replay surface that differs; descriptive only."""
    surfaces=("trades","equity","drawdown","buy_hold")
    for name in surfaces:
        x=list(a.get(name) or []); y=list(b.get(name) or [])
        n=min(len(x),len(y))
        for i in range(n):
            if x[i] != y[i]:
                return {"surface":name,"index":i,"first":x[i],"second":y[i]}
        if len(x)!=len(y):
            return {"surface":name,"index":n,"first":(x[n] if n<len(x) else None),"second":(y[n] if n<len(y) else None),
                    "lengths":[len(x),len(y)]}
    if a.get("summary") != b.get("summary"):
        return {"surface":"summary","index":None,"first":a.get("summary"),"second":b.get("summary")}
    if a.get("config") != b.get("config"):
        return {"surface":"config","index":None,"first":a.get("config"),"second":b.get("config")}
    return None

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
    history_assurance=_history_assurance(src)
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
                           "matrix":rows,"history_assurance":history_assurance,"interpretation":"DESCRIPTIVE_ONLY","execution_authorized":False,
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


_DEFAULT_ROBUSTNESS_FIELDS=("rate_min_mult","rate_max_mult","shock_z_thresh","pe_thresh","family_discount","pulse_conf_weight")

def _new_job(symbol,kind,total):
    job_id=uuid.uuid4().hex[:12]
    job={"id":job_id,"kind":kind,"asset":symbol,"status":"running","started":time.time(),"progress":0,
         "total":total,"result":None,"error":None,"execution_authorized":False}
    with _LOCK:
        MATRIX_JOBS[job_id]=job
        if len(MATRIX_JOBS)>_MAX:
            for k in sorted(MATRIX_JOBS,key=lambda x:MATRIX_JOBS[x]["started"])[:len(MATRIX_JOBS)-_MAX]:
                MATRIX_JOBS.pop(k,None)
    return job_id,job

def start_determinism(port,symbol:str)->str:
    symbol=str(symbol).upper()
    if symbol not in port.runners: raise ValueError("unknown asset")
    src=port.runners[symbol]
    history_assurance=_history_assurance(src)
    if not src.warm: raise ValueError("asset is still warming")
    frozen=freeze_replay_port(port,symbol)
    job_id,job=_new_job(symbol,"determinism",2)
    def work():
        try:
            a=run_backtest(frozen,symbol); job["progress"]=1
            b=run_backtest(frozen,symbol); job["progress"]=2
            da,db=regression_digest(a),regression_digest(b)
            equal=da==db
            job["result"]={"asset":symbol,"equal":equal,"first_digest":da,"second_digest":db,
                           "bars":[a.get("bars"),b.get("bars")],
                           "trade_counts":[_all(a["summary"],"total_trades"),_all(b["summary"],"total_trades")],
                           "first_divergence":None if equal else _first_replay_diff(a,b),
                           "history_assurance":history_assurance,
                           "mode":"DETERMINISM_AUDIT","execution_authorized":False}
            job["status"]="done"
        except Exception as ex:
            job["error"]=f"{type(ex).__name__}: {ex}"; job["status"]="error"
        job["finished"]=time.time()
    threading.Thread(target=work,daemon=True,name=f"determinism-{job_id}").start()
    return job_id

def start_robustness(port,symbol:str,fields=None,fraction:float=0.10)->str:
    symbol=str(symbol).upper()
    if symbol not in port.runners: raise ValueError("unknown asset")
    src=port.runners[symbol]
    history_assurance=_history_assurance(src)
    if not src.warm: raise ValueError("asset is still warming")
    fraction=float(fraction)
    if not 0.0 < fraction <= 0.50: raise ValueError("fraction must be >0 and <=0.50")
    frozen=freeze_replay_port(port,symbol)
    base_inputs=src.inputs_base.to_dict()
    fields=tuple(fields or _DEFAULT_ROBUSTNESS_FIELDS)
    if len(fields)>12: raise ValueError("at most 12 robustness fields")
    bad=[f for f in fields if f not in base_inputs or isinstance(base_inputs[f],bool) or not isinstance(base_inputs[f],(int,float))]
    if bad: raise ValueError("unsupported robustness fields: "+", ".join(map(str,bad)))
    job_id,job=_new_job(symbol,"robustness",1+2*len(fields))
    def work():
        try:
            baseline=run_backtest(frozen,symbol); job["progress"]=1
            bm=_compact(baseline)["metrics"]; rows=[]
            step=1
            for field in fields:
                center=base_inputs[field]
                for direction,label in ((-1,"lower"),(1,"upper")):
                    value=robustness_value(center,fraction,direction)
                    result=run_backtest(frozen,symbol,inputs={field:value}); step+=1; job["progress"]=step
                    m=_compact(result)["metrics"]
                    rows.append({"field":field,"variant":label,"center":center,"value":value,"metrics":m,
                                 "delta_vs_current":{k:(m[k]-bm[k] if isinstance(m.get(k),(int,float)) and isinstance(bm.get(k),(int,float)) else None)
                                                     for k in ("net_profit","max_drawdown","total_trades","expectancy","profit_factor")}})
            grouped={}
            for row in rows: grouped.setdefault(row["field"],[]).append(row)
            sensitivity={}
            for field,rr in grouped.items():
                vals=[x["metrics"].get("net_profit") for x in rr if isinstance(x["metrics"].get("net_profit"),(int,float))]
                dds=[x["metrics"].get("max_drawdown") for x in rr if isinstance(x["metrics"].get("max_drawdown"),(int,float))]
                sensitivity[field]={"net_profit_span":(max(vals)-min(vals) if vals else None),
                                    "max_drawdown_span":(max(dds)-min(dds) if dds else None)}
            job["result"]={"asset":symbol,"fraction":fraction,"baseline":bm,"variants":rows,"sensitivity":sensitivity,
                           "history_assurance":history_assurance,
                           "interpretation":"DESCRIPTIVE_LOCAL_SENSITIVITY","execution_authorized":False,
                           "note":"One parameter is perturbed at a time; no variant is selected, ranked or activated."}
            job["status"]="done"
        except Exception as ex:
            job["error"]=f"{type(ex).__name__}: {ex}"; job["status"]="error"
        job["finished"]=time.time()
    threading.Thread(target=work,daemon=True,name=f"robustness-{job_id}").start()
    return job_id


def start_live_replay_parity(port,symbol:str)->str:
    """Replay one frozen live snapshot and compare its terminal decision fingerprint."""
    symbol=str(symbol).upper()
    if symbol not in port.runners: raise ValueError("unknown asset")
    src_live=port.runners[symbol]
    history_assurance=_history_assurance(src_live)
    if not src_live.warm: raise ValueError("asset is still warming")
    frozen=freeze_replay_port(port,symbol)
    src=frozen.runners[symbol]
    reference_ts=getattr(src,"frozen_terminal_bar_ts",None)
    reference_digest=getattr(src,"frozen_terminal_digest",None)
    job_id,job=_new_job(symbol,"live-replay-parity",1)
    def work():
        try:
            replay=run_backtest(frozen,symbol)
            job["progress"]=1
            a=replay.get("assurance") or {}
            replay_ts=a.get("terminal_bar_ts"); replay_digest=a.get("terminal_decision_digest")
            if reference_ts is None or reference_digest is None:
                status="NO_REFERENCE"
            elif replay_ts != reference_ts:
                status="BAR_MISMATCH"
            elif replay_digest == reference_digest:
                status="MATCH"
            else:
                status="STATE_DIVERGENCE"
            job["result"]={"asset":symbol,"status":status,
                           "reference":{"bar_ts":reference_ts,"digest":reference_digest},
                           "replay":{"bar_ts":replay_ts,"digest":replay_digest},
                           "history_assurance":history_assurance,
                           "mode":"LIVE_VS_REPLAY_PARITY_AUDIT","execution_authorized":False,
                           "note":"Comparison is against a frozen closed-bar snapshot; it never mutates the live runner."}
            job["status"]="done"
        except Exception as ex:
            job["error"]=f"{type(ex).__name__}: {ex}"; job["status"]="error"
        job["finished"]=time.time()
    threading.Thread(target=work,daemon=True,name=f"live-replay-parity-{job_id}").start()
    return job_id


def start_robustness_map(port,symbol:str,x_field:str="shock_z_thresh",y_field:str="pe_thresh",
                         fraction:float=0.10,steps:int=5)->str:
    """Two-parameter neighborhood map. Descriptive only; no optimum is selected."""
    symbol=str(symbol).upper()
    if symbol not in port.runners: raise ValueError("unknown asset")
    src=port.runners[symbol]
    history_assurance=_history_assurance(src)
    if not src.warm: raise ValueError("asset is still warming")
    fraction=float(fraction); steps=int(steps)
    if not 0.0 < fraction <= 0.50: raise ValueError("fraction must be >0 and <=0.50")
    if steps not in (3,5,7): raise ValueError("steps must be 3, 5 or 7")
    base_inputs=src.inputs_base.to_dict()
    for f in (x_field,y_field):
        if f not in base_inputs or isinstance(base_inputs[f],bool) or not isinstance(base_inputs[f],(int,float)):
            raise ValueError(f"unsupported robustness-map field: {f}")
    if x_field==y_field: raise ValueError("robustness-map fields must differ")
    frozen=freeze_replay_port(port,symbol)
    offsets=[-fraction + (2*fraction*i/(steps-1)) for i in range(steps)]
    job_id,job=_new_job(symbol,"robustness-map",steps*steps)
    def value(center,off):
        if isinstance(center,int):
            return max(0,int(round(center*(1.0+off))))
        return float(center)*(1.0+off)
    def work():
        try:
            cells=[]; n=0
            for yo in offsets:
                for xo in offsets:
                    xv=value(base_inputs[x_field],xo); yv=value(base_inputs[y_field],yo)
                    cell={"x_offset":xo,"y_offset":yo,"x_value":xv,"y_value":yv}
                    try:
                        r=run_backtest(frozen,symbol,inputs={x_field:xv,y_field:yv})
                        cell["metrics"]=_compact(r)["metrics"]; cell["error"]=None
                    except Exception as ex:
                        cell["metrics"]=None; cell["error"]=f"{type(ex).__name__}: {ex}"
                    cells.append(cell); n+=1; job["progress"]=n
            job["result"]={"asset":symbol,"x_field":x_field,"y_field":y_field,
                           "fraction":fraction,"steps":steps,"cells":cells,
                           "history_assurance":history_assurance,
                           "interpretation":"DESCRIPTIVE_PARAMETER_NEIGHBORHOOD",
                           "execution_authorized":False,
                           "note":"No optimum, winner, ranking or activation is produced; inspect the surface for stability and cliffs."}
            job["status"]="done"
        except Exception as ex:
            job["error"]=f"{type(ex).__name__}: {ex}"; job["status"]="error"
        job["finished"]=time.time()
    threading.Thread(target=work,daemon=True,name=f"robustness-map-{job_id}").start()
    return job_id
