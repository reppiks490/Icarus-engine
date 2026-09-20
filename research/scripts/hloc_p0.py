"""H-LOC P0: does c_location carry any signal on the REAL MNQ tape?

Direction-aware triple-barrier labels, TUNE vs HOLD spans, 5m/10m/20m.
Rows are sweep bars only (the population the engine is actually asked about).
Two populations per span:
  gated  -- score > 0, i.e. the setup survived the hard gates and was scored
             (trap #8: score==0 rows are unscored vetoes and pollute deciles)
  all    -- every sweep bar, with the location score recomputed from vwap_dev
             so gating cannot select on the very term under test
"""
import sys, statistics as st, time
sys.path.insert(0, '/home/user/Icarus-engine')
from datetime import datetime, timezone
from icarus.data import load_csv
from icarus.strategy import IcarusEngine
from icarus.config import AssetClass
from icarus.ml import triple_barrier, engine_features
from icarus.indicators import clamp

SPLIT = datetime(2025, 10, 1, tzinfo=timezone.utc)
HORIZON = 24


def loc_orig(direction, dev):
    favourable = -direction * dev
    if favourable <= 0.0:
        return clamp(0.5 + 0.18 * favourable)
    return clamp(0.5 + 0.5 * min(favourable, 2.5) / 2.5 - 0.22 * max(0.0, favourable - 3.0))


def collect(bars, tf):
    eng = IcarusEngine(AssetClass.MICRO_FUTURES, exit_policy="hybrid", timeframe=f"{tf}m")
    rows = []
    for index, bar in enumerate(bars):
        eng.on_bar(bar)
        sweep = eng.liquidity.last_sweep
        if sweep is None or sweep.index != eng.state.bar_index:
            continue
        direction = int(sweep.direction)
        lab = triple_barrier(bars, index, eng.volatility.state.atr, 2.0, 1.0, HORIZON, direction)
        if lab is None:
            continue
        f = engine_features(eng, bar, sweep, eng.state.signal)
        rows.append(dict(dir=direction, dev=f["vwap_dev"], score=f["score"],
                         c_location=f["c_location"], c_momentum=f["c_momentum"],
                         c_structure=f["c_structure"],
                         loc_raw=loc_orig(direction, f["vwap_dev"]),
                         label=lab.label, fwd=lab.forward_atr))
    return rows


def spread(rows, key, wins):
    s = sorted(range(len(rows)), key=lambda k: rows[k][key])
    n = len(s) // 5
    if n < 30:
        return None
    bot = st.fmean([wins[k] for k in s[:n]])
    top = st.fmean([wins[k] for k in s[-n:]])
    return top - bot, bot, top, n


def report(tag, rows, keys):
    rows = [r for r in rows if r["label"] != 0]
    if len(rows) < 150:
        print(f"  {tag:<28s} n={len(rows)} -- too few decided labels to quote")
        return
    wins = [1.0 if r["label"] > 0 else 0.0 for r in rows]
    base = st.fmean(wins)
    longs = sum(1 for r in rows if r["dir"] > 0)
    print(f"  {tag:<28s} n={len(rows):5d}  base_win={base:.4f}  long_share={longs/len(rows):.3f}")
    for k in keys:
        out = spread(rows, k, wins)
        if out is None:
            print(f"      {k:<14s} (quintile < 30)")
            continue
        sp, bot, top, qn = out
        print(f"      {k:<14s} spread={sp:+.4f}   bottom={bot:.4f} top={top:.4f}  q={qn}")


if __name__ == "__main__":
    tfs = [int(x) for x in sys.argv[1:]] or [20, 10, 5]
    for tf in tfs:
        t0 = time.time()
        bars = load_csv(f"/home/user/Icarus-engine/data/mnq_{tf}m_full.csv")
        tune = [b for b in bars if b.ts < SPLIT]
        hold = [b for b in bars if b.ts >= SPLIT]
        print(f"\n=== {tf}m  ({len(bars)} bars; TUNE {len(tune)} / HOLD {len(hold)}) horizon={HORIZON} bars ===")
        sys.stdout.flush()
        for name, seg in (("TUNE", tune), ("HOLD", hold)):
            rows = collect(seg, tf)
            gated = [r for r in rows if r["score"] > 0]
            report(f"{name} gated (score>0)", gated, ("c_location", "c_momentum", "c_structure", "score"))
            report(f"{name} all sweep bars", rows, ("loc_raw",))
            sys.stdout.flush()
        print(f"  ({time.time()-t0:.0f}s)")
        sys.stdout.flush()
