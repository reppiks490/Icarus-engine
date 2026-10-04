# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.smoke: end-to-end smoke run of the grammar on the committed MNQ tape
"""python -m cl_lab.smoke [--limit-days N]: prints counts and wall time only (no performance claims)."""
from __future__ import annotations

import argparse
import collections
import time

from . import backtest, bars, costs, grammar, sessions


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/mnq_5m_full.csv")
    ap.add_argument("--limit-days", type=int, default=0)
    a = ap.parse_args(argv)
    t0 = time.time()
    adf = bars.annotate(bars.load_csv(a.csv))
    if a.limit_days:
        keep = sorted(set(adf["session_date"]))[: a.limit_days]
        adf = adf[adf["session_date"].isin(set(keep))]
    sess = sessions.build_sessions(adf)
    cands = grammar.enumerate_candidates()
    per_fam, trades = collections.Counter(), collections.Counter()
    for c in cands:
        per_fam[c.family] += 1
        trades[c.family] += backtest.run(c, sess, costs.MNQ).n_trades
    print(f"sessions={sess.D} complete={int(sess.complete.sum())} candidates={len(cands)} "
          f"registration={grammar.registration_hash(cands)[:16]}")
    for f in per_fam:
        print(f"  {f:6s} candidates={per_fam[f]:4d} trades={trades[f]}")
    print(f"wall={time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
