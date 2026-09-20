"""Continuous goal-directed search with independent verification.

Three tapes, and a candidate only ever moves forward:

  TUNE    (seed 11)  the climb happens here, and ONLY here
  HOLD    (seed 41)  selection check -- does it survive data it was not fitted to
  VERIFY  (seed 77)  touched only by candidates that already cleared HOLD, plus
                     a permutation null on that same tape

The third tape exists because HOLD stops being independent the moment it is
used to choose between candidates. Run enough rounds against it and it becomes
a second tuning tape. VERIFY is never used to select, only to confirm, and any
candidate that clears it is recorded with the round that produced it so the
selection count is visible rather than hidden.

Runs until stopped. State is appended to a ledger on every round, so killing
the process loses at most one round.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icarus.backtest import shuffle_bars
from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.timeframe import resample
from tools.goal import GOAL, TARGET_COUNT
from tools.htf_context import ContextProvider
from tools.hunt import climb
from tools.sweep_pulse import CONTEXTS, TAPES, PulseVariant, evaluate, load_meta, run_stage

TIMEFRAMES = ("2m", "3m", "5m", "10m", "15m", "20m", "30m")
FULL_2M = 110_000
SEEDS = {"tune": 11, "hold": 41, "verify": 77}


def build_tapes(log=print) -> None:
    for key, seed in SEEDS.items():
        src = synthetic_for(AssetClass.MICRO_FUTURES, FULL_2M, seed=seed, minutes=2)
        for tf in TIMEFRAMES:
            TAPES[(key, tf)] = resample(src, tf)
            CONTEXTS[(key, tf)] = ContextProvider(src, tf)
        log(f"  {key:6s} seed {seed:3d}  "
            f"{(TAPES[(key,'10m')][-1].ts - TAPES[(key,'10m')][0].ts).days} days")


def permutation_p(variant: PulseVariant, observed_net: float, runs: int,
                  rng: random.Random) -> float:
    """Null on the VERIFY tape. Surrogates rebuild their own HTF context."""
    tape = TAPES[("verify", variant.timeframe)]
    minutes = int(variant.timeframe.rstrip("m"))
    overrides = dict(variant.overrides)
    mode = overrides.pop("tpsl_mode", "Structure-Based")
    from tools.validate_pulse import run_pulse

    beats = 0
    for _ in range(runs):
        surrogate = shuffle_bars(tape, rng)
        ctx = ContextProvider(surrogate, variant.timeframe)
        result = run_pulse(surrogate, tf_minutes=minutes, tpsl_mode=mode,
                           context=ctx, **overrides)
        if result.get("net", 0.0) >= observed_net:
            beats += 1
    return (beats + 1) / (runs + 1)


def run_round(index: int, meta, rng: random.Random, *, iterations: int,
              workers: int, null_runs: int, log=print) -> list[dict]:
    log(f"\n--- round {index} ---", flush=True)
    climbed = climb(TIMEFRAMES, meta, iterations=iterations, width=3,
                    workers=workers, rng=rng, log=lambda m: None)

    held = run_stage([v for v, _ in climbed], "hold", workers)
    tune_by = {v.key(): r for v, r in climbed}
    passed_hold = [(v, tune_by[v.key()], hr) for v, hr in held if GOAL.clears(hr, tune_by[v.key()])]
    log(f"  climbed {len(climbed)} -> {len(passed_hold)} cleared HOLD")

    if not passed_hold:
        best = sorted(held, key=lambda x: -GOAL.score(x[1]))[:1]
        if best:
            v, r = best[0]
            log(f"  closest: {v.timeframe} win={r.get('win_rate',0):.1f}% "
                f"-> {', '.join(GOAL.shortfall(r)) or 'n/a'}")
        return []

    verified = []
    for variant, tune, hold in passed_hold:
        vres = evaluate(variant, "verify")
        if not GOAL.clears(vres, tune):
            log(f"  {variant.timeframe} cleared HOLD but FAILED VERIFY "
                f"-> {', '.join(GOAL.shortfall(vres))}")
            continue
        p = permutation_p(variant, vres["net"], null_runs, rng)
        status = "VERIFIED" if p <= 0.05 else f"null p={p:.3f}"
        log(f"  {variant.timeframe} win={vres['win_rate']:.1f}% n={vres['trades']} "
            f"p={p:.4f}  {status}")
        if p <= 0.05:
            verified.append({
                "round": index, "timeframe": variant.timeframe,
                "changed": variant.changed_from_anchor(), "overrides": variant.overrides,
                "tune": tune, "hold": hold, "verify": vres, "p_value": p,
            })
    return verified


def main() -> int:
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    ledger = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/verified.json")
    null_runs = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    workers = 4

    t0 = time.time()
    print("building tune / hold / verify tapes with real HTF context...", flush=True)
    build_tapes()
    print(f"  ({time.time()-t0:.0f}s)\n", flush=True)
    print(f"GOAL: runner 0 legs or >={GOAL.min_runner_win_rate}% | "
          f"win>={GOAL.min_win_rate}% | n>={GOAL.min_trades:.0f} | "
          f"consistency>={GOAL.min_consistency} | top-decile<={GOAL.max_top_decile_share}%")
    print(f"VERIFY: third tape (seed {SEEDS['verify']}) + {null_runs}-run permutation null, p<=0.05\n",
          flush=True)

    meta = load_meta()
    found: list[dict] = []
    if ledger.exists():
        found = json.loads(ledger.read_text())
        print(f"resuming with {len(found)} already verified\n", flush=True)

    index = 0
    while True:
        index += 1
        rng = random.Random(7000 + index * 131)
        try:
            new = run_round(index, meta, rng, iterations=iterations,
                            workers=workers, null_runs=null_runs)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"  round {index} errored: {type(exc).__name__}: {exc}", flush=True)
            continue

        if new:
            found.extend(new)
            ledger.write_text(json.dumps(found, indent=1, default=str))
            print(f"  +{len(new)} verified  (total {len(found)}, target >{TARGET_COUNT})", flush=True)
        print(f"  round {index} done, {time.time()-t0:.0f}s elapsed, "
              f"{len(found)} verified so far", flush=True)


if __name__ == "__main__":
    sys.exit(main() or 0)
