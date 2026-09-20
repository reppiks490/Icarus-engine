"""Command line surface.

    python -m icarus demo    --asset crypto --bars 6000 --permutations 50
    python -m icarus backtest --csv data/es_5m.csv --asset futures --permutations 100
    python -m icarus walk    --csv data/es_5m.csv --asset futures --folds 5
    python -m icarus live    --csv data/es_5m.csv --asset futures      # replay, prints intents
"""

from __future__ import annotations

import argparse
import sys

from icarus.backtest import backtest, run_engine, walk_forward
from icarus.config import AssetClass
from icarus.data import load_csv, synthetic_for
from icarus.strategy import IcarusEngine


def _load(args: argparse.Namespace):
    asset = AssetClass(args.asset)
    if getattr(args, "csv", None):
        bars = load_csv(args.csv)
        if not bars:
            raise SystemExit(f"no bars parsed from {args.csv}")
        return asset, bars
    return asset, synthetic_for(asset, bars=args.bars, seed=args.seed)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="icarus", description="Icarus Engine -- intraday execution core")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser, *, allow_csv: bool = True) -> None:
        if allow_csv:
            sub.add_argument("--csv", help="OHLCV csv; omit to use the calibrated synthetic tape")
        sub.add_argument("--asset", default="futures", choices=[item.value for item in AssetClass])
        sub.add_argument("--bars", type=int, default=6000, help="synthetic tape length")
        sub.add_argument("--seed", type=int, default=11)
        sub.add_argument("--equity", type=float, default=100_000.0)

    demo = subparsers.add_parser("demo", help="run on the built-in synthetic tape")
    common(demo, allow_csv=False)
    demo.add_argument("--permutations", type=int, default=0)

    test = subparsers.add_parser("backtest", help="run on a csv or the synthetic tape")
    common(test)
    test.add_argument("--permutations", type=int, default=0,
                      help="shuffled-tape runs used to compute the p-value")

    walk = subparsers.add_parser("walk", help="contiguous walk-forward folds")
    common(walk)
    walk.add_argument("--folds", type=int, default=4)

    live = subparsers.add_parser("live", help="replay bars and print every intent as it fires")
    common(live)
    live.add_argument("--tail", type=int, default=40, help="intents to print")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    asset, bars = _load(args)

    if args.command in ("demo", "backtest"):
        report = backtest(bars, asset, starting_equity=args.equity,
                          permutations=args.permutations, seed=args.seed)
        print(report.render())
        return 0

    if args.command == "walk":
        reports = walk_forward(bars, asset, folds=args.folds, starting_equity=args.equity)
        for index, report in enumerate(reports, start=1):
            print(f"--- fold {index}/{len(reports)} ---")
            print(report.render())
            print()
        surviving = sum(1 for report in reports if report.sum_r > 0.0)
        print(f"folds with positive expectancy: {surviving}/{len(reports)}")
        return 0

    if args.command == "live":
        engine = IcarusEngine(asset, starting_equity=args.equity)
        emitted = []
        for bar in bars:
            for intent in engine.on_bar(bar):
                emitted.append(intent)
        for intent in emitted[-args.tail:]:
            print(f"{intent.ts.isoformat()}  {intent.kind.value:10s} "
                  f"{'LONG ' if intent.direction > 0 else 'SHORT'} "
                  f"size={intent.size:12.4f} @ {intent.price:.5f}  {intent.reason}")
        print(f"\n{len(emitted)} intents, {len(engine.blotter.trades)} closed trades, "
              f"equity {engine.equity:,.2f}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
