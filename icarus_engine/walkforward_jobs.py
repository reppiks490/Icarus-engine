"""Rolling walk-forward descriptive jobs over the frozen ICARUS replay source."""
from __future__ import annotations
import threading,time,uuid,math
from typing import Any,Dict
from .backtest import freeze_replay_port, run_backtest

JOBS:Dict[str,Dict[str,Any]]={}
_LOCK=threading.Lock()

def _all(summary,key):
    v=summary.get(key) or {}; return v.get("all")

def _metrics(r):
    s=r["summary"]
    return {k:_all(s,k) for k in ("total_trades","net_profit","profit_factor","max_drawdown","max_drawdown_pct","expectancy","percent_profitable")}

def start(port,asset:str,folds:int=5,train_fraction:float=0.50):
    asset=str(asset).upper()
    if asset not in port.runners: raise ValueError("unknown asset")
    live=port.runners[asset]
    if not live.warm: raise ValueError("asset is still warming")
    gate=getattr(live,"warmup_quality_gate",None) or {}
    if gate.get("status")=="INVALID": raise ValueError("walk-forward refused: history quality is INVALID")
    folds=int(folds); train_fraction=float(train_fraction)
    if not 2<=folds<=10: raise ValueError("folds must be 2..10")
    if not 0.25<=train_fraction<=0.80: raise ValueError("train_fraction must be 0.25..0.80")
    frozen=freeze_replay_port(port,asset); src=frozen.runners[asset]
    rows=tuple(getattr(src,"raw_subbars",()) or src.subbars)
    if len(rows)<100: raise ValueError("insufficient cached bars for walk-forward")
    start_ts=min(b.ts for b,_ in rows); end_ts=max(b.ts+m*60 for b,m in rows)
    span=end_ts-start_ts
    train_span=int(span*train_fraction)
    remaining=span-train_span
    test_span=max(1,remaining//folds)
    windows=[]
    train_start=start_ts
    for i in range(folds):
        test_start=train_start+train_span+i*test_span
        test_end=end_ts if i==folds-1 else min(end_ts,test_start+test_span)
        if test_start>=test_end: break
        windows.append({"fold":i+1,"train_start":train_start,"train_end":test_start,
                        "test_start":test_start,"test_end":test_end})
    jid=uuid.uuid4().hex[:12]
    job={"id":jid,"asset":asset,"status":"running","started":time.time(),"progress":0,"total":len(windows)*2,
         "result":None,"error":None,"execution_authorized":False}
    with _LOCK: JOBS[jid]=job
    def work():
        try:
            out=[]; n=0
            for w in windows:
                train=run_backtest(frozen,asset,window_start=w["train_start"],window_end=w["train_end"])
                n+=1; job["progress"]=n
                test=run_backtest(frozen,asset,window_start=w["test_start"],window_end=w["test_end"])
                n+=1; job["progress"]=n
                out.append({**w,"train":_metrics(train),"test":_metrics(test),
                            "provenance":{"train":train["config"].get("reproducibility"),
                                          "test":test["config"].get("reproducibility")}})
            test_nets=[x["test"]["net_profit"] for x in out if isinstance(x["test"].get("net_profit"),(int,float))]
            test_pf=[x["test"]["profit_factor"] for x in out if isinstance(x["test"].get("profit_factor"),(int,float))]
            job["result"]={"asset":asset,"folds":out,
                           "stability":{"test_net_min":min(test_nets) if test_nets else None,
                                        "test_net_max":max(test_nets) if test_nets else None,
                                        "test_net_positive_folds":sum(x>0 for x in test_nets),
                                        "test_profit_factor_min":min(test_pf) if test_pf else None,
                                        "test_profit_factor_max":max(test_pf) if test_pf else None},
                           "interpretation":"DESCRIPTIVE_ROLLING_OUT_OF_SAMPLE",
                           "history_assurance":{"status":gate.get("status","UNKNOWN"),"reasons":gate.get("reasons",[])},
                           "execution_authorized":False,
                           "note":"Baseline configuration only. No parameter is selected, ranked or activated from these folds."}
            job["status"]="done"
        except Exception as ex:
            job["status"]="error"; job["error"]=f"{type(ex).__name__}: {ex}"
        job["finished"]=time.time()
    threading.Thread(target=work,daemon=True,name=f"walkforward-{jid}").start()
    return jid

def get(jid:str):
    with _LOCK:
        j=JOBS.get(str(jid))
        if not j: raise ValueError("unknown walk-forward job")
        return j
