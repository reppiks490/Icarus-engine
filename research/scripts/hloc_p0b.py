"""H-LOC P0 (part b): is the c_location spread distinguishable from noise?

Same rows as hloc_p0.py, but each quintile spread gets a standard error and a
within-span label-permutation p-value (labels shuffled, feature order kept, so
the null is 'this feature orders outcomes no better than chance').
"""
import sys, statistics as st, random, time
sys.path.insert(0, '/home/user/Icarus-engine')
sys.path.insert(0, '/tmp/claude-0/-home-user-Icarus-engine/134e69c0-9376-5c62-9fa5-dfe829f5f315/scratchpad')
from hloc_p0 import collect, SPLIT
from icarus.data import load_csv

REPS = 400


def quint_spread(order, wins):
    n = len(order) // 5
    return st.fmean([wins[k] for k in order[-n:]]) - st.fmean([wins[k] for k in order[:n]]), n


def study(rows, key):
    rows = [r for r in rows if r["label"] != 0]
    wins = [1.0 if r["label"] > 0 else 0.0 for r in rows]
    order = sorted(range(len(rows)), key=lambda k: rows[k][key])
    sp, qn = quint_spread(order, wins)
    base = st.fmean(wins)
    se = (2.0 * base * (1 - base) / qn) ** 0.5
    rng = random.Random(7)
    hits = 0
    for _ in range(REPS):
        shuffled = wins[:]
        rng.shuffle(shuffled)
        s2, _ = quint_spread(order, shuffled)
        if abs(s2) >= abs(sp):
            hits += 1
    return sp, se, (hits + 1) / (REPS + 1), len(rows), qn


if __name__ == "__main__":
    print(f"{'tf':>4s} {'span':>5s} {'population':>12s} {'feature':>11s} {'n':>6s} {'q':>5s} "
          f"{'spread':>8s} {'SE':>7s} {'z':>6s} {'perm p':>7s}")
    for tf in (5, 10, 20, 30):
        bars = load_csv(f"/home/user/Icarus-engine/data/mnq_{tf}m_full.csv")
        for name, seg in (("TUNE", [b for b in bars if b.ts < SPLIT]),
                          ("HOLD", [b for b in bars if b.ts >= SPLIT])):
            rows = collect(seg, tf)
            for pop, rs, key in (("gated", [r for r in rows if r["score"] > 0], "c_location"),
                                 ("all-sweeps", rows, "loc_raw")):
                sp, se, p, n, qn = study(rs, key)
                print(f"{tf:>3d}m {name:>5s} {pop:>12s} {key:>11s} {n:>6d} {qn:>5d} "
                      f"{sp:+8.4f} {se:7.4f} {sp/se:+6.2f} {p:7.4f}")
                sys.stdout.flush()
