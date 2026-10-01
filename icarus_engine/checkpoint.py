"""Atomic, versioned research-state checkpoints. No live-order authority is persisted."""
from __future__ import annotations
import json, os, tempfile, time
SCHEMA="icarus-research-checkpoint-v1"
def save(path: str, *, symbol: str, last_bar_ts: int, state: dict, provenance: dict):
    payload={"schema_version":SCHEMA,"saved_at":int(time.time()),"symbol":symbol,"last_bar_ts":int(last_bar_ts),"state":state,"provenance":provenance,"execution_authorized":False}
    directory=os.path.dirname(os.path.realpath(path)) or "."
    os.makedirs(directory,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".checkpoint-",dir=directory,text=True)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(payload,f,sort_keys=True); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return payload
def load(path: str):
    try:
        with open(path,encoding="utf-8") as f: p=json.load(f)
        return p if p.get("schema_version")==SCHEMA and p.get("execution_authorized") is False else None
    except (OSError,ValueError,TypeError): return None
