#!/usr/bin/env python3
"""Enforce the ICARUS MCP same-changeset interface/provenance contract in CI."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
try:
    from tools.background_process import background_kwargs
except ModuleNotFoundError:
    from background_process import background_kwargs

EVENT_ROOT="automation_intelligence/mcp_interface/events/"
CRITICAL_PREFIXES=("icarus_engine/","icarus/")
EXEMPT_PARTS=("/tests","test_","/docs/","README")
REQUIRED={"event_id","at_utc","category","status","severity","summary","surface","source","paths","evidence","execution_authorized"}
CATEGORIES={"REPAIR","AUDIT","EVOLUTION","INTEGRATION"}

def sh(*args):
    return subprocess.check_output(args,text=True,**background_kwargs()).strip()

def base_ref():
    base=os.environ.get("GITHUB_BASE_REF","").strip()
    if base:
        return "origin/"+base
    try:
        sh("git","rev-parse","HEAD^")
        return "HEAD^"
    except subprocess.CalledProcessError:
        return None

def important(path:str)->bool:
    if not path.startswith(CRITICAL_PREFIXES): return False
    if path.startswith("tests") or "/test" in path: return False
    return True

def main():
    base=base_ref()
    if not base:
        print("MCP contract: no comparison base; skipped")
        return 0
    changed=[p for p in sh("git","diff","--name-only",base+"...HEAD").splitlines() if p]
    critical=[p for p in changed if important(p)]
    if not critical:
        print("MCP contract: no critical ICARUS code changes")
        return 0
    events=[p for p in changed if p.startswith(EVENT_ROOT) and p.endswith(".json") and Path(p).is_file()]
    if not events:
        print("::error::Critical ICARUS code changed without an MCP interface event in the same changeset")
        print("critical:",*critical,sep="\n  ")
        return 1
    covered=set(); errors=[]
    for p in events:
        try:
            d=json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception as ex:
            errors.append(f"{p}: invalid JSON: {ex}"); continue
        missing=sorted(REQUIRED-set(d))
        if missing: errors.append(f"{p}: missing fields {missing}")
        if d.get("category") not in CATEGORIES: errors.append(f"{p}: bad category {d.get('category')!r}")
        if d.get("execution_authorized") is not False: errors.append(f"{p}: execution_authorized must remain false")
        paths=d.get("paths")
        if not isinstance(paths,list) or not all(isinstance(x,str) for x in paths or []):
            errors.append(f"{p}: paths must be a list of strings")
        else:
            covered.update(paths)
    uncovered=[p for p in critical if p not in covered]
    if uncovered:
        errors.append("critical changed paths not covered by event paths: "+", ".join(uncovered))
    for e in errors: print("::error::"+e)
    if errors: return 1
    print(f"MCP contract OK: {len(critical)} critical path(s), {len(events)} event(s)")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
