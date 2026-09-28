"""Backtests on the live engine's cached bars - the dashboard's Strategy Tester.

A backtest builds a fresh, isolated `AssetRunner` (in-memory journal) from a live runner's cached deep
history and sub-bars, replays them with the requested preset / inputs / fill mode / costs (no network,
seconds), and reports TradingView's Strategy Tester numbers (`metrics.tv_summary`), the equity /
drawdown / buy-and-hold curves, the List of Trades in TradingView's columns and a CSV in TradingView's
export format. Jobs run in a thread; results are kept in memory (`JOBS`).

Fill modes are the engine's: `real` (default - real prices, the honest number) and `chart` (Heikin Ashi
bar prices, TradingView's "Heikin Ashi bars" mode, for parity only).
"""
from __future__ import annotations

import csv
import copy
import hashlib
import io
import json
import math
import threading
import time
import uuid
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any, Dict, List, Optional
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from .metrics import PERFORMANCE_ROWS, RISK_ROWS, TRADES_ROWS, Piece, tv_summary
from .pine.timeframe import Bar, tf_minutes
from .runtime import AssetRunner, Journal, RunnerConfig, resolve_inputs, validate_values
from .strategy.inputs import Inputs

JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 20
_CT = ZoneInfo("America/Chicago")


def _fmt_ct(ts: Optional[int]) -> str:
    return datetime.fromtimestamp(ts, _CT).strftime("%Y-%m-%d %H:%M") if ts else "Open"


def freeze_replay_port(port, symbol: str):
    """Capture one coherent source for a replay or a sequence of candidate trials.

    The returned shim owns copies of all configuration and immutable bar tuples.
    Reusing it never rereads the live runner or requests market/feed metadata.
    """
    symbol = symbol.upper()
    if getattr(port, "_replay_frozen", False):
        if symbol not in port.runners:
            raise ValueError(f"{symbol}: not present in the frozen replay source")
        return port
    src = port.runners[symbol]
    with src.lock:
        cfg = copy.deepcopy(src.cfg)
        spec = copy.deepcopy(src.spec)
        base = copy.deepcopy(getattr(src, "inputs_base", cfg.inputs))
        effective = copy.deepcopy(getattr(src, "inputs", base))
        preset = port.preset_for(src)
        htf = {tf_minutes(getattr(base, f"htf_tf_{n}")) for n in range(1, 6)}
        frozen = SimpleNamespace(
            spec=spec, cfg=cfg, inputs_base=base, inputs=effective,
            mintick=getattr(src, "mintick", spec.mintick), pts_scale=getattr(src, "pts_scale", 1.0),
            deep={m: tuple(rows) for m, rows in src.deep.items()}, subbars=tuple(src.subbars),
            T_w=getattr(src, "T_w", None), chains=tuple(getattr(src, "chains", htf | {2, 5})),
            lock=threading.RLock())
    return SimpleNamespace(runners={symbol: frozen}, base_dir=port.base_dir, profile=cfg.profile,
                           feeds={}, preset_for=lambda _: preset, _replay_frozen=True)


