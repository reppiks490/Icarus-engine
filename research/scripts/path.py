"""Does the favourable excursion arrive BEFORE the adverse one?

MFE of +1.4 ATR sits inside these windows next to MAE of -1.6 ATR, so the
move is there and is being handed back. Whether that is recoverable depends
entirely on ORDER. If price typically runs favourably first, a target or trail
banks it and a stop is rarely reached. If it goes against you first, the same
stop removes you before the move you were right about.

Entry geometry cannot answer this. Only the path can.
"""
import sys, statistics as st; sys.path.insert(0,'/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from tools.capture import atr_of, group_by_htf

SPLIT = datetime(2025,10,1,tzinfo=timezone.utc)
bars = load_csv("data/mnq_5m_full.csv")
atr = atr_of(bars)
idx = {int(b.ts.timestamp()): i for i,b in enumerate(bars)}

def trade(sub, trig):
    """Causal entry, then walk the path recording which barrier is hit first."""
    if not sub: return None
    o = sub[0].open
    for k,b in enumerate(sub):
        up, dn = b.high >= o+trig, b.low <= o-trig
        if not (up or dn): continue
        body = sub[-1].close - o
        d = (-1 if body>0 else +1) if (up and dn) else (+1 if up else -1)
        entry = o + d*trig
        return d, entry, sub[k:]
    return None

for span, seg in (("TUNE",[b for b in bars if b.ts<SPLIT]), ("HOLD",[b for b in bars if b.ts>=SPLIT])):
    wins = group_by_htf(seg, 60, 5)
    print(f"\n=== HTF 60m {span} ===")
    print(f"  {'stop':>5s} {'target':>7s} {'n':>6s} {'tgt-first':>10s} {'stop-first':>11s} "
          f"{'neither':>8s} {'win%':>6s} {'expR':>8s}")
    for stop_a, tgt_a in ((0.5,0.5),(0.5,1.0),(0.5,1.5),(0.75,1.5),(1.0,1.0),(1.0,2.0)):
        tgt_first=stop_first=neither=0; rs=[]
        for w in wins:
            i = idx.get(int(w[0].ts.timestamp()))
            if i is None or atr[i]<=0: continue
            a = atr[i]
            t = trade(w, 0.5*a)
            if t is None: continue
            d, entry, rest = t
            stop_px = entry - d*stop_a*a
            tgt_px  = entry + d*tgt_a*a
            hit = None
            for b in rest:
                # Within one bar both may be touched; assume the STOP first.
                # Any other assumption invents a favourable ordering the data
                # cannot support, which is how backtests manufacture edge.
                s_hit = (b.low <= stop_px) if d>0 else (b.high >= stop_px)
                t_hit = (b.high >= tgt_px) if d>0 else (b.low <= tgt_px)
                if s_hit: hit='stop'; break
                if t_hit: hit='tgt'; break
            if hit=='tgt':   tgt_first+=1;  rs.append(tgt_a/stop_a)
            elif hit=='stop':stop_first+=1; rs.append(-1.0)
            else:
                neither+=1
                rs.append(d*(rest[-1].close-entry)/(stop_a*a))
        n = tgt_first+stop_first+neither
        if n < 200: continue
        wins_n = sum(1 for r in rs if r>0)
        print(f"  {stop_a:>5.2f} {tgt_a:>7.2f} {n:6d} {100*tgt_first/n:9.1f}% "
              f"{100*stop_first/n:10.1f}% {100*neither/n:7.1f}% "
              f"{100*wins_n/len(rs):5.1f}% {st.fmean(rs):+8.3f}")
