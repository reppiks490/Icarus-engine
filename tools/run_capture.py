"""Is an HTF move reachable from the LTF? Measured, not argued."""

from __future__ import annotations

import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icarus.data import load_csv
from tools.capture import (atr_of, commitment_entry, concentration,
                           directionality, group_by_htf)

SPLIT = datetime(2025, 10, 1, tzinfo=timezone.utc)


def main() -> None:
    ltf_minutes = 5
    bars = load_csv(f"data/mnq_{ltf_minutes}m_full.csv")
    atr = atr_of(bars)
    atr_at = {int(b.ts.timestamp()): a for b, a in zip(bars, atr)}

    for htf_minutes in (20, 60):
        print(f"\n{'='*86}")
        print(f"HTF {htf_minutes}m   LTF {ltf_minutes}m   "
              f"({htf_minutes // ltf_minutes} sub-bars per HTF bar)")
        print("=" * 86)

        for span_name, seg in (("TUNE", [b for b in bars if b.ts < SPLIT]),
                               ("HOLD", [b for b in bars if b.ts >= SPLIT])):
            windows = group_by_htf(seg, htf_minutes, ltf_minutes)
            if not windows:
                continue

            # Size each window against the volatility prevailing when it opened,
            # so "big" means big for the conditions rather than big in points.
            sized = []
            for w in windows:
                a = atr_at.get(int(w[0].ts.timestamp()), 0.0)
                if a <= 0:
                    continue
                rng = max(b.high for b in w) - min(b.low for b in w)
                sized.append((rng / a, w, a))
            if not sized:
                continue
            sized.sort(key=lambda x: x[0])
            big = [x for x in sized if x[0] >= sized[int(0.80 * len(sized))][0]]

            print(f"\n  {span_name}: {len(windows)} HTF bars, "
                  f"top quintile by range = {len(big)} 'big' bars")

            d_all = [directionality(w) for _, w, _ in sized]
            d_big = [directionality(w) for _, w, _ in big]
            c_big = [concentration(w) for _, w, _ in big]
            print(f"    directionality  all {st.median(d_all):.2f}   "
                  f"big {st.median(d_big):.2f}   "
                  f"(1.0 = pure trend, 0.0 = round trip)")
            print(f"    concentration   big {st.median(c_big):.2f}   "
                  f"(1.0 = arrived in one LTF print)")
            oneprint = sum(1 for c in c_big if c > 0.60)
            print(f"    big bars where one LTF bar carried >60% of travel: "
                  f"{oneprint}/{len(c_big)} ({100*oneprint/len(c_big):.0f}%)")

            print(f"    {'trigger':>9s} {'fired':>7s} {'MFE':>8s} {'MAE':>8s} "
                  f"{'MFE/MAE':>8s} {'realised':>9s} {'win%':>6s}")
            for trig_atr in (0.25, 0.50, 0.75):
                rows = []
                for _, w, a in sized:
                    r = commitment_entry(w, trig_atr * a)
                    if r is not None:
                        rows.append((r, a))
                if len(rows) < 50:
                    continue
                mfe = [r.mfe / a for r, a in rows]
                mae = [abs(r.mae) / a for r, a in rows]
                real = [r.realised / a for r, a in rows]
                wins = sum(1 for r, _ in rows if r.realised > 0)
                ratio = st.median(mfe) / st.median(mae) if st.median(mae) > 0 else 0.0
                print(f"    {trig_atr:>8.2f}A {len(rows):7d} {st.median(mfe):+8.2f} "
                      f"{-st.median(mae):+8.2f} {ratio:8.2f} "
                      f"{st.fmean(real):+9.2f} {100*wins/len(rows):6.1f}")


if __name__ == "__main__":
    main()