def _snapshot_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def validate_backtest_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate before scheduling or replay; retain optional/default semantics."""
    out = copy.deepcopy(params)
    modes = {"fill_on": ("real", "chart"), "chart_type": ("real", "heikin_ashi"), "session": ("rth", "eth")}
    numbers = ("slippage_ticks", "commission", "capital", "leverage", "window_start", "window_end")
    for key in ("preset", *modes, *numbers):
        value = out.get(key)
        if value is None or value == "":
            out.pop(key, None)
            continue
        if key == "preset":
            if not isinstance(value, str):
                raise ValueError("preset must be a string")
        elif key in modes:
            if not isinstance(value, str) or value not in modes[key]:
                raise ValueError(f"{key}: must be one of {modes[key]}")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError(f"{key}: expected a finite number")
            try:
                number = float(value)
            except (ValueError, OverflowError):
                raise ValueError(f"{key}: expected a finite number") from None
            if not math.isfinite(number):
                raise ValueError(f"{key}: expected a finite number")
            if number < 0 or (key in ("capital", "leverage") and number == 0):
                raise ValueError(f"{key}: must be {'positive' if key in ('capital', 'leverage') else 'nonnegative'}")
            if key in ("slippage_ticks", "window_start", "window_end"):
                if not number.is_integer():
                    raise ValueError(f"{key}: expected a whole number")
                if key.startswith("window_") and number > 253402300799:
                    raise ValueError(f"{key}: timestamp is outside the supported calendar range")
                out[key] = int(number)
            else:
                out[key] = number
    if out.get("window_start") is not None and out.get("window_end") is not None and out["window_start"] > out["window_end"]:
        raise ValueError("window_start must not exceed window_end")
    if out.get("inputs") is None:
        out.pop("inputs", None)
    else:
        vals = out["inputs"]
        if not isinstance(vals, dict):
            raise ValueError("inputs must be an object")
        bad = set(vals) - set(Inputs.__dataclass_fields__)
        if bad:
            raise ValueError(f"unknown input names {sorted(map(str, bad))}")
        try:
            validate_values(vals)
        except OverflowError:
            raise ValueError("inputs must contain finite numbers") from None
    return out


def run_backtest(port, symbol: str, *, preset: Optional[str] = None, inputs: Optional[Dict[str, Any]] = None,
                 fill_on: Optional[str] = None, chart_type: Optional[str] = None, slippage_ticks: Optional[int] = None,
                 commission: Optional[float] = None, capital: Optional[float] = None, session: Optional[str] = None,
                 window_start: Optional[int] = None, window_end: Optional[int] = None, leverage: float = 50.0,
                 progress=None) -> Dict[str, Any]:
    """Report entries from start onward using only bars completed by end.

    Earlier bars retain strategy/position warmup state but their trades do not
    contribute to the reported equity. Open trades are marked at the last
    completed chart close; a partial final chart bar is not simulated.
    """
    params = validate_backtest_params({"preset": preset, "inputs": inputs, "fill_on": fill_on, "chart_type": chart_type,
                                      "slippage_ticks": slippage_ticks, "commission": commission, "capital": capital,
                                      "session": session, "window_start": window_start, "window_end": window_end, "leverage": leverage})
    preset, inputs = params.get("preset"), params.get("inputs", {})
    fill_on, chart_type, session = params.get("fill_on"), params.get("chart_type"), params.get("session")
    slippage_ticks, commission, capital = params.get("slippage_ticks"), params.get("commission"), params.get("capital")
    window_start, window_end, leverage = params.get("window_start"), params.get("window_end"), params.get("leverage", 50.0)
    port = freeze_replay_port(port, symbol)
    src: AssetRunner = port.runners[symbol.upper()]
    spec = replace(src.spec)
    preset_name = preset if preset is not None else port.preset_for(src)
    spec.preset = preset_name or None
    if preset is not None:
        inp, meta, sources = resolve_inputs(spec, port.base_dir, port.profile, preset_name or None, inputs or None)
    else:
        vals = copy.deepcopy(inputs or {})
        bad = set(vals) - set(src.inputs_base.to_dict())
        if bad:
            raise ValueError(f"unknown input names {sorted(bad)}")
        validate_values(vals)
        inp = replace(src.inputs_base, **vals)
        meta = {}
        sources = list(src.cfg.sources or []) + ["frozen source inputs"] + (["override"] if vals else [])
    requested = {tf_minutes(getattr(inp, f"htf_tf_{n}")) for n in range(1, 6)}
    available = set(src.chains) | {m for m, rows in src.deep.items() if rows}
    missing = requested - available
    if missing:
        raise ValueError(f"{src.spec.symbol}: cached history unavailable for requested HTF minutes {sorted(missing)}; fetch compatible history first")
    if meta.get("chart_type") in ("real", "heikin_ashi"):
        spec.chart_type = meta["chart_type"]
    if meta.get("slippage_ticks") is not None:
        spec.slippage_ticks = int(meta["slippage_ticks"])
    if meta.get("commission") is not None:
        spec.commission = float(meta["commission"])
    if meta.get("capital") is not None:
        spec.capital = float(meta["capital"])
    if meta.get("session") in ("rth", "eth") and spec.calendar == "cme":
        spec.session = meta["session"]
    if fill_on in ("real", "chart"):
        spec.fill_on = fill_on
    if chart_type in ("real", "heikin_ashi"):
        spec.chart_type = chart_type
    if slippage_ticks is not None:
        spec.slippage_ticks = int(slippage_ticks)
    if commission is not None:
        spec.commission = float(commission)
    if capital is not None:
        spec.capital = float(capital)
    if session in ("rth", "eth") and spec.calendar == "cme":
        spec.session = session
    cfg = RunnerConfig(spec=spec, inputs=inp, warmup_bars=src.cfg.warmup_bars, sources=sources, profile=port.profile,
                       preset=preset_name or None, pts_ref_price=src.cfg.pts_ref_price,
                       fixed_pts_scale=src.pts_scale, mintick=src.mintick, scale_known_at=src.cfg.scale_known_at)
    r = AssetRunner(cfg, Journal(":memory:"))
    path: List[List[float]] = []
    real_closes: List[float] = []
    orig = r._on_chart_bar
    closed_seen = 0
    realized = 0.0
    replayed = 0

    def included(ts: int) -> bool:
        return (window_start is None or ts >= window_start) and (window_end is None or ts <= window_end)

    def hooked(real: Bar, live: bool) -> None:
        nonlocal closed_seen, realized, replayed
        if window_end is not None and r.cal.bucket_end(real.ts, r.chart_minutes) > window_end:
            return
        orig(real, live)
        for t in r.em.closed[closed_seen:]:
            if included(t.entry_ts):
                realized += t.profit
        closed_seen = len(r.em.closed)
        if included(real.ts):
            upl = sum(t.direction * (real.c - t.entry_price) * t.qty * r.em.contract_size - r.em.commission * t.qty
                      for t in r.em.open if included(t.entry_ts))
            path.append([real.ts, spec.capital + realized + upl])
            real_closes.append(real.c)
        replayed += 1
        if progress and replayed % 100 == 0:
            progress(replayed)
    r._on_chart_bar = hooked                                   # type: ignore[assignment]
    # replay the live runner's cached history: deep native bars, then every sub-bar since T_w
    deep, subs = src.deep, src.subbars
    for m, rows in deep.items():
        ch = r.chains.get(m)
        if ch:
            for b, sub in rows:
                if window_end is not None and r.cal.bucket_end(b.ts, sub) > window_end:
                    continue
                r._push_deep(ch, b, sub)
    for b, sub in subs:
        if window_end is not None and r.cal.bucket_end(b.ts, sub) > window_end:
            continue
        r.on_sub_bar(b, sub, live=False, record=False)
    r.warm = True

    # trades -> TradingView pieces
    closed_all = list(r.em.closed)
    pieces: List[Piece] = []
    for k, t in enumerate(closed_all, 1):
        if not included(t.entry_ts):
            continue
        pieces.append(Piece(no=k, direction=t.direction, qty=t.qty, entry_ts=t.entry_ts, entry_px=t.entry_price, exit_ts=t.exit_ts, exit_px=t.exit_price,
                            exit_signal=t.exit_comment, pnl=t.profit, commission=r.em.commission * t.qty * 2.0, runup=t.runup, drawdown=t.drawdown,
                            bars=t.bars, entry_id=t.entry_id))
    mark = real_closes[-1] if real_closes else None
    open_pieces: List[Piece] = []
    for k, t in enumerate(r.em.open, len(closed_all) + 1):
        if not included(t.entry_ts):
            continue
        upl = (t.direction * (mark - t.entry_price) * t.qty * r.em.contract_size - r.em.commission * t.qty) if mark is not None else 0.0
        open_pieces.append(Piece(no=k, direction=t.direction, qty=t.qty, entry_ts=t.entry_ts, entry_px=t.entry_price, exit_ts=None, exit_px=None,
                                 exit_signal="Open", pnl=upl, commission=r.em.commission * t.qty,
                                 runup=max(0.0, t.direction * (t.best - t.entry_price) * t.qty * r.em.contract_size - r.em.commission * t.qty),
                                 drawdown=min(0.0, t.direction * (t.worst - t.entry_price)) * t.qty * r.em.contract_size - r.em.commission * t.qty,
                                 bars=(r.bar_index - t.entry_bar), entry_id=t.entry_id))
    bars_n = len(path)
    bt_start = path[0][0] if path else None
    bt_end = r.cal.bucket_end(int(path[-1][0]), r.chart_minutes) if path else None
    path_w = path
    summary = tv_summary(pieces, open_pieces, initial_capital=spec.capital, point_value=r.em.contract_size,
                         backtest_start=bt_start, backtest_end=bt_end,
                         first_close=(real_closes[0] if real_closes else None), last_close=mark, leverage=leverage,
                         equity_path=[(int(t), e) for t, e in path_w] or None)
    # curves
    eq_curve = [[int(t), round(e, 2)] for t, e in path_w]
    peak = spec.capital; dd_curve = []
    for t, e in path_w:
        peak = max(peak, e); dd_curve.append([int(t), round(e - peak, 2)])
    bh_curve = []
    if real_closes and path_w:
        first_close = real_closes[0]
        qty = int(spec.capital // (first_close * r.em.contract_size)) if first_close * r.em.contract_size > 0 else 0
        for (t, _), c in zip(path_w, real_closes):
            bh_curve.append([int(t), round(spec.capital + (c - first_close) * r.em.contract_size * qty, 2)])
    rows = {
        "performance": [_row(summary, k, label, kind) for k, label, kind in PERFORMANCE_ROWS],
        "trades": [_row(summary, k, label, kind) for k, label, kind in TRADES_ROWS],
        "risk": [_row(summary, k, label, kind) for k, label, kind in RISK_ROWS],
    }
    trades = _trade_rows(pieces, open_pieces, r.em.contract_size)
    source_config = {"spec": asdict(src.spec), "runner_config": asdict(src.cfg),
                     "base_inputs": src.inputs_base.to_dict(), "effective_inputs": src.inputs.to_dict(),
                     "mintick": src.mintick, "pts_scale": src.pts_scale, "T_w": src.T_w}
    effective_config = {"spec": asdict(spec), "base_inputs": inp.to_dict(), "effective_inputs": r.inputs.to_dict(),
                        "mintick": r.mintick, "pts_scale": r.pts_scale, "window_start": window_start,
                        "window_end": window_end, "leverage": leverage}
    literal_scale = src.cfg.pts_ref_price == 0 and src.pts_scale == 1.0
    scale_known_at = src.cfg.scale_known_at
    historical_scale_asof_valid = literal_scale or (
        type(scale_known_at) is int and scale_known_at > 0
        and window_start is not None and scale_known_at <= window_start)
    reproducibility = {
        "source_config": source_config, "effective_config": effective_config,
        "source_config_sha256": _snapshot_hash(source_config), "effective_config_sha256": _snapshot_hash(effective_config),
        "subbars_sha256": _snapshot_hash([(asdict(b), sub) for b, sub in subs]),
        "deep_sha256": _snapshot_hash({m: [(asdict(b), sub) for b, sub in rows] for m, rows in deep.items()}),
        "subbars_count": len(subs), "deep_counts": {str(m): len(rows) for m, rows in deep.items()},
        "scale_source": "literal points (no reference scaling)" if literal_scale else "frozen source scale",
        "scale_known_at": scale_known_at,
        "historical_scale_asof_valid": historical_scale_asof_valid,
        "scale_caveat": (None if historical_scale_asof_valid else
                         "The frozen source scale was not recorded before the scored window. Collect forward history after scale initialization; reproducibility alone is not historical validity."),
    }
    r.journal.con.close()
    return {
        "asset": r.symbol, "bars": bars_n, "config": {
            "preset": preset_name, "fill_on": spec.fill_on, "chart_type": spec.chart_type, "slippage_ticks": spec.slippage_ticks,
            "commission": spec.commission, "capital": spec.capital, "session": getattr(r.cal, "session", "24/7"), "tf": r.chart_minutes,
            "point_value": r.em.contract_size, "overrides": inputs or {}, "sources": sources, "leverage": leverage,
            "window_start": window_start, "window_end": window_end, "pts_scale": r.pts_scale,
            "historical_scale_asof_valid": historical_scale_asof_valid, "reproducibility": reproducibility,
        },
        "range": {"start": bt_start, "end": bt_end, "first_trade": (pieces[0].entry_ts if pieces else None), "last_trade": (pieces[-1].exit_ts if pieces else None)},
        "summary": summary, "rows": rows, "trades": trades, "equity": eq_curve, "drawdown": dd_curve, "buy_hold": bh_curve,
        "csv": trades_csv(trades), "sources": sources,
    }


def _row(summary, key, label, kind):
    v = summary.get(key, {"all": None, "long": None, "short": None})
    pct = summary.get(key + "_pct") if kind == "$%" else None
    return {"key": key, "label": label, "kind": kind, "all": v.get("all"), "long": v.get("long"), "short": v.get("short"),
            "all_pct": (pct or {}).get("all"), "long_pct": (pct or {}).get("long"), "short_pct": (pct or {}).get("short")}


def _trade_rows(pieces: List[Piece], open_pieces: List[Piece], point_value: float) -> List[Dict[str, Any]]:
    out = []
    cum = 0.0
    for p in sorted(pieces, key=lambda p: (p.exit_ts, p.no)):
        cum += p.pnl
        notional = p.entry_px * p.qty * point_value
        out.append({"no": p.no, "type": ("long" if p.direction > 0 else "short"), "entry_ts": p.entry_ts, "entry_px": p.entry_px, "entry_signal": p.entry_id or ("Long" if p.direction > 0 else "Short"),
                    "exit_ts": p.exit_ts, "exit_px": p.exit_px, "exit_signal": p.exit_signal, "qty": p.qty, "value": notional, "pnl": p.pnl,
                    "return_pct": (p.pnl / notional * 100.0) if notional else None, "commission": p.commission,
                    "runup": p.runup, "runup_pct": (p.runup / notional * 100.0) if notional and p.runup is not None else None,
                    "drawdown": p.drawdown, "drawdown_pct": (p.drawdown / notional * 100.0) if notional and p.drawdown is not None else None,
                    "cum_pnl": cum, "bars": p.bars, "open": False})
    for p in open_pieces:
        notional = p.entry_px * p.qty * point_value
        out.append({"no": p.no, "type": ("long" if p.direction > 0 else "short"), "entry_ts": p.entry_ts, "entry_px": p.entry_px, "entry_signal": p.entry_id or ("Long" if p.direction > 0 else "Short"),
                    "exit_ts": None, "exit_px": None, "exit_signal": "Open", "qty": p.qty, "value": notional, "pnl": p.pnl,
                    "return_pct": (p.pnl / notional * 100.0) if notional else None, "commission": p.commission,
                    "runup": p.runup, "runup_pct": (p.runup / notional * 100.0) if notional and p.runup is not None else None,
                    "drawdown": p.drawdown, "drawdown_pct": (p.drawdown / notional * 100.0) if notional and p.drawdown is not None else None,
                    "cum_pnl": cum + p.pnl, "bars": p.bars, "open": True})
    return out


def _px(v: float) -> str:
    return f"{v:.6f}".rstrip("0").rstrip(".")


def trades_csv(rows: List[Dict[str, Any]]) -> str:
    """TradingView's List-of-Trades export layout (exit row then entry row per trade, Chicago time)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Trade number", "Type", "Date and time", "Signal", "Price USD", "Size (qty)", "Size (value)", "Net PnL USD", "Return %", "Commission USD",
                "Favorable excursion USD", "Favorable excursion %", "Adverse excursion USD", "Adverse excursion %", "Cumulative PnL USD", "Cumulative PnL %", "Duration (bars)"])
    for r in rows:
        common = [r["qty"], f"{r['value']:.0f}", f"{r['pnl']:.0f}", f"{(r['return_pct'] or 0):.2f}", f"{r['commission']:.0f}",
                  f"{(r['runup'] or 0):.0f}", f"{(r['runup_pct'] or 0):.2f}", f"{(r['drawdown'] or 0):.0f}", f"{(r['drawdown_pct'] or 0):.2f}",
                  f"{r['cum_pnl']:.0f}", "", r["bars"]]
        w.writerow([r["no"], f"Exit {r['type']}", _fmt_ct(r["exit_ts"]), r["exit_signal"], (_px(r["exit_px"]) if r["exit_px"] is not None else "—")] + common)
        w.writerow([r["no"], f"Entry {r['type']}", _fmt_ct(r["entry_ts"]), r["entry_signal"], _px(r["entry_px"])] + common)
    return buf.getvalue()


