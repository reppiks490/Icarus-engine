"""Consolidated read-only assurance completion gate for ICARUS.

This gate reports evidence readiness only. It never grants trading permission,
changes strategy inputs, activates a model, or mutates order state.
"""
from __future__ import annotations
from typing import Any, Dict, List

def source_classification(source: str | None, stitch: Dict[str,Any] | None = None) -> Dict[str,Any]:
    src=str(source or "")
    st=stitch or {}
    kind=str(st.get("source_kind") or "").lower()
    if kind in ("exact","private_exact"):
        cls="EXACT_OPERATOR_HISTORY"
    elif kind=="alias" or "mnq_20m" in src.lower():
        cls="COMPATIBLE_PRICE_PROXY"
    elif src in ("yahoo","coinbase","kraken") or src.startswith(("yahoo:","coinbase:","kraken:")):
        cls="NETWORK_PROVIDER"
    elif src:
        cls="LOCAL_HISTORY"
    else:
        cls="UNKNOWN"
    return {"class":cls,"source":source,"proxy_warning":cls=="COMPATIBLE_PRICE_PROXY",
            "execution_authorized":False}

def completion_status(*, warmup_loaded:int, warmup_target:int, warmup_gate:Dict[str,Any] | None,
                      warmup_source:str | None, warmup_stitch:Dict[str,Any] | None,
                      temporal:Dict[str,Any] | None, replay:Dict[str,Any] | None,
                      recovery:Dict[str,Any] | None, provider:Dict[str,Any] | None,
                      continuous:Dict[str,Any] | None, kind:str, roll_mode:str) -> Dict[str,Any]:
    checks:List[Dict[str,Any]]=[]
    hard=[]; warnings=[]

    gate=warmup_gate or {}
    hist_status=str(gate.get("status") or "UNKNOWN")
    depth_ok=int(warmup_loaded)>=int(warmup_target)>0
    hist_ok=depth_ok and hist_status not in ("INVALID","BLOCKED")
    if hist_status in ("INVALID","BLOCKED"):
        hard.append("HISTORY_INVALID")
    elif hist_status=="DEGRADED":
        warnings.append("HISTORY_QUALITY_DEGRADED")
    elif hist_status=="UNKNOWN":
        warnings.append("HISTORY_QUALITY_UNKNOWN")
    if not depth_ok:
        warnings.append("HISTORY_BELOW_TARGET")
    checks.append({"name":"historical_depth","status":"PASS" if hist_ok else ("BLOCK" if hist_status in ("INVALID","BLOCKED") else "WARN"),
                   "loaded":int(warmup_loaded),"target":int(warmup_target),"quality":hist_status})

    t=temporal or {}
    violations=int(t.get("violations") or 0)
    if violations: hard.append("TEMPORAL_LOOKAHEAD_EVIDENCE")
    checks.append({"name":"temporal_integrity","status":"BLOCK" if violations else ("PASS" if t.get("status")=="PASS" else "PENDING"),
                   "violations":violations})

    rp=replay or {}
    div=int(rp.get("divergences_this_run") or 0)
    if div: hard.append("REPLAY_DIVERGENCE")
    elif not int(rp.get("checkpoints") or 0): warnings.append("REPLAY_BASELINE_NOT_ESTABLISHED")
    checks.append({"name":"replay_equivalence","status":"BLOCK" if div else ("PASS" if int(rp.get("checkpoints") or 0)>0 else "PENDING"),
                   "checkpoints":int(rp.get("checkpoints") or 0),"divergences":div})

    rec=recovery or {}
    rec_status=str(rec.get("status") or "NOT_INITIALIZED")
    if rec_status in ("DIVERGENCE","REFERENCE_BAR_MISSING"): hard.append("RESTART_RECOVERY_MISMATCH")
    elif rec_status not in ("MATCH",): warnings.append("RESTART_WITNESS_PENDING")
    checks.append({"name":"restart_recovery","status":"BLOCK" if rec_status in ("DIVERGENCE","REFERENCE_BAR_MISSING") else ("PASS" if rec_status=="MATCH" else "PENDING"),
                   "detail":rec_status,"state_restore_enabled":bool(rec.get("state_restore_enabled",False))})

    ph=provider or {}
    phs=str(ph.get("status") or "UNKNOWN")
    if phs=="DEGRADED": warnings.append("PRIMARY_PROVIDER_DEGRADED")
    elif phs=="UNKNOWN": warnings.append("PROVIDER_HEALTH_UNKNOWN")
    checks.append({"name":"provider_health","status":"WARN" if phs in ("DEGRADED","UNKNOWN") else "PASS",
                   "detail":phs,"primary":ph.get("primary"),"secondary":ph.get("secondary"),
                   "failover_configured":bool(ph.get("failover_configured"))})

    st=warmup_stitch or {}
    conflicts=int(st.get("conflicts") or 0)
    if conflicts: hard.append("HISTORY_OVERLAP_CONFLICT")
    checks.append({"name":"history_stitch","status":"BLOCK" if conflicts else "PASS",
                   "conflicts":conflicts,"sources":int(st.get("shards") or st.get("source_count") or 0)})

    cont=continuous or {}
    continuous_required=(str(kind)=="futures" and str(roll_mode)=="volume")
    configured=bool(cont.get("configured"))
    if continuous_required and not configured:
        warnings.append("CONTINUOUS_RESEARCH_ARCHIVE_NOT_CONFIGURED")
    checks.append({"name":"continuous_futures_research","status":"PASS" if configured else ("OPTIONAL" if not continuous_required else "WARN"),
                   "required_for_research":continuous_required,"configured":configured,
                   "contract_files":len(cont.get("contract_files") or [])})

    src=source_classification(warmup_source,warmup_stitch)
    if src["proxy_warning"]: warnings.append("COMPATIBLE_PRICE_PROXY_IN_USE")
    checks.append({"name":"history_source","status":"WARN" if src["proxy_warning"] else ("PASS" if src["class"]!="UNKNOWN" else "PENDING"),
                   **src})

    overall="BLOCKED" if hard else ("DEGRADED" if warnings else "READY")
    return {"status":overall,"hard_blocks":hard,"warnings":warnings,"checks":checks,
            "source_quality":src,
            "meaning":"RESEARCH_ASSURANCE_READINESS_ONLY",
            "trading_permission":"UNCHANGED",
            "execution_authorized":False,"trading_execution_authorized":False}
