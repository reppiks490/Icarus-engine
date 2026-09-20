"""Enter on the RETRACEMENT after commitment, not on the commitment itself.

Entering on commitment buys the local extreme of the move that just printed,
then puts a tight stop under it. Measured: the stop is hit first 95% of the
time at 0.5 ATR. That is not the market refusing to trend, it is the entry
paying the worst available price.

A pullback entry keeps the directional read -- which came from the commitment
leg, and is still causal -- but takes the price the retracement offers, and
places the stop BEHIND the leg's origin rather than a fixed distance under a
spike. Same information, better geometry.
"""
import sys, statistics as st; sys.path.insert(0,'/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from tools.capture import atr_of, group_by_htf

SPLIT = datetime(2025,10,1,tzinfo=timezone.utc)
bars = load_csv("data/mnq_5m_full.csv")
atr = atr_of(bars); idx = {int(b.ts.timestamp()): i for i,b in enumerate(bars)}

def pullback_trade(sub, trig, retrace, stop_pad, tgt_r):
    """Commit -> wait for a retrace of `retrace` of the leg -> enter -> manage."""
    if len(sub) < 3: return None
    o = sub[0].open
    # 1. commitment leg establishes direction, causally
    k = None
    for i,b in enumerate(sub):
        up, dn = b.high >= o+trig, b.low <= o-trig
        if up or dn:
            if up and dn:
                body = sub[-1].close - o
                d = -1 if body > 0 else +1
            else:
                d = +1 if up else -1
            k = i; break
    if k is None: return None
    extreme = max(b.high for b in sub[:k+1]) if d>0 else min(b.low for b in sub[:k+1])
    leg = abs(extreme - o)
    if leg <= 0: return None

    # 2. wait for the retracement to offer a price
    entry_px = extreme - d*retrace*leg
    entry_i = None
    for i in range(k+1, len(sub)):
        b = sub[i]
        if (b.low <= entry_px) if d>0 else (b.high >= entry_px):
            entry_i = i; break
    if entry_i is None: return None

    # 3. stop sits behind the leg's ORIGIN, not a fixed pad under a spike
    stop_px = o - d*stop_pad*leg
    risk = abs(entry_px - stop_px)
    if risk <= 0: return None
    tgt_px = entry_px + d*tgt_r*risk

    for b in sub[entry_i:]:
        s_hit = (b.low <= stop_px) if d>0 else (b.high >= stop_px)
        t_hit = (b.high >= tgt_px) if d>0 else (b.low <= tgt_px)
        if s_hit: return -1.0            # stop assumed first when both touch
        if t_hit: return tgt_r
    return d*(sub[-1].close - entry_px)/risk

for span, seg in (("TUNE",[b for b in bars if b.ts<SPLIT]), ("HOLD",[b for b in bars if b.ts>=SPLIT])):
    wins = group_by_htf(seg, 60, 5)
    print(f"\n=== HTF 60m {span} : pullback entry ===")
    print(f"  {'retr':>5s} {'pad':>5s} {'tgtR':>5s} {'n':>5s} {'fill%':>6s} {'win%':>6s} {'expR':>8s}")
    for retrace in (0.33, 0.50, 0.618):
        for pad in (0.10, 0.25):
            for tgt_r in (1.0, 2.0):
                rs=[]; attempted=0
                for w in wins:
                    i = idx.get(int(w[0].ts.timestamp()))
                    if i is None or atr[i]<=0: continue
                    attempted += 1
                    r = pullback_trade(w, 0.5*atr[i], retrace, pad, tgt_r)
                    if r is not None: rs.append(r)
                if len(rs) < 150: continue
                print(f"  {retrace:>5.2f} {pad:>5.2f} {tgt_r:>5.1f} {len(rs):5d} "
                      f"{100*len(rs)/max(attempted,1):5.1f}% "
                      f"{100*sum(1 for r in rs if r>0)/len(rs):5.1f}% {st.fmean(rs):+8.3f}")
