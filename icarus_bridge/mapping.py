"""Futures-signal -> equity-proxy mapping, level conversion, sizing. Pure functions.

Why percentages: NQ ≈ 20,000 and QQQ ≈ 500 move ~1:1 in PERCENT (same index),
so a 45-pt NQ stop (0.225%) becomes a 0.225% QQQ stop. TQQQ (3x) gets 3× the
percentage so the dollar-risk geometry survives the leverage.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional

from .config import Settings
from .models import Alert


@dataclass
class Levels:
    """Percent distances (positive numbers) from the reference price."""
    tp1_pct: float
    tp2_pct: float
    sl_pct: float
    ref_price: Optional[float]          # futures reference the pts were measured against
    source: str                         # meta | default


def map_symbol(ticker: str, symbol_map: Dict[str, str]) -> Optional[str]:
    t = (ticker or "").upper().strip()
    if t in symbol_map:
        return symbol_map[t]
    # strip exchange prefix (CME_MINI:NQ1!) and contract months (NQZ2026)
    if ":" in t:
        t2 = t.split(":", 1)[1]
        if t2 in symbol_map:
            return symbol_map[t2]
        t = t2
    root = t.rstrip("!0123456789")
    for suffix in ("1!", "!", ""):
        k = root + suffix
        if k in symbol_map:
            return symbol_map[k]
    # month-coded futures like NQZ2026 / NQU26 -> NQ
    if len(root) >= 3 and root[:-1] in symbol_map:
        return symbol_map[root[:-1]]
    return None


def levels_from_alert(alert: Alert, cfg: Settings) -> Levels:
    """Prefer pts embedded by the Pine alert_message; else the configured defaults."""
    m = alert.meta or {}
    ref = None
    for k in ("ref", "entry"):
        if isinstance(m.get(k), (int, float)) and m[k] > 0:
            ref = float(m[k]); break
    if ref is None:
        ref = alert.order_price or alert.bar_close
    tp1 = m.get("tp1"); tp2 = m.get("tp2"); sl = m.get("sl")
    have_meta = all(isinstance(x, (int, float)) and x > 0 for x in (tp1, tp2, sl))
    if not have_meta:
        tp1, tp2, sl = cfg.default_tp1_pts, cfg.default_tp2_pts, cfg.default_sl_pts
    if not ref or ref <= 0:
        # no reference price at all: fall back to a generic NQ scale so we still get sane %s
        ref = 20000.0
    lev = cfg.leverage_factor if cfg.leverage_factor > 0 else 1.0
    return Levels(
        tp1_pct=float(tp1) / ref * lev,
        tp2_pct=float(tp2) / ref * lev,
        sl_pct=float(sl) / ref * lev,
        ref_price=ref,
        source="meta" if have_meta else "default",
    )


def pct_from_prices(level_price: float, ref_price: float, leverage: float = 1.0) -> float:
    """Signed percent distance of a futures level from a futures reference, leverage-scaled."""
    if not ref_price:
        return 0.0
    return (level_price - ref_price) / ref_price * (leverage if leverage > 0 else 1.0)


def apply_pct(price: float, pct: float) -> float:
    return price * (1.0 + pct)


def round_price(p: float) -> float:
    """Alpaca sub-penny rule: >= $1 → 2 decimals, < $1 → 4."""
    return round(p, 2) if p >= 1.0 else round(p, 4)


def shares_per_contract(cfg: Settings, proxy_price: float, sl_pct: Optional[float] = None) -> float:
    """How many proxy shares represent ONE futures contract of the strategy's size."""
    if proxy_price is None or proxy_price <= 0:
        return cfg.fixed_shares_per_contract
    if cfg.sizing_mode == "fixed_shares":
        return cfg.fixed_shares_per_contract
    if cfg.sizing_mode == "risk":
        if sl_pct and sl_pct > 0:
            return cfg.risk_per_contract_usd / (sl_pct * proxy_price)
        return cfg.fixed_shares_per_contract
    return cfg.notional_per_contract_usd / proxy_price


def target_shares(position_contracts: float, spc: float, max_shares: int) -> int:
    """Signed target share count for a signed contract position, clamped by max."""
    raw = position_contracts * spc
    n = int(math.copysign(math.floor(abs(raw) + 1e-9), raw)) if abs(raw) >= 1 else 0
    if abs(n) > max_shares:
        n = int(math.copysign(max_shares, n))
    return n