def start_job(port, params: Dict[str, Any]) -> str:
    params = validate_backtest_params(params)
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "running", "progress": 0, "started": time.time(), "params": params, "result": None, "error": None}
    with _JOBS_LOCK:
        JOBS[job_id] = job
        if len(JOBS) > _MAX_JOBS:
            for old in sorted(JOBS.values(), key=lambda j: j["started"])[: len(JOBS) - _MAX_JOBS]:
                JOBS.pop(old["id"], None)

    def run():
        try:
            res = run_backtest(port, params["asset"], preset=params.get("preset"), inputs=params.get("inputs"), fill_on=params.get("fill_on"),
                               chart_type=params.get("chart_type"), slippage_ticks=params.get("slippage_ticks"), commission=params.get("commission"),
                               capital=params.get("capital"), session=params.get("session"), window_start=params.get("window_start"),
                               window_end=params.get("window_end"), leverage=float(params.get("leverage") or 50.0),
                               progress=lambda n: job.__setitem__("progress", n))
            job["result"] = res
            job["status"] = "done"
        except Exception as ex:                                # reported to the caller, never raised in the thread
            job["error"] = f"{type(ex).__name__}: {ex}"
            job["status"] = "error"
        job["finished"] = time.time()
    threading.Thread(target=run, daemon=True, name=f"backtest-{job_id}").start()
    return job_id
