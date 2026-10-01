"""Small deterministic assurance primitives used by replay/regression tooling."""
from __future__ import annotations
import math
def compare_series(reference, candidate, tol=1e-9):
    n=min(len(reference),len(candidate)); first=None; max_abs=0.0
    for i in range(n):
        try: d=abs(float(reference[i])-float(candidate[i]))
        except (TypeError,ValueError): d=0.0 if reference[i]==candidate[i] else math.inf
        max_abs=max(max_abs,d)
        if first is None and d>tol: first=i
    if first is None and len(reference)!=len(candidate): first=n
    return {"equal":first is None,"first_divergence":first,"max_abs_error":max_abs,"reference_len":len(reference),"candidate_len":len(candidate)}
def gate_attribution(state: dict):
    keys=("entry_allowed","in_session","gate_long","gate_short","diverge_veto_l","diverge_veto_s","final_l","final_s","eff_thresh","rate_regime","shock_mult")
    return {k:state.get(k) for k in keys}
