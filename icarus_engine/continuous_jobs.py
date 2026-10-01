"""Async research materialization jobs for explicit continuous futures archives."""
from __future__ import annotations
import threading,time,uuid
from typing import Any,Dict
from .continuous_history import archive_status, materialize

JOBS:Dict[str,Dict[str,Any]]={}
_LOCK=threading.Lock()

def start(port,asset:str,tf_minutes=None):
    asset=str(asset).upper()
    if asset not in port.runners: raise ValueError("unknown asset")
    r=port.runners[asset]
    if r.spec.kind!="futures": raise ValueError("continuous archive applies to futures assets")
    tf=int(tf_minutes or r.chart_minutes)
    status=archive_status(port.base_dir,asset)
    if not status["configured"]:
        raise ValueError(f"continuous archive is not configured under {status['root']}")
    jid=uuid.uuid4().hex[:12]
    job={"id":jid,"asset":asset,"tf_minutes":tf,"status":"running","started":time.time(),
         "result":None,"error":None,"execution_authorized":False}
    with _LOCK: JOBS[jid]=job
    def work():
        try:
            job["result"]=materialize(port.base_dir,asset,tf)
            job["status"]="done"
        except Exception as ex:
            job["status"]="error"; job["error"]=f"{type(ex).__name__}: {ex}"
        job["finished"]=time.time()
    threading.Thread(target=work,daemon=True,name=f"continuous-history-{jid}").start()
    return jid

def get(job_id:str):
    with _LOCK:
        j=JOBS.get(str(job_id))
        if not j: raise ValueError("unknown continuous-history job")
        return j
