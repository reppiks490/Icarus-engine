"""Does the sweep premise hold, anywhere, in any market?

The engine's entire thesis is that a liquidity sweep -- price taking out a
prior extreme and then reclaiming it -- is followed by a move in the reversal
direction. Every result in this project has been a parameter search inside
that assumption. A permutation null on the finished strategy said the entry
signal is not distinguishable from random (p=0.377 held-out), which is what it
looks like when the assumption itself is wrong.

So: test the assumption, not the strategy. No confluence, no ML gate, no exit
policy, no thresholds to fit. Just the structure, measured against matched
controls, in every market on disk.

The design is built to make a false positive hard rather than easy:

  CROSS-ASSET     A microstructure claim about resting stop orders should hold
                  in gold and crude and credit, not only in the instrument it
                  was designed on. Replication across unrelated markets is
                  worth more than any single-market p-value.
  TWO HALVES      Each market is split in time; a sign that flips between
                  halves is noise, however significant it looks in one.
  MATCHED         Sweeps are compared against non-sweep bars at the same time
                  of day and in the same volatility regime, not against zero.
  FDR CONTROLLED  The grid runs hundreds of tests. At p<0.05 roughly one in
                  twenty comes back "significant" with nothing there, which is
                  how every prior result in this repo was born.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icarus.data import load_csv
from tools.asset_panel import ASSET_CLASS, load_panel
from tools.duration import HOLD
from tools.premise import (Tape, benjamini_hochberg, find_sweeps,
                           forward_return, matched_controls, welch_t)

LOOKBACKS = (10, 20, 40)
RECLAIMS = (1, 2, 3)
PENETRATIONS = (0.0, 0.25)


def run_market(name: str, bars, tf_minutes: float) -> list[dict]:
    """Every (variant x horizon x half) cell for one market."""
    horizons = HOLD.horizons(tf_minutes)
    results = []
    half = len(bars) // 2
    for span_name, seg in (("early", bars[:half]), ("late", bars[half:])):
        tape = Tape(seg)
        for lookback in LOOKBACKS:
            for reclaim in RECLAIMS:
                for pen in PENETRATIONS:
                    sweeps = find_sweeps(tape, lookback=lookback,
                                         reclaim_bars=reclaim,
                                         min_penetration_atr=pen)
                    if len(sweeps) < 40:
                        continue
                    for horizon in horizons:
                        treated = [v for v in
                                   (forward_return(tape, s.index, horizon, s.direction)
                                    for s in sweeps) if v is not None]
                        controls = matched_controls(tape, sweeps, horizon)
                        if len(treated) < 40 or len(controls) < 40:
                            continue
                        t, p = welch_t(treated, controls)
                        results.append({
                            "market": name, "class": ASSET_CLASS.get(name, "futures"),
                            "span": span_name, "lookback": lookback,
                            "reclaim": reclaim, "pen": pen, "horizon": horizon,
                            "n": len(treated), "t": t, "p": p,
                            "effect": (sum(treated) / len(treated)) - (sum(controls) / len(controls)),
                        })
    return results


def main() -> None:
    rows: list[dict] = []

    panel = load_panel()
    for name, bars in sorted(panel.items()):
        rows.extend(run_market(name, bars, 5.0))
        print(f"  {name:<8s} done ({len(rows)} cells so far)", flush=True)

    for tf in (5, 10, 20):
        bars = load_csv(f"data/mnq_{tf}m_full.csv")
        rows.extend(run_market(f"MNQ{tf}m", bars, float(tf)))
        print(f"  MNQ{tf}m   done ({len(rows)} cells so far)", flush=True)

    print(f"\n{len(rows)} tests across {len({r['market'] for r in rows})} markets")

    keep = benjamini_hochberg([r["p"] for r in rows], alpha=0.05)
    survivors = [r for r, k in zip(rows, keep) if k]
    raw_hits = [r for r in rows if r["p"] < 0.05]
    print(f"raw p<0.05: {len(raw_hits)}  (expected by chance alone: ~{len(rows) * 0.05:.0f})")
    print(f"survive FDR control: {len(survivors)}")

    # The question that matters more than any p-value: does a variant hold its
    # SIGN in both halves, and in how many unrelated markets?
    print("\n--- sign consistency across the two halves, per market ---")
    print(f"    {'market':<9s} {'class':<14s} {'cells':>6s} {'early+':>7s} {'late+':>7s} {'agree':>7s}")
    for market in sorted({r["market"] for r in rows}):
        cells = [r for r in rows if r["market"] == market]
        early = {(r["lookback"], r["reclaim"], r["pen"], r["horizon"]): r["effect"]
                 for r in cells if r["span"] == "early"}
        late = {(r["lookback"], r["reclaim"], r["pen"], r["horizon"]): r["effect"]
                for r in cells if r["span"] == "late"}
        shared = set(early) & set(late)
        if not shared:
            continue
        agree = sum(1 for k in shared if early[k] * late[k] > 0)
        pos_e = sum(1 for k in shared if early[k] > 0)
        pos_l = sum(1 for k in shared if late[k] > 0)
        klass = cells[0]["class"]
        print(f"    {market:<9s} {klass:<14s} {len(shared):6d} "
              f"{100*pos_e/len(shared):6.0f}% {100*pos_l/len(shared):6.0f}% "
              f"{100*agree/len(shared):6.0f}%")

    if survivors:
        print("\n--- cells surviving FDR ---")
        survivors.sort(key=lambda r: r["p"])
        for r in survivors[:25]:
            print(f"    {r['market']:<9s} {r['span']:<6s} lb={r['lookback']:<3d} "
                  f"rc={r['reclaim']} pen={r['pen']:.2f} h={r['horizon']:<3d} "
                  f"n={r['n']:5d} effect={r['effect']:+.4f} ATR  p={r['p']:.5f}")
    else:
        print("\nNothing survives FDR control. The premise is not visible in the raw")
        print("structure of any market on the panel, at any of these settings.")


if __name__ == "__main__":
    main()
