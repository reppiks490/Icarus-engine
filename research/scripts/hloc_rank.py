"""Does TUNE's ordering of lambda predict HOLD's ordering? (Spearman, stdlib)"""
import re, sys, json, statistics as st

def parse(path):
    out, tf = {}, None
    for line in open(path):
        m = re.search(r"=== (?:pulse\.py )?(\d+)m", line)
        if m:
            tf = int(m.group(1))
        m = re.match(r"\s*L=([-+0-9.]+)\s", line)
        if m and tf:
            lam = float(m.group(1))
            nets = [float(x.replace(",", "")) for x in re.findall(r"net=\$\s*([-+0-9,]+)", line)]
            if len(nets) == 2:
                out[(tf, lam)] = nets
    return out

def spearman(a, b):
    def rank(v):
        order = sorted(range(len(v)), key=lambda k: v[k])
        r = [0.0] * len(v)
        for pos, k in enumerate(order):
            r[k] = pos
        return r
    ra, rb = rank(a), rank(b)
    n = len(a)
    ma, mb = st.fmean(ra), st.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else 0.0

for tag, path in (("icarus/ hybrid", sys.argv[1]),) + tuple(("pulse.py ATR", p) for p in sys.argv[2:]):
    d = parse(path)
    tfs = sorted({k[0] for k in d})
    for tf in tfs:
        lams = sorted(l for (t, l) in d if t == tf)
        tune = [d[(tf, l)][0] for l in lams]
        hold = [d[(tf, l)][1] for l in lams]
        bt, bh = lams[tune.index(max(tune))], lams[hold.index(max(hold))]
        print(f"{tag:<16s} {tf:>3d}m  rho(TUNE,HOLD net over L) = {spearman(tune, hold):+.3f}   "
              f"TUNE argmax L={bt:+.2f} (HOLD there ${d[(tf,bt)][1]:+,.0f})   "
              f"HOLD argmax L={bh:+.2f} (${max(hold):+,.0f})   "
              f"shipped L=+1 HOLD ${d[(tf,1.0)][1]:+,.0f}")
