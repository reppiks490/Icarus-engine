import sys, csv, statistics as st; sys.path.insert(0,'/home/user/Icarus-engine')
from icarus.ml import export_training_set
from icarus.config import profile_for, AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample, at_timeframe
SCR="/tmp/claude-0/-home-user-Icarus-engine/134e69c0-9376-5c62-9fa5-dfe829f5f315/scratchpad"
prof = at_timeframe(profile_for(AssetClass.MICRO_FUTURES), "2m")
for seed,name in ((11,"tune"),(41,"hold")):
    bars = resample(synthetic_for(AssetClass.MICRO_FUTURES,150000,seed=seed,minutes=2),"2m")
    export_training_set(bars, prof, f"{SCR}/fix_{name}.csv", upper_atr=2.0, lower_atr=1.0, horizon=30)

FEATS=("score","sweep_quality","c_order_flow","c_structure","c_volatility","c_location",
       "c_momentum","atr_pct","choppiness","target_room_atr","sweep_penetration_atr",
       "pool_weight","htf_position","sweep_reclaim_bars","kalman_dev_atr")
def load(name):
    rows=[]
    for r in csv.DictReader(open(f"{SCR}/fix_{name}.csv")):
        d=float(r["sweep_direction"]); s=float(r["score"])
        if d==0 or s<=0: continue
        lab=float(r["label"])          # ALREADY in the trade's frame now
        if lab==0: continue
        rows.append(dict(win=1.0 if lab>0 else 0.0, dir=d,
                         **{k:float(r[k]) for k in FEATS}))
    return rows
tune,hold=load("tune"),load("hold")
bt,bh=st.fmean([r['win'] for r in tune]),st.fmean([r['win'] for r in hold])
print(f"DIRECTION-AWARE LABELS.  tune n={len(tune)} base={bt:.4f} | hold n={len(hold)} base={bh:.4f}")
print(f"long share: tune {st.fmean([1 if r['dir']>0 else 0 for r in tune]):.3f} "
      f"hold {st.fmean([1 if r['dir']>0 else 0 for r in hold]):.3f}")
for nm,rows,b in (("tune",tune,bt),("hold",hold,bh)):
    L=[r['win'] for r in rows if r['dir']>0]; S=[r['win'] for r in rows if r['dir']<0]
    print(f"  {nm}: long win {st.fmean(L):.4f} (n={len(L)})   short win {st.fmean(S):.4f} (n={len(S)})")
def q(rows,key,base):
    s=sorted(rows,key=lambda r:r[key]); n=len(s)//5
    if n<30: return None
    return (st.fmean([r['win'] for r in s[:n]])-base, st.fmean([r['win'] for r in s[-n:]])-base)
print(f"\n{'feature':>24s} {'TUNE spread':>12s} {'HOLD spread':>12s} {'agrees':>8s}")
hits=[]
for f in FEATS:
    a=q(tune,f,bt); b=q(hold,f,bh)
    if not a or not b: continue
    sa,sb=a[1]-a[0], b[1]-b[0]
    ag = "YES" if (sa>0)==(sb>0) and min(abs(sa),abs(sb))>0.03 else "-"
    if ag=="YES": hits.append((f,sa,sb))
    print(f"{f:>24s} {sa:+12.4f} {sb:+12.4f} {ag:>8s}")
print("\n>>> SURVIVES BOTH TAPES (|spread|>0.03, same sign):")
for f,sa,sb in sorted(hits,key=lambda x:-min(abs(x[1]),abs(x[2]))):
    print(f"      {f:24s} tune {sa:+.4f}  hold {sb:+.4f}")
if not hits: print("      NONE -- no feature carries cross-validated signal")
