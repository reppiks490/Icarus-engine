"""Explicit, read-only replay regression baselines for ICARUS research."""
from __future__ import annotations
import json, os, tempfile, threading, time, uuid
from pathlib import Path
from typing import Any, Dict
from .backtest import freeze_replay_port, run_backtest
from .research_extensions import regression_digest

JOBS: Dict[str,Dict[str,Any]]={}
_LOCK=threading.Lock()
_MAX=12

_METRICS=("total_trades","net_profit","net_profit_pct","profit_factor","max_drawdown","max_drawdown_pct",
          "percent_profitable","expectancy","sharpe","sortino","cagr_pct")

def _all(summary,key):
    v=summary.get(key) or {}
    return v.get("all")

def _trade_sig(t):
    return [t.get(k) for k in ("type","entry_ts","entry_px","exit_ts","exit_px","exit_signal","qty","pnl")]

def snapshot(result):
    return {"schema_version":"icarus-regression-baseline-v1","asset":result.get("asset"),"digest":regression_digest(result),
            "bars":result.get("bars"),"range":result.get("range"),
            "config":{k:result.get("config",{}).get(k) for k in ("preset","fill_on","chart_type","session","tf","slippage_ticks","commission","pts_scale")},
            "metrics":{k:_all(result.get("summary",{}),k) for k in _METRICS},
            "trades":[_trade_sig(t) for t in result.get("trades",[]) if not t.get("open")],
            "execution_authorized":False}

def compare(base,current):
    b=set(json.dumps(x,separators=(",",":"),sort_keys=False,default=str) for x in base.get("trades",[]))
    c=set(json.dumps(x,separators=(",",":"),sort_keys=False,default=str) for x in current.get("trades",[]))
    deltas={}
    for k in _METRICS:
        x,y=base.get("metrics",{}).get(k),current.get("metrics",{}).get(k)
        deltas[k]=(y-x) if isinstance(x,(int,float)) and isinstance(y,(int,float)) else None
    return {"digest_equal":base.get("digest")==current.get("digest"),
            "baseline_digest":base.get("digest"),"current_digest":current.get("digest"),
            "bars_delta":(current.get("bars") or 0)-(base.get("bars") or 0),
            "metrics_delta":deltas,"trades_added":len(c-b),"trades_removed":len(b-c),
            "baseline_trade_count":len(b),"current_trade_count":len(c),
            "interpretation":"DESCRIPTIVE_REGRESSION_DIFF","execution_authorized":False}

def _path(root,asset):
    return Path(root)/"state"/"regression"/(asset.upper()+".json")

def load_baseline(root,asset):
    p=_path(root,asset)
    if not p.is_file(): return None
    try:
        d=json.loads(p.read_text(encoding="utf-8"))
        return d if d.get("schema_version")=="icarus-regression-baseline-v1" and d.get("execution_authorized") is False else None
    except (ValueError,OSError,TypeError): return None

def save_baseline(root,asset,data):
    p=_path(root,asset); p.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".baseline-",dir=str(p.parent),text=True)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(data,f,sort_keys=True); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return str(p)

def start(port,asset,mode):
    asset=str(asset).upper()
    if asset not in port.runners: raise ValueError("unknown asset")
    if mode not in ("baseline","check"): raise ValueError("mode must be baseline or check")
    if not port.runners[asset].warm: raise ValueError("asset is still warming")
    frozen=freeze_replay_port(port,asset)
    jid=uuid.uuid4().hex[:12]
    job={"id":jid,"asset":asset,"mode":mode,"status":"running","started":time.time(),"result":None,"error":None,"execution_authorized":False}
    with _LOCK:
        JOBS[jid]=job
        if len(JOBS)>_MAX:
            for k in sorted(JOBS,key=lambda x:JOBS[x]["started"])[:len(JOBS)-_MAX]: JOBS.pop(k,None)
    def work():
        try:
            res=run_backtest(frozen,asset,fill_on="real")
            cur=snapshot(res)
            if mode=="baseline":
                path=save_baseline(port.base_dir,asset,cur)
                job["result"]={"status":"BASELINE_SAVED","path":os.path.relpath(path,port.base_dir),"snapshot":cur,"execution_authorized":False}
            else:
                base=load_baseline(port.base_dir,asset)
                job["result"]=({"status":"NO_BASELINE","execution_authorized":False} if base is None
                               else {"status":"COMPARED","diff":compare(base,cur),"current":cur,"execution_authorized":False})
            job["status"]="done"
        except Exception as ex:
            job["status"]="error"; job["error"]=f"{type(ex).__name__}: {ex}"
        job["finished"]=time.time()
    threading.Thread(target=work,daemon=True,name=f"regression-{mode}-{jid}").start()
    return jid

def get(job_id):
    with _LOCK:
        j=JOBS.get(str(job_id))
        if not j: raise ValueError("unknown regression job")
        return j
