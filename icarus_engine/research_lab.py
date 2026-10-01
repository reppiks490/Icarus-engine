"""Walk-forward and counterfactual bookkeeping helpers; deliberately execution-free."""
from __future__ import annotations
def walk_forward_slices(n, train, validate, test, step=None):
    step=step or test; out=[]; start=0
    while start+train+validate+test<=n:
        a=start; b=a+train; c=b+validate; d=c+test
        out.append({"train":(a,b),"validate":(b,c),"test":(c,d)}); start+=step
    return out
def parameter_neighborhood(center: dict, fractional_step=0.1):
    pts=[dict(center)]
    for k,v in center.items():
        if isinstance(v,(int,float)) and not isinstance(v,bool):
            for s in (-1,1):
                q=dict(center); q[k]=v*(1+s*fractional_step); pts.append(q)
    return pts
def counterfactual_record(*, ts, symbol, decision, reason, hypothetical):
    return {"ts":int(ts),"symbol":symbol,"decision":decision,"reason":reason,"hypothetical":hypothetical,"execution_authorized":False}
