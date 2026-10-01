"""Private licensed-history discovery for ICARUS.

Raw licensed exports stay outside Git. This module recognizes explicitly
validated private files by SHA-256 and lets the local runtime consume them
directly from a private folder, Downloads, or a synced Dropbox folder.

No network access, credential access, order logic, or execution authority is
present here.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional


KNOWN_PRIVATE_REPORTS: Dict[str, Dict[str, object]] = {
    "05cebeb4a44fcad254b6c7ee05d66ef8a81593e5d984cf91b5ee1b1a8dd9aae3": {
        "symbol": "NQ",
        "tf_minutes": 20,
        "session": "rth",
        "price_geometry": "standard",
        "chart_type": "Candles",
        "source": "TradingView CME_MINI:NQ1!",
        "canonical_name": "THE_PULSE_OF_ICARUS_CME_MINI_NQ1!_2026-09-30 3.xlsx",
        "trading_range": "Feb 7, 2019 at 08:50 — Sep 29, 2026 at 15:10",
        "backtesting_range": "Feb 1, 2019 at 08:30 — Sep 29, 2026 at 15:10",
        "closed_trades": 473,
        "open_trades": 1,
        "net_profit_usd": 56950.0,
        "percent_profitable": 68.5,
        "max_drawdown_intrabar_usd": 80846.0,
        "report_rows": 949,
        "classification": "EXACT_OPERATOR_STRATEGY_REPORT",
    },
    "dc3c1c3b32bc7da97bcbaa5bd207eb1d462d8104cc77b9f4e5cb75eef9425585": {
        "symbol": "NQ",
        "tf_minutes": 20,
        "session": "rth",
        "price_geometry": "heikin_ashi",
        "chart_type": "Heikin Ashi",
        "source": "TradingView CME_MINI:NQ1!",
        "canonical_name": "THE_PULSE_OF_ICARUS_CME_MINI_NQ1!_2026-09-30 4.xlsx",
        "trading_range": "Feb 7, 2019 at 08:50 — Sep 29, 2026 at 15:10",
        "backtesting_range": "Feb 1, 2019 at 08:30 — Sep 29, 2026 at 15:10",
        "closed_trades": 1204,
        "open_trades": 0,
        "net_profit_usd": 967652.0,
        "percent_profitable": 92.69,
        "max_drawdown_intrabar_usd": 60844.0,
        "report_rows": 2409,
        "classification": "EXACT_OPERATOR_STRATEGY_REPORT",
    },
}

KNOWN_PRIVATE_EXPORTS: Dict[str, Dict[str, object]] = {
    "a8141ffa372b4ffaba4d6bf8b8998a489f2daf00bfad5e248bf27132d99f0932": {
        "symbol": "NQ",
        "tf_minutes": 20,
        "session": "eth",
        "price_geometry": "standard",
        "rows": 41239,
        "first_ts": 1717365600,
        "last_ts": 1790774400,
        "source": "TradingView CME_MINI:NQ1!",
        "filename_hint": "CME_MINI_DL_NQ1!",
    },
    "4fe26a9b2ee9a5e81c24577f2abd51073e7e944f4f6aa43a77b61095af44e48c": {
        "symbol": "NQ",
        "tf_minutes": 20,
        "session": "eth",
        "price_geometry": "heikin_ashi",
        "rows": 41239,
        "first_ts": 1717365600,
        "last_ts": 1790774400,
        "source": "TradingView CME_MINI:NQ1!",
        "filename_hint": "CME_MINI_DL_NQ1!",
    },
}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def private_history_roots(base_dir: Optional[str] = None) -> List[str]:
    """Return deterministic private-history search roots."""
    roots: List[str] = []
    env = os.environ.get("ICARUS_PRIVATE_HISTORY_DIR", "")
    roots.extend(p for p in env.split(os.pathsep) if p.strip())

    home = Path.home()
    roots.extend([
        str(home / "Downloads" / "ICARUS_EXPORTS"),
        str(home / "Downloads"),
        str(home / "Dropbox" / "ICARUS_EXPORTS"),
        str(home / "Dropbox" / "ICARUS_PRIVATE_HISTORY"),
        str(home / "Documents" / "ICARUS_EXPORTS"),
    ])
    if base_dir:
        roots.append(str(Path(base_dir) / "private_history"))

    out=[]; seen=set()
    for p in roots:
        rp=os.path.realpath(os.path.expanduser(p))
        if rp not in seen:
            seen.add(rp); out.append(rp)
    return out


def _candidate_files(root: str, symbol: str) -> Iterable[str]:
    """Yield plausible CSVs from root and one directory level below."""
    if not os.path.isdir(root):
        return
    prefix = "CME_MINI_DL_NQ1!" if symbol.upper()=="NQ" else ""
    try:
        entries=list(os.scandir(root))
    except OSError:
        return
    for ent in entries:
        if ent.is_file() and ent.name.lower().endswith(".csv"):
            if not prefix or ent.name.startswith(prefix) or os.path.basename(root)=="ICARUS_EXPORTS":
                yield ent.path
        elif ent.is_dir() and os.path.basename(root) in ("ICARUS_EXPORTS","ICARUS_PRIVATE_HISTORY","private_history"):
            try:
                for sub in os.scandir(ent.path):
                    if sub.is_file() and sub.name.lower().endswith(".csv"):
                        yield sub.path
            except OSError:
                continue


def discover_private_history(symbol: str, tf_minutes: int, session: str,
                             price_geometry: str="standard", *,
                             base_dir: Optional[str]=None,
                             roots: Optional[Iterable[str]]=None,
                             catalog: Optional[Dict[str,Dict[str,object]]]=None):
    """Find a hash-validated private export matching the requested cell."""
    symbol=str(symbol).upper(); tf=int(tf_minutes)
    session=str(session or "").lower(); geometry=str(price_geometry or "standard").lower()
    catalog = catalog or KNOWN_PRIVATE_EXPORTS
    roots = list(roots) if roots is not None else private_history_roots(base_dir)

    for root in roots:
        for path in _candidate_files(os.path.realpath(os.path.expanduser(root)), symbol) or ():
            try:
                digest=sha256_file(path)
            except OSError:
                continue
            meta=catalog.get(digest)
            if not meta:
                continue
            if (str(meta.get("symbol","")).upper()!=symbol or int(meta.get("tf_minutes") or 0)!=tf
                    or str(meta.get("session","")).lower()!=session
                    or str(meta.get("price_geometry","")).lower()!=geometry):
                continue
            return {
                "path": os.path.realpath(path),
                "display_name": os.path.basename(path),
                "sha256": digest,
                "symbol": symbol,
                "tf_minutes": tf,
                "session": session,
                "price_geometry": geometry,
                "rows": int(meta.get("rows") or 0),
                "first_ts": meta.get("first_ts"),
                "last_ts": meta.get("last_ts"),
                "source": meta.get("source"),
                "classification": "EXACT_OPERATOR_HISTORY",
                "private": True,
                "execution_authorized": False,
            }
    return None



def _candidate_report_files(root: str, symbol: str) -> Iterable[str]:
    """Yield plausible private strategy-report XLSX files."""
    if not os.path.isdir(root):
        return
    prefix = "THE_PULSE_OF_ICARUS_CME_MINI_NQ1!" if symbol.upper()=="NQ" else ""
    try:
        entries=list(os.scandir(root))
    except OSError:
        return
    for ent in entries:
        if ent.is_file() and ent.name.lower().endswith(".xlsx"):
            if not prefix or ent.name.startswith(prefix) or os.path.basename(root)=="ICARUS_EXPORTS":
                yield ent.path
        elif ent.is_dir() and os.path.basename(root) in ("ICARUS_EXPORTS","ICARUS_PRIVATE_HISTORY","private_history"):
            try:
                for sub in os.scandir(ent.path):
                    if sub.is_file() and sub.name.lower().endswith(".xlsx"):
                        yield sub.path
            except OSError:
                continue


def discover_private_reference_reports(symbol: str, tf_minutes: int, session: str, *,
                                       base_dir: Optional[str]=None,
                                       roots: Optional[Iterable[str]]=None,
                                       catalog: Optional[Dict[str,Dict[str,object]]]=None):
    """Return hash-verified strategy-report witnesses for a research cell.

    Report metadata is useful for parity/regression evidence, but it is not bar
    history and is never eligible to seed warm-up or execution.
    """
    symbol=str(symbol).upper(); tf=int(tf_minutes); session=str(session or "").lower()
    catalog = catalog or KNOWN_PRIVATE_REPORTS
    roots = list(roots) if roots is not None else private_history_roots(base_dir)
    matches=[]
    for digest,meta in catalog.items():
        if (str(meta.get("symbol","")).upper()==symbol and int(meta.get("tf_minutes") or 0)==tf
                and str(meta.get("session","")).lower()==session):
            row=dict(meta)
            row.update({
                "sha256":digest,
                "local_file_verified":False,
                "display_name":meta.get("canonical_name"),
                "warmup_eligible":False,
                "data_type":"STRATEGY_REPORT_NOT_BAR_HISTORY",
                "execution_authorized":False,
            })
            matches.append(row)
    if not matches:
        return []

    by_hash={x["sha256"]:x for x in matches}
    found=set()
    for root in roots:
        for path in _candidate_report_files(os.path.realpath(os.path.expanduser(root)), symbol) or ():
            try:
                digest=sha256_file(path)
            except OSError:
                continue
            row=by_hash.get(digest)
            if not row or digest in found:
                continue
            found.add(digest)
            row["local_file_verified"]=True
            row["display_name"]=os.path.basename(path)
    return sorted(matches,key=lambda x:(str(x.get("price_geometry")),str(x.get("sha256"))))


def safe_private_label(meta) -> Optional[str]:
    if not meta:
        return None
    return "private:%s#%s" % (meta.get("display_name","validated-export"), str(meta.get("sha256",""))[:12])
