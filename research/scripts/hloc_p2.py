"""H-LOC P2: is any lambda gain just the gate moving?

Inverting a term inside a normalised weighted sum shifts the whole score
distribution, so `min_score` bites in a different place. Re-tune min_score
independently at L=+1 and L=-1 over its full range and compare like for like,
including at matched trade counts.
"""
import sys, json, time
sys.path.insert(0, '/home/user/Icarus-engine')
sys.path.insert(0, '/tmp/claude-0/-home-user-Icarus-engine/134e69c0-9376-5c62-9fa5-dfe829f5f315/scratchpad')
from datetime import datetime, timezone
from icarus.data import load_csv
from hloc_p1 import run, SPLIT

GRID = [round(0.40 + 0.02 * k, 3) for k in range(20)]     # 0.40 .. 0.78


def sweep(tf, policy="hybrid"):
    bars = load_csv(f"/home/user/Icarus-engine/data/mnq_{tf}m_full.csv")
    segs = {"TUNE": [b for b in bars if b.ts < SPLIT], "HOLD": [b for b in bars if b.ts >= SPLIT]}
    table = {}
    for lam in (1.0, -1.0):
        for ms in GRID:
            for name, seg in segs.items():
                table[(lam, ms, name)] = run(seg, tf, policy, lam, min_score=ms)
    return table


def show(tf, table):
    print(f"\n=== {tf}m  min_score re-tune, hybrid ===")
    print(f"{'min_score':>9s} | {'L=+1 TUNE  n / exp$ / net$':>34s} | {'L=-1 TUNE  n / exp$ / net$':>34s}")
    for ms in GRID:
        a, b = table[(1.0, ms, "TUNE")], table[(-1.0, ms, "TUNE")]
        print(f"{ms:9.2f} | {a['trades']:6d} {a.get('expectancy',0):+9.2f} {a.get('net',0):+12,.0f}      "
              f"| {b['trades']:6d} {b.get('expectancy',0):+9.2f} {b.get('net',0):+12,.0f}")
    for lam in (1.0, -1.0):
        cand = [(table[(lam, ms, 'TUNE')].get('net', 0.0), ms) for ms in GRID
                if table[(lam, ms, 'TUNE')]['trades'] >= 40]
        if not cand:
            print(f"  L={lam:+.0f}: no threshold reaches 40 trades on TUNE")
            continue
        best_net, best_ms = max(cand)
        h = table[(lam, best_ms, 'HOLD')]
        t = table[(lam, best_ms, 'TUNE')]
        print(f"  L={lam:+.0f}  TUNE-best min_score={best_ms:.2f}: "
              f"TUNE n={t['trades']} exp=${t.get('expectancy',0):+.2f} net=${t.get('net',0):+,.0f}  ->  "
              f"HOLD n={h['trades']} win={h.get('win_rate',0):.1f}% exp=${h.get('expectancy',0):+.2f} "
              f"PF={h.get('profit_factor',0):.2f} net=${h.get('net',0):+,.0f}")
    # trade-count matched: for each L=-1 threshold, find the L=+1 threshold with
    # the closest TUNE trade count and compare both spans at matched n.
    print(f"  {'--- count-matched (TUNE n within 5%) ---':>44s}")
    print(f"{'n(-1)':>7s} {'ms(-1)':>7s} {'exp T':>8s} {'exp H':>8s} | "
          f"{'n(+1)':>7s} {'ms(+1)':>7s} {'exp T':>8s} {'exp H':>8s} | {'winner HOLD':>12s}")
    for ms in GRID[::2]:
        neg = table[(-1.0, ms, 'TUNE')]
        if neg['trades'] < 40:
            continue
        pool = [(abs(table[(1.0, m2, 'TUNE')]['trades'] - neg['trades']), m2) for m2 in GRID]
        gap, m2 = min(pool)
        if gap > max(3, 0.05 * neg['trades']):
            continue
        pos = table[(1.0, m2, 'TUNE')]
        nh, ph = table[(-1.0, ms, 'HOLD')], table[(1.0, m2, 'HOLD')]
        win = "L=-1" if nh.get('expectancy', 0) > ph.get('expectancy', 0) else "L=+1"
        print(f"{neg['trades']:7d} {ms:7.2f} {neg.get('expectancy',0):+8.2f} {nh.get('expectancy',0):+8.2f} | "
              f"{pos['trades']:7d} {m2:7.2f} {pos.get('expectancy',0):+8.2f} {ph.get('expectancy',0):+8.2f} | "
              f"{win:>12s}")


if __name__ == "__main__":
    for tf in [int(x) for x in sys.argv[1:]] or [20]:
        t0 = time.time()
        table = sweep(tf)
        show(tf, table)
        print(f"  ({time.time()-t0:.0f}s)")
        sys.stdout.flush()
