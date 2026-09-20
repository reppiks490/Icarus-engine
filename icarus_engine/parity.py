"""Parity check: this engine's trades vs a TradingView Strategy Tester "List of Trades" export.

How to produce the TradingView side:
  1. Load THE_PULSE_OF_ICARUS v3/v3.1 on the SAME symbol and timeframe the engine runs
     (e.g. COINBASE:BTCUSD, 5m) with the same input changes (crypto profile:
     `icarus-engine inputs --profile crypto`).
  2. Strategy Tester → List of Trades → Export (CSV).
  3. `icarus-engine parity --asset BTC --tf 5 --warmup 2000 --tv-csv "<file>"`

Matching: trades are grouped by entry (TradingView lists each partial exit as a
row pair with the same trade number). An engine trade matches a TV trade when
direction agrees and the entry time is within `tol` chart bars, after the
chart-timezone offset that maximises matches is chosen automatically.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from .runtime import AssetRunner


def _num(s: str) -> float:
    s = (s or "").replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _parse_dt(s: str) -> int:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            pass
    raise ValueError(f"unrecognised date: {s!r}")


def read_tv_trades(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return read_tv_trades_text(fh.read())


def read_tv_trades_text(text: str) -> List[Dict[str, Any]]:
    import io as _io
    rows = list(csv.DictReader(_io.StringIO(text.lstrip("﻿"))))
    if not rows:
        return []
    keys = {k.lower(): k for k in rows[0].keys()}

    def col(*names: str) -> str:
        for n in names:
            for lk, k in keys.items():
                if n in lk:
                    return k
        raise KeyError(names)
    c_no, c_type, c_dt, c_sig = col("trade #", "trade number", "trade"), col("type"), col("date"), col("signal")
    c_px = col("price"); c_qty = col("position size", "size (qty)", "contracts", "qty"); c_pnl = col("net p&l usd", "net pnl usd", "net pnl", "profit usd", "profit", "p&l")
    # TradingView numbers every partial exit as its own "trade" (TP1 and TP2 of one entry are
    # trade #2 and #3). Regroup by (entry time, direction, entry price) so one entry = one trade.
    by_no: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        no = r[c_no].strip(); typ = r[c_type].strip().lower()
        t = by_no.setdefault(no, {"no": no, "dir": 0, "pieces": []})
        if typ.startswith("entry"):
            t["dir"] = 1 if "long" in typ else -1
            t["entry_ts"] = _parse_dt(r[c_dt]); t["entry_px"] = _num(r[c_px]); t["entry_sig"] = r[c_sig].strip(); t["qty"] = _num(r[c_qty])
        elif typ.startswith("exit"):
            if r[c_dt].strip().lower() == "open" or r[c_sig].strip().lower() == "open":     # still-open piece at export time
                t["pieces"].append({"ts": None, "px": float("nan"), "sig": "OPEN", "qty": _num(r[c_qty]), "pnl": _num(r[c_pnl])})
                continue
            t["pieces"].append({"ts": _parse_dt(r[c_dt]), "px": _num(r[c_px]), "sig": r[c_sig].strip(), "qty": _num(r[c_qty]), "pnl": _num(r[c_pnl])})
    trades: Dict[tuple, Dict[str, Any]] = {}
    for t in by_no.values():
        if not t.get("entry_ts"):
            continue
        k = (t["entry_ts"], t["dir"], round(t["entry_px"], 4))
        g = trades.setdefault(k, {"no": t["no"], "dir": t["dir"], "entry_ts": t["entry_ts"], "entry_px": t["entry_px"], "entry_sig": t["entry_sig"], "qty": 0.0, "pieces": []})
        g["qty"] += t["qty"]; g["pieces"].extend(t["pieces"])
    out = list(trades.values())
    out.sort(key=lambda t: t["entry_ts"])
    return out


def engine_trades(r: AssetRunner) -> List[Dict[str, Any]]:
    groups: Dict[tuple, Dict[str, Any]] = {}
    for ct in r.em.closed:
        k = (ct.entry_id, ct.entry_ts)
        g = groups.setdefault(k, {"id": ct.entry_id, "dir": ct.direction, "entry_ts": ct.entry_ts, "entry_px": ct.entry_price, "qty": 0, "pieces": []})
        g["qty"] += ct.qty
        g["pieces"].append({"ts": ct.exit_ts, "px": ct.exit_price, "sig": ct.exit_comment, "qty": ct.qty, "pnl": ct.profit})
    for ot in r.em.open:                                       # still-open entries take part in the matching too
        k = (ot.entry_id, ot.entry_ts)
        g = groups.setdefault(k, {"id": ot.entry_id, "dir": ot.direction, "entry_ts": ot.entry_ts, "entry_px": ot.entry_price, "qty": 0, "pieces": []})
        g["qty"] += ot.qty
        g["pieces"].append({"ts": None, "px": float("nan"), "sig": "OPEN", "qty": ot.qty, "pnl": 0.0})
    out = list(groups.values())
    out.sort(key=lambda t: t["entry_ts"])
    return out


def engine_trades_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The same structure from a backtest job's trade rows (backtest.py)."""
    groups: Dict[tuple, Dict[str, Any]] = {}
    for t in rows:
        d = 1 if t["type"] == "long" else -1
        k = (t.get("entry_signal") or t["type"], t["entry_ts"])
        g = groups.setdefault(k, {"id": t.get("entry_signal") or t["type"], "dir": d, "entry_ts": t["entry_ts"], "entry_px": t["entry_px"], "qty": 0, "pieces": []})
        g["qty"] += t["qty"]
        g["pieces"].append({"ts": t["exit_ts"], "px": (t["exit_px"] if t["exit_px"] is not None else float("nan")), "sig": ("OPEN" if t.get("open") else t["exit_signal"]), "qty": t["qty"], "pnl": t["pnl"] if not t.get("open") else 0.0})
    out = list(groups.values())
    out.sort(key=lambda t: t["entry_ts"])
    return out


