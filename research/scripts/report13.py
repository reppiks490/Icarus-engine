"""Render P1 and P3 from lam11.json / lam41.json."""
import json, sys
SP = "/tmp/claude-0/-home-user-Icarus-engine/134e69c0-9376-5c62-9fa5-dfe829f5f315/scratchpad/"
A = json.load(open(SP + "lam11.json"))      # TUNE
B = json.load(open(SP + "lam41.json"))      # HOLD
LAMS = ["-1.00","-0.75","-0.50","-0.25","+0.00","+0.25","+0.50","+0.75","+1.00"]

print("=" * 108)
print("P1  HORIZON CROSSOVER -- expR by lambda, shipped gate (min_confluence 0.56), hybrid exit")
print("=" * 108)
print(f"{'tf':>4s} {'tape':>5s} {'n@l=+1':>7s} | " + " ".join(f"{l:>7s}" for l in LAMS) + f" | {'lam*':>6s} {'lam*(comb)':>10s}")
p1_star = {}
for tf in A["p1"]:
    combined = {}
    for tag, D in (("tune", A), ("hold", B)):
        row = D["p1"][tf]
        vals = [row[l].get("exp", float("nan")) for l in LAMS]
        star = LAMS[max(range(len(LAMS)), key=lambda k: vals[k])]
        n1 = row["+1.00"].get("n", 0)
        for l in LAMS:
            combined[l] = combined.get(l, 0.0) + row[l].get("exp", 0.0)
        print(f"{tf:>4s} {tag:>5s} {n1:7d} | " + " ".join(f"{v:+7.3f}" for v in vals) + f" | {star:>6s}")
    cstar = max(LAMS, key=lambda l: combined[l])
    p1_star[tf] = cstar
    print(f"{'':>4s} {'sum':>5s} {'':>7s} | " + " ".join(f"{combined[l]:+7.3f}" for l in LAMS) + f" | {'':>6s} {cstar:>10s}")
    print()
print("lambda* per timeframe (sum of the two tapes' expR):")
for tf, s in p1_star.items():
    n_t = A["p1"][tf]["+1.00"].get("n", 0); n_h = B["p1"][tf]["+1.00"].get("n", 0)
    flag = "" if min(n_t, n_h) >= 150 else "   <-- BELOW the 150-trade quotable floor (trap 3)"
    print(f"  {tf:>4s}  lam* = {s}   (n at lam=+1: tune {n_t}, hold {n_h}){flag}")

print()
print("=" * 108)
print("P3  KILL TEST -- min_score re-tuned INDEPENDENTLY at lam=+1 and lam=-1")
print("=" * 108)
for tf in A["p3"]:
    print(f"\n--- {tf} ---")
    print(f"{'min_score':>9s} | {'lam=+1 TUNE':>26s} | {'lam=+1 HOLD':>26s} | {'lam=-1 TUNE':>26s} | {'lam=-1 HOLD':>26s}")
    grid = sorted(A["p3"][tf]["+1.00"].keys(), key=float)
    for ms in grid:
        cells = []
        for lam in ("+1.00", "-1.00"):
            for D in (A, B):
                r = D["p3"][tf][lam][ms]
                cells.append(f"n={r.get('n',0):4d} exp={r.get('exp',0):+6.3f} win={r.get('win',0):5.1f}"
                             if r.get("n") else "        (no trades)       ")
        print(f"{ms:>9s} | " + " | ".join(cells))

    # Honest selection: pick min_score on TUNE, report HOLD.
    print(f"\n  {tf}: gate selected on the TUNE tape (seed 11), then read on HOLD (seed 41)")
    for lam in ("+1.00", "-1.00"):
        for floor in (0, 120):
            cand = [(ms, A["p3"][tf][lam][ms]) for ms in grid
                    if A["p3"][tf][lam][ms].get("n", 0) >= max(floor, 30)]
            if not cand:
                print(f"    lam={lam} n>={floor}: no gate leaves that many trades"); continue
            ms, tr = max(cand, key=lambda x: x[1]["exp"])
            hr = B["p3"][tf][lam][ms]
            print(f"    lam={lam} n>={floor:3d}: min_score*={ms}  TUNE n={tr['n']:4d} exp={tr['exp']:+.3f} "
                  f"win={tr['win']:5.1f} dd={tr['dd']:5.2f}  ->  HOLD n={hr.get('n',0):4d} "
                  f"exp={hr.get('exp',0):+.3f} win={hr.get('win',0):5.1f} dd={hr.get('dd',0):5.2f}")
    # Best-on-own-tape upper bound for each lambda (in sample, both tapes)
    print(f"  {tf}: BEST-ON-OWN-TAPE upper bound (in sample -- flatters both sides equally)")
    for lam in ("+1.00", "-1.00"):
        for tag, D in (("tune", A), ("hold", B)):
            cand = [(ms, D["p3"][tf][lam][ms]) for ms in grid if D["p3"][tf][lam][ms].get("n", 0) >= 30]
            ms, r = max(cand, key=lambda x: x[1]["exp"])
            print(f"    lam={lam} {tag}: best min_score={ms} n={r['n']:4d} exp={r['exp']:+.3f} win={r['win']:5.1f} dd={r['dd']:5.2f}")
    # Matched trade count
    print(f"  {tf}: MATCHED TRADE COUNT -- lam=+1 gate chosen to land on lam=-1's n at the shipped 0.560 gate")
    for tag, D in (("tune", A), ("hold", B)):
        base = D["p3"][tf]["-1.00"].get("0.55") or D["p3"][tf]["-1.00"]["0.550"]
        target = base.get("n", 0)
        cand = [(ms, D["p3"][tf]["+1.00"][ms]) for ms in grid if D["p3"][tf]["+1.00"][ms].get("n", 0)]
        ms, r = min(cand, key=lambda x: abs(x[1]["n"] - target))
        print(f"    {tag}: lam=-1 @0.550 n={target:4d} exp={base['exp']:+.3f} win={base['win']:5.1f}"
              f"   vs   lam=+1 @{ms} n={r['n']:4d} exp={r['exp']:+.3f} win={r['win']:5.1f}")
