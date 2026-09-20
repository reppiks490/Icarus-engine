"""Does conditioning entry on PREDICTABLE volatility change the capture profile?

The unconditional trigger fires on essentially every window and returns a coin
flip, which is the expected result: it selects nothing. But big HTF moves were
just shown to develop progressively rather than arriving in one print, so the
geometry is there. The question is whether the windows worth entering can be
identified BEFORE they happen.

Realised volatility is the only feature that held its sign across both halves
of the cross-asset test, and volatility clustering is the most durable
regularity in this data. Everything below uses only bars that closed BEFORE the
window opened.
"""
import sys, statistics as st; sys.path.insert(0,'/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from tools.capture import atr_of, commitment_entry, concentration, directionality, group_by_htf

SPLIT = datetime(2025,10,1,tzinfo=timezone.utc)
bars = load_csv("data/mnq_5m_full.csv")
atr = atr_of(bars)
idx = {int(b.ts.timestamp()): i for i, b in enumerate(bars)}

def prior_rvol(open_ts, lookback=12):
    """Realised vol of the bars BEFORE this window opened. Strictly causal."""
    i = idx.get(open_ts)
    if i is None or i < lookback + 1:
        return None
    rets = []
    for k in range(i - lookback, i):
        prev = bars[k-1].close
        if prev > 0:
            rets.append((bars[k].close - prev) / prev)
    return st.pstdev(rets) if len(rets) > 3 else None

for htf in (60,):
    for span, seg in (("TUNE",[b for b in bars if b.ts<SPLIT]), ("HOLD",[b for b in bars if b.ts>=SPLIT])):
        wins = group_by_htf(seg, htf, 5)
        rows = []
        for w in wins:
            ts = int(w[0].ts.timestamp())
            i = idx.get(ts)
            if i is None or atr[i] <= 0: continue
            rv = prior_rvol(ts)
            if rv is None: continue
            rows.append((rv, w, atr[i]))
        if len(rows) < 200: continue
        rvs = sorted(r[0] for r in rows)
        q = [rvs[int(f*len(rvs))] for f in (0.25,0.50,0.75,0.90)]

        print(f"\n=== HTF {htf}m  {span}  ({len(rows)} windows) ===")
        print(f"  {'prior-vol band':>18s} {'n':>6s} {'dir':>6s} {'conc':>6s} "
              f"{'MFE':>7s} {'MAE':>7s} {'MFE/MAE':>8s} {'real':>7s} {'win%':>6s}")
        bands = [("bottom 25%", None, q[0]), ("25-50%", q[0], q[1]),
                 ("50-75%", q[1], q[2]), ("75-90%", q[2], q[3]), ("top 10%", q[3], None)]
        for name, lo, hi in bands:
            sel = [(w,a) for rv,w,a in rows
                   if (lo is None or rv >= lo) and (hi is None or rv < hi)]
            if len(sel) < 50: continue
            res = [(commitment_entry(w, 0.5*a), a) for w,a in sel]
            res = [(r,a) for r,a in res if r is not None]
            if len(res) < 50: continue
            mfe = [r.mfe/a for r,a in res]; mae = [abs(r.mae)/a for r,a in res]
            real= [r.realised/a for r,a in res]
            wr  = 100*sum(1 for r,_ in res if r.realised>0)/len(res)
            ratio = st.median(mfe)/st.median(mae) if st.median(mae)>0 else 0
            print(f"  {name:>18s} {len(res):6d} "
                  f"{st.median([directionality(w) for w,_ in sel]):6.2f} "
                  f"{st.median([concentration(w) for w,_ in sel]):6.2f} "
                  f"{st.median(mfe):+7.2f} {-st.median(mae):+7.2f} {ratio:8.2f} "
                  f"{st.fmean(real):+7.2f} {wr:6.1f}")
