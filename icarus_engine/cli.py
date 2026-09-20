"""icarus-engine CLI.

  icarus-engine run        --assets NQ,ES,YM,GC,SI,PL,PA,BTCF,BTC [--tf 20] [--preset NQ-20m-ultracoded] [--fill-on real|chart]
  icarus-engine backtest   --assets NQ [--tf 20] [--preset ...] [--csv out.csv] [--verbose 20]
  icarus-engine parity     --asset NQ --tv-csv "List of Trades.csv" [--tf 20] [--preset ...] [--fill-on chart]
  icarus-engine import-tv  <TradingView strategy export .xlsx|.csv> --name NQ-20m-mine     -> presets/<name>.json
  icarus-engine inputs     [--profile nq|crypto] [--preset NAME]                            -> the effective inputs as JSON
  icarus-engine assets                                                                      -> the asset registry

Asset tokens: NQ, ES, YM, GC, SI, PL, PA, BTCF (CME bitcoin), MBT, BTC (Coinbase spot), ETH, SOL ...
  NQ@10                    chart timeframe per asset
  GC@20:NQ-10m-original    per-asset preset
Any ./inputs.json is a global override; ./inputs.<SYM>.json a per-asset override (the dashboard edits those).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

from .assets import REGISTRY, parse_spec
from .runtime import AssetRunner, Journal, Portfolio, resolve_inputs


def _base_dir() -> str:
    return os.getcwd()


def _portfolio(args: argparse.Namespace, journal: Journal) -> Portfolio:
    port = Portfolio(journal, _base_dir(), poll_sec=getattr(args, "poll", 5.0), profile=args.profile, preset=args.preset,
                     warmup_bars=args.warmup, pts_ref_symbol=args.pts_ref_symbol)
    for tok in [a for a in args.assets.split(",") if a.strip()]:
        spec = parse_spec(tok, args.tf)
        if args.fill_on:
            spec.fill_on = args.fill_on
        if args.chart_type:
            spec.chart_type = args.chart_type
        if args.slippage is not None:
            spec.slippage_ticks = args.slippage
        if args.capital:
            spec.capital = args.capital
        if getattr(args, "session", None) and spec.calendar == "cme":
            spec.session = args.session
        if getattr(args, "security_source", None):
            spec.security_source = args.security_source
        if getattr(args, "roll", None):
            spec.roll = args.roll
        port.add_asset(spec, start=False)
    return port


def _summary(r: AssetRunner) -> str:
    cl = r.em.closed
    n = len(cl); wins = sum(1 for t in cl if t.profit > 0)
    gp = sum(t.profit for t in cl if t.profit > 0); gl = -sum(t.profit for t in cl if t.profit <= 0)
    pf = (gp / gl) if gl > 0 else float("inf") if gp > 0 else 0.0
    eq = r.spec.capital; peak = eq; dd = 0.0
    for t in cl:
        eq += t.profit; peak = max(peak, eq); dd = max(dd, peak - eq)
    rate_n = sum(1 for t in cl if t.entry_id in ("Long", "Short")); tide_n = n - rate_n
    ents = len({(t.entry_id, t.entry_ts) for t in cl})
    return (f"{r.symbol:>5} {r.chart_minutes}m {r.spec.chart_type}/{r.spec.fill_on} slip={r.spec.slippage_ticks}  bars={r.bar_index + 1}  entries={ents} pieces={n} (RATE {rate_n} / TIDE {tide_n})  "
            f"win={wins / n * 100 if n else 0:.1f}%  net={r.em.netprofit:+,.0f}  PF={pf:.2f}  maxDD={dd:,.0f}  open={r.em.position_size:+d}")


def cmd_backtest(args: argparse.Namespace) -> int:
    journal = Journal(args.db or ":memory:")                  # never journal a backtest into the live engine's database
    port = _portfolio(args, journal)
    t0 = time.time()
    for r in port.runner_list():
        r.warmup()
        print(_summary(r))
        if args.csv:
            path = args.csv if len(port.order) == 1 else args.csv.replace(".csv", f"_{r.symbol}.csv")
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(r.export_csv())
            print(f"   trades -> {path}")
        if args.verbose:
            for t in r.em.closed[-args.verbose:]:
                print(f"   {time.strftime('%m-%d %H:%M', time.gmtime(t.entry_ts))} {t.entry_id:<9} x{t.qty} {t.entry_price:.6g} -> "
                      f"{time.strftime('%m-%d %H:%M', time.gmtime(t.exit_ts))} {t.exit_price:.6g} {t.exit_comment:<8} {t.profit:+.2f}")
    print(f"done in {time.time() - t0:.1f}s")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .server import serve
    journal = Journal(args.db)
    port = _portfolio(args, journal)
    journal.log("INFO", f"ICARUS Engine starting: {port.order} tf={args.tf}m preset={args.preset} profile={args.profile} fills={args.fill_on or 'preset/real'}")
    port.start()
    print(f"\nICARUS ENGINE  assets={port.order}  tf={args.tf}m  preset={args.preset}")
    print(f"  dashboard : http://127.0.0.1:{args.port}/     admin token: {args.token}")
    print("  warming up each asset from history, then LIVE (futures wait for the CME open); Ctrl+C to stop\n")
    if args.open:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    try:
        serve(port, args.port, args.token)
    except KeyboardInterrupt:
        pass
    finally:
        port.stop()
    return 0


def cmd_inputs(args: argparse.Namespace) -> int:
    spec = parse_spec(args.asset or "NQ", args.tf)
    inputs, meta, sources = resolve_inputs(spec, _base_dir(), args.profile, args.preset)
    d = inputs.to_dict()
    d["_sources"] = sources
    if meta:
        d["_meta"] = meta
    print(json.dumps(d, indent=2, ensure_ascii=True))
    return 0


def cmd_assets(args: argparse.Namespace) -> int:
    for s in REGISTRY.values():
        print(f"  {s.symbol:<5} {s.name:<30} feed={s.feed:<8} calendar={s.calendar:<6} tick={s.mintick:<6} $/pt={s.multiplier:<7} tv={s.tv_symbol}")
    return 0


def _read_tv_properties(path: str) -> dict:
    props = {}
    if path.lower().endswith(".xlsx"):
        import zipfile
        from xml.etree import ElementTree as ET
        z = zipfile.ZipFile(path); ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        ss = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                ss.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml")); names = [s.get("name") for s in wb.find("m:sheets", ns)]
        if "Properties" not in names:
            raise SystemExit("no 'Properties' sheet in this workbook (export the full strategy report from the Strategy Tester)")
        root = ET.fromstring(z.read(f"xl/worksheets/sheet{names.index('Properties') + 1}.xml"))
        for row in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
            vals = []
            for c in row:
                v = c.find("m:v", ns); t = c.get("t")
                vals.append("" if v is None else (ss[int(v.text)] if t == "s" else v.text))
            if len(vals) >= 2 and vals[0]:
                props[vals[0]] = vals[1]
    else:
        import csv
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                if len(row) >= 2:
                    props[row[0].strip()] = row[1].strip()
    return props


def cmd_import_tv(args: argparse.Namespace) -> int:
    """TradingView strategy export (.xlsx with a Properties sheet, or a label,value CSV) -> preset."""
    import re
    from .strategy.meta import inputs_from_tv_properties
    props = _read_tv_properties(args.file)
    ov = inputs_from_tv_properties(props)
    for k in ("htf_tf_1", "htf_tf_2", "htf_tf_3", "htf_tf_4", "htf_tf_5"):
        if k in ov:
            ov[k] = {"1D": "D", "1W": "W"}.get(str(ov[k]), ov[k])
    meta = {"source": os.path.basename(args.file), "script": props.get("name", ""), "symbol": props.get("Symbol", ""), "timeframe": props.get("Timeframe", ""),
            "chart_type": "heikin_ashi" if "heikin" in str(props.get("Chart type", "")).lower() else "real",
            "slippage_ticks": int(re.sub(r"[^0-9]", "", str(props.get("Slippage", "0"))) or 0),
            "commission": float(str(props.get("Commission", "2")).split()[0] or 2), "capital": float(str(props.get("Initial capital", "500000")).replace(",", "") or 500000),
            "tv_trading_range": props.get("Trading range", "")}
    os.makedirs(os.path.join(_base_dir(), "presets"), exist_ok=True)
    dest = os.path.join(_base_dir(), "presets", f"{args.name}.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump({"_meta": meta, **ov}, fh, indent=1, ensure_ascii=False)
    print(f"wrote {dest}: {len(ov)} inputs differ from the script defaults; chart={meta['chart_type']} slippage={meta['slippage_ticks']} tf={meta['timeframe']}")
    for k, v in ov.items():
        print(f"   {k} = {v!r}")
    return 0


def cmd_parity(args: argparse.Namespace) -> int:
    from .parity import compare
    journal = Journal(args.db or ":memory:")
    args.assets = args.asset
    port = _portfolio(args, journal)
    r = port.runner_list()[0]
    r.warmup()
    print(_summary(r))
    rep = compare(r, args.tv_csv, tol_bars=args.tol)
    print(json.dumps(rep["summary"], indent=2))
    for line in rep["lines"][: args.lines]:
        print("  " + line)
    return 0


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="icarus-engine", description="THE PULSE OF ICARUS - self-contained paper-trading engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(s: argparse.ArgumentParser, multi: bool = True) -> None:
        if multi:
            s.add_argument("--assets", default="NQ,ES,YM,GC,SI,PL,PA,BTCF,BTC", help="comma list of asset tokens (see `assets`)")
        s.add_argument("--tf", default="20", help="chart timeframe in minutes (per-asset with NQ@10)")
        s.add_argument("--preset", default="NQ-20m-ultracoded-0914", help="presets/<name>.json applied to every asset (per-asset with GC:NAME); '' for none")
        s.add_argument("--profile", default="nq", choices=["nq", "crypto"], help="base defaults before presets/overrides")
        s.add_argument("--fill-on", default=None, choices=["real", "chart"], help="fill orders on real bars (default) or on the chart's Heikin Ashi bars (TradingView 'Heikin Ashi bars')")
        s.add_argument("--chart-type", default=None, choices=["real", "heikin_ashi"], help="override the preset's chart type")
        s.add_argument("--slippage", type=int, default=None, help="override the preset's slippage (ticks)")
        s.add_argument("--session", default=None, choices=["rth", "eth"], help="CME chart session: rth = TradingView 'Regular trading hours' 09:30-16:15 ET (default, your charts), eth = full Globex session")
        s.add_argument("--security-source", default=None, choices=["chart", "standard"], help="what the HTF/LTF request.security chains see on a Heikin Ashi chart: chart = HA bars (TradingView, default), standard = real bars")
        s.add_argument("--roll", default=None, choices=["volume", "none"], help="live-feed contract roll for NQ/ES/YM: volume = TradingView's 1! rule (default), none = Yahoo's =F front month")
        s.add_argument("--capital", type=float, default=None, help="override initial capital per asset")
        s.add_argument("--warmup", type=int, default=1200, help="chart bars of history to replay before going live")
        s.add_argument("--pts-ref-symbol", default="NQ", help="asset whose price anchors the *_pts inputs (they are NQ points)")
        s.add_argument("--db", default=None, help="journal database (run: icarus_engine.db; backtest/parity: in memory unless given)")

    s = sub.add_parser("run", help="live paper trading + dashboard")
    common(s)
    s.add_argument("--port", type=int, default=8791)
    s.add_argument("--token", default="icarus")
    s.add_argument("--poll", type=float, default=5.0)
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_run)

    b = sub.add_parser("backtest", help="replay history only and print the strategy's results")
    common(b)
    b.add_argument("--csv", default=None)
    b.add_argument("--verbose", type=int, default=0)
    b.set_defaults(fn=cmd_backtest)

    q = sub.add_parser("parity", help="compare with a TradingView 'List of Trades' CSV export")
    common(q, multi=False)
    q.add_argument("--asset", required=True)
    q.add_argument("--tv-csv", required=True)
    q.add_argument("--tol", type=int, default=1)
    q.add_argument("--lines", type=int, default=80)
    q.set_defaults(fn=cmd_parity)

    n = sub.add_parser("inputs", help="print the effective inputs for an asset")
    n.add_argument("--asset", default="NQ")
    n.add_argument("--tf", default="20")
    n.add_argument("--profile", default="nq", choices=["nq", "crypto"])
    n.add_argument("--preset", default="NQ-20m-ultracoded")
    n.set_defaults(fn=cmd_inputs)

    a = sub.add_parser("assets", help="list the asset registry")
    a.set_defaults(fn=cmd_assets)

    i = sub.add_parser("import-tv", help="TradingView strategy export -> presets/<name>.json")
    i.add_argument("file")
    i.add_argument("--name", required=True)
    i.set_defaults(fn=cmd_import_tv)

    args = p.parse_args(argv)
    if getattr(args, "preset", None) == "":
        args.preset = None
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