def compare(r: AssetRunner, tv_csv: str, tol_bars: int = 1) -> Dict[str, Any]:
    return compare_lists(engine_trades(r), read_tv_trades(tv_csv), r.chart_minutes * 60, tol_bars)


def compare_lists(eng: List[Dict[str, Any]], tv: List[Dict[str, Any]], bar: int, tol_bars: int = 1) -> Dict[str, Any]:
    if not tv or not eng:
        return {"summary": {"tv_trades": len(tv), "engine_trades": len(eng), "note": "nothing to compare"}, "lines": []}
    # restrict to the overlapping window
    lo = max(min(t["entry_ts"] for t in eng), min(t["entry_ts"] for t in tv) - 14 * 3600)
    best = None
    for off_half in range(-28, 29):
        off = off_half * 1800
        used = set(); n = 0
        for e in eng:
            for j, t in enumerate(tv):
                if j in used or t["dir"] != e["dir"]:
                    continue
                if abs((t["entry_ts"] + off) - e["entry_ts"]) <= tol_bars * bar:
                    used.add(j); n += 1; break
        if best is None or n > best[1]:
            best = (off, n)
    off, _ = best
    tv_adj = [dict(t, entry_ts=t["entry_ts"] + off, pieces=[dict(p, ts=(p["ts"] + off) if p["ts"] is not None else None) for p in t["pieces"]]) for t in tv]
    tv_w = [t for t in tv_adj if t["entry_ts"] >= lo]
    eng_w = [t for t in eng if t["entry_ts"] >= lo]
    used = set(); matched = []; unmatched_eng = []
    for e in eng_w:
        hit = None
        for j, t in enumerate(tv_w):
            if j in used or t["dir"] != e["dir"]:
                continue
            if abs(t["entry_ts"] - e["entry_ts"]) <= tol_bars * bar:
                hit = j; break
        if hit is None:
            unmatched_eng.append(e)
        else:
            used.add(hit); matched.append((e, tv_w[hit]))
    unmatched_tv = [t for j, t in enumerate(tv_w) if j not in used]
    px_diff = [abs(e["entry_px"] - t["entry_px"]) / t["entry_px"] * 1e4 for e, t in matched if t["entry_px"] == t["entry_px"]]
    exit_agree = sum(1 for e, t in matched if sorted(p["sig"] for p in e["pieces"]) == sorted(p["sig"] for p in t["pieces"]))
    pnl_eng = sum(p["pnl"] for e in eng_w for p in e["pieces"]); pnl_tv = sum(p["pnl"] for t in tv_w for p in t["pieces"] if p["pnl"] == p["pnl"])
    lines = []
    for e, t in matched:
        lines.append(f"MATCH  {_ts(e['entry_ts'])} {'L' if e['dir']>0 else 'S'} eng {e['entry_px']:.6g} tv {t['entry_px']:.6g}  exits eng {[p['sig'] for p in e['pieces']]} tv {[p['sig'] for p in t['pieces']]}")
    for e in unmatched_eng:
        lines.append(f"ENGINE-ONLY {_ts(e['entry_ts'])} {'L' if e['dir']>0 else 'S'} @ {e['entry_px']:.6g} exits {[p['sig'] for p in e['pieces']]}")
    for t in unmatched_tv:
        lines.append(f"TV-ONLY     {_ts(t['entry_ts'])} {'L' if t['dir']>0 else 'S'} @ {t['entry_px']:.6g} exits {[p['sig'] for p in t['pieces']]}")
    n_all = len(eng_w) + len(unmatched_tv)
    return {"summary": {
        "window_start": _ts(lo), "tz_offset_hours": off / 3600, "engine_trades": len(eng_w), "tv_trades": len(tv_w),
        "matched": len(matched), "engine_only": len(unmatched_eng), "tv_only": len(unmatched_tv),
        "match_rate_pct": round(len(matched) / n_all * 100, 1) if n_all else None,
        "exit_signature_agreement_pct": round(exit_agree / len(matched) * 100, 1) if matched else None,
        "avg_entry_price_diff_bps": round(sum(px_diff) / len(px_diff), 2) if px_diff else None,
        "net_pnl_engine": round(pnl_eng, 2), "net_pnl_tv": round(pnl_tv, 2),
    }, "lines": lines}


def _ts(t: int) -> str:
    return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
