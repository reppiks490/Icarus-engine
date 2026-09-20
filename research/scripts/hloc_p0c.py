"""Positive control: can this harness still SEE the synthetic effect?

A null result is only worth something if the instrument that produced it can
detect the effect when the effect is there. Same collect() used on real MNQ,
pointed at the two synthetic tapes N-001 was built on. It should reproduce
c_location spread ~= -0.16.
"""
import sys, statistics as st
sys.path.insert(0, '/home/user/Icarus-engine')
sys.path.insert(0, '/tmp/claude-0/-home-user-Icarus-engine/134e69c0-9376-5c62-9fa5-dfe829f5f315/scratchpad')
import hloc_p0
from hloc_p0 import collect, spread
from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample

hloc_p0.HORIZON = 30                                   # rerun.py's horizon
for seed, name in ((11, "tune(seed 11)"), (41, "hold(seed 41)")):
    bars = resample(synthetic_for(AssetClass.MICRO_FUTURES, 150_000, seed=seed, minutes=2), "2m")
    rows = [r for r in collect(bars, 2) if r["score"] > 0 and r["label"] != 0]
    wins = [1.0 if r["label"] > 0 else 0.0 for r in rows]
    base = st.fmean(wins)
    sp, bot, top, qn = spread(rows, "c_location", wins)
    se = (2.0 * base * (1 - base) / qn) ** 0.5
    print(f"SYNTHETIC {name:<14s} n={len(rows):5d} base={base:.4f} "
          f"c_location spread={sp:+.4f} SE={se:.4f} z={sp/se:+.2f}")
