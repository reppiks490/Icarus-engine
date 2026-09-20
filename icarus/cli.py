"""Command line surface.

    python -m icarus demo     --asset micro_futures --policy hybrid --timeframe 10m
    python -m icarus backtest --csv data/mnq_2m.csv --asset micro_futures --permutations 100
    python -m icarus compare  --asset micro_futures --timeframes 2m,5m,10m,30m
    python -m icarus walk     --csv data/mnq_2m.csv --asset micro_futures --folds 5
    python -m icarus live     --csv data/mnq_2m.csv --asset micro_futures
    python -m icarus export-features --asset micro_futures --out train.csv
"""

from __future__ import annotations

import argparse
import sys

from icarus.backtest import backtest, walk_forward
from icarus.config import AssetClass, profile_for
from icarus.data import load_csv, synthetic_for
from icarus.exits import POLICIES
from icarus.lab import compare, render
from icarus.ml import export_training_set
from icarus.strategy import IcarusEngine
from icarus.timeframe import at_timeframe, parse_timeframe, resample


def _load(args: argparse.Namespace):
    asset = AssetClass(args.asset)
    if getattr(args, "csv", None):
        bars = load_csv(args.csv)
        if not bars:
            raise SystemExit(f"no bars parsed from {args.csv}")
    else:
        minutes = getattr(args, "source_minutes", None)
        extra = {"minutes": minutes} if minutes else {}
        bars = synthetic_for(asset, bars=args.bars, seed=args.seed, **extra)
    if getattr(args, "timeframe", None):
        bars = resample(bars, args.timeframe)
    return asset, bars


def _profile(args: argparse.Namespace):
    profile = profile_for(args.asset)
    if getattr(args, "timeframe", None):
        profile = at_timeframe(profile, args.timeframe)
    if getattr(args, "policy", None):
        profile = profile.with_overrides(exit_policy=args.policy)
    return profile


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="icarus", description="Icarus Engine -- intraday execution core")
    subparsers = parser.add_subparsers(dest="command", required=True)
    assets = [item.value for item in AssetClass]

    def common(sub: argparse.ArgumentParser, *, allow_csv: bool = True) -> None:
        if allow_csv:
            sub.add_argument("--csv", help="OHLCV csv; omit to use the calibrated synthetic tape")
        sub.add_argument("--asset", default="micro_futures", choices=assets)
        sub.add_argument("--bars", type=int, default=8000, help="synthetic tape length")
        sub.add_argument("--seed", type=int, default=11)
        sub.add_argument("--equity", type=float, default=100_000.0)
        sub.add_argument("--policy", choices=sorted(POLICIES),
                         help="exit policy override (default: the profile's)")
        sub.add_argument("--timeframe", help="resample bars and rescale bar-count params, e.g. 10m")

    demo = subparsers.add_parser("demo", help="run on the built-in synthetic tape")
    common(demo, allow_csv=False)
    demo.add_argument("--permutations", type=int, default=0)

    test = subparsers.add_parser("backtest", help="run on a csv or the synthetic tape")
    common(test)
    test.add_argument("--permutations", type=int, default=0,
                      help="shuffled-tape runs used to compute the p-value")

    comp = subparsers.add_parser("compare", help="cross-examine exit policies across timeframes")
    common(comp)
    comp.add_argument("--timeframes", default="2m,5m,10m,30m", help="comma-separated list")
    comp.add_argument("--policies", default="pulse,suite,hybrid", help="comma-separated list")
    comp.add_argument("--permutations", type=int, default=0)
    comp.add_argument("--htf", default="4h", help="higher timeframe for the endurance target")
    comp.add_argument("--source-minutes", type=int, default=2,
                      help="granularity of the synthetic source tape")

    walk = subparsers.add_parser("walk", help="contiguous walk-forward folds")
    common(walk)
    walk.add_argument("--folds", type=int, default=4)

    live = subparsers.add_parser("live", help="replay bars and print every intent as it fires")
    common(live)
    live.add_argument("--tail", type=int, default=40, help="intents to print")

    export = subparsers.add_parser("export-features", help="write a labelled training matrix")
    common(export)
    export.add_argument("--out", default="training.csv")
    export.add_argument("--upper-atr", type=float, default=2.0, help="profit barrier, in ATRs")
    export.add_argument("--lower-atr", type=float, default=1.0, help="loss barrier, in ATRs")
    export.add_argument("--horizon", type=int, default=24, help="barrier horizon, in bars")
    export.add_argument("--all-bars", action="store_true",
                        help="label every bar, not only bars where the trigger fired")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "compare":
        asset = AssetClass(args.asset)
        bars = (load_csv(args.csv) if getattr(args, "csv", None)
                else synthetic_for(asset, bars=args.bars, seed=args.seed,
                                   minutes=args.source_minutes))
        results = compare(
            bars, asset,
            policies=tuple(p.strip() for p in args.policies.split(",") if p.strip()),
            timeframes=tuple(t.strip() for t in args.timeframes.split(",") if t.strip()),
            starting_equity=args.equity, permutations=args.permutations,
            seed=args.seed, htf=args.htf,
        )
        print(render(results, f"ICARUS -- {args.asset} exit policy x timeframe"))
        return 0

    asset, bars = _load(args)
    profile = _profile(args)

    if args.command in ("demo", "backtest"):
        report = backtest(bars, profile, starting_equity=args.equity,
                          permutations=args.permutations, seed=args.seed)
        print(report.render())
        return 0

    if args.command == "walk":
        reports = walk_forward(bars, profile, folds=args.folds, starting_equity=args.equity)
        for index, report in enumerate(reports, start=1):
            print(f"--- fold {index}/{len(reports)} ---")
            print(report.render())
            print()
        surviving = sum(1 for report in reports if report.sum_r > 0.0)
        print(f"folds with positive expectancy: {surviving}/{len(reports)}")
        return 0

    if args.command == "live":
        engine = IcarusEngine(profile, starting_equity=args.equity)
        emitted = [intent for bar in bars for intent in engine.on_bar(bar)]
        for intent in emitted[-args.tail:]:
            print(f"{intent.ts.isoformat()}  {intent.kind.value:10s} "
                  f"{'LONG ' if intent.direction > 0 else 'SHORT'} "
                  f"size={intent.size:12.4f} @ {intent.price:.5f}  {intent.reason}")
        print(f"\n{len(emitted)} intents, {len(engine.blotter.trades)} closed trades, "
              f"equity {engine.equity:,.2f}  (policy: {engine.exit_policy.name})")
        return 0

    if args.command == "export-features":
        rows = export_training_set(
            bars, profile, args.out,
            upper_atr=args.upper_atr, lower_atr=args.lower_atr, horizon=args.horizon,
            sweeps_only=not args.all_bars,
        )
        print(f"wrote {rows} labelled rows to {args.out} "
              f"(barriers +{args.upper_atr}/-{args.lower_atr} ATR over {args.horizon} bars)")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
