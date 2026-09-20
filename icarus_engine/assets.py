"""Asset registry: what each symbol is, where its bars come from, how it is aligned and sized.

Contract specs are CME's (tick size, $ per point). `multiplier` is the emulator's
contract_size: P&L = points × multiplier × contracts, exactly as TradingView
computes it for the futures symbol.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Dict, Optional


@dataclass
class AssetSpec:
    symbol: str                      # short name used everywhere (NQ, ES, BTC ...)
    name: str
    feed: str                        # yahoo | coinbase
    ticker: str                      # feed symbol (NQ=F, BTC-USD)
    calendar: str                    # cme | crypto
    mintick: float
    multiplier: float                # $ per 1.0 price point per contract (contract_size)
    kind: str = "futures"            # futures | crypto
    tv_symbol: str = ""              # TradingView symbol, for parity exports
    chart_tf: str = "20"
    preset: Optional[str] = None     # inputs preset name (presets/<name>.json)
    chart_type: str = "real"         # real | heikin_ashi  (what the STRATEGY sees)
    fill_on: str = "real"            # real | chart        (what the EMULATOR fills on; chart = TradingView "Heikin Ashi bars")
    slippage_ticks: int = 0
    capital: float = 500000.0
    commission: float = 2.0
    anchor_et: Optional[str] = None  # intraday bar anchor override (ET "HHMM"); derived from `session` when None
    session: str = "rth"             # rth | eth  - TradingView chart session for CME futures (see calendar.CMECalendar)
    group: str = "equity"            # holiday schedule: equity | metals | crypto (CME Bitcoin futures follow equity)
    security_source: str = "chart"   # chart | standard - what request.security() sees on a Heikin Ashi chart (chart = HA, TradingView)
    roll: str = "volume"             # volume | none - continuous-contract roll rule for the live feed (TradingView 1! = volume)


REGISTRY: Dict[str, AssetSpec] = {
    "NQ": AssetSpec("NQ", "Nasdaq 100 E-mini", "yahoo", "NQ=F", "cme", 0.25, 20.0, tv_symbol="CME_MINI:NQ1!"),
    "ES": AssetSpec("ES", "S&P 500 E-mini", "yahoo", "ES=F", "cme", 0.25, 50.0, tv_symbol="CME_MINI:ES1!"),
    "YM": AssetSpec("YM", "Dow E-mini", "yahoo", "YM=F", "cme", 1.0, 5.0, tv_symbol="CBOT_MINI:YM1!"),
    "GC": AssetSpec("GC", "Gold", "yahoo", "GC=F", "cme", 0.10, 100.0, tv_symbol="COMEX:GC1!", group="metals", roll="none"),
    "SI": AssetSpec("SI", "Silver", "yahoo", "SI=F", "cme", 0.005, 5000.0, tv_symbol="COMEX:SI1!", group="metals", roll="none"),
    "PL": AssetSpec("PL", "Platinum", "yahoo", "PL=F", "cme", 0.10, 50.0, tv_symbol="NYMEX:PL1!", group="metals", roll="none"),
    "PA": AssetSpec("PA", "Palladium", "yahoo", "PA=F", "cme", 0.10, 100.0, tv_symbol="NYMEX:PA1!", group="metals", roll="none"),
    "BTCF": AssetSpec("BTCF", "Bitcoin futures (CME)", "yahoo", "BTC=F", "cme_crypto", 5.0, 5.0, tv_symbol="CME:BTC1!", group="crypto", roll="none", session="eth"),
    "MBT": AssetSpec("MBT", "Micro Bitcoin futures (CME)", "yahoo", "MBT=F", "cme_crypto", 5.0, 0.1, tv_symbol="CME:MBT1!", group="crypto", roll="none", session="eth"),
    "BTC": AssetSpec("BTC", "Bitcoin spot (Coinbase)", "coinbase", "BTC-USD", "crypto", 0.01, 1.0, kind="crypto", tv_symbol="COINBASE:BTCUSD"),
    "ETH": AssetSpec("ETH", "Ether spot (Coinbase)", "coinbase", "ETH-USD", "crypto", 0.01, 1.0, kind="crypto", tv_symbol="COINBASE:ETHUSD"),
    "SOL": AssetSpec("SOL", "Solana spot (Coinbase)", "coinbase", "SOL-USD", "crypto", 0.01, 1.0, kind="crypto", tv_symbol="COINBASE:SOLUSD"),
}
ALIASES = {"NQ1!": "NQ", "MNQ": "NQ", "ES1!": "ES", "YM1!": "YM", "GC1!": "GC", "GOLD": "GC", "SI1!": "SI", "SILVER": "SI",
           "PL1!": "PL", "PLATINUM": "PL", "PA1!": "PA", "PALLADIUM": "PA", "BTC=F": "BTCF", "BTC1!": "BTCF", "BTCUSD": "BTC", "BTC-USD": "BTC",
           "NASDAQ": "NQ", "SP500": "ES", "DOW": "YM"}


_SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9=!.\-]{0,15}")


def resolve(symbol: str) -> AssetSpec:
    s = symbol.strip().upper().split(":")[-1]
    s = ALIASES.get(s, s)
    if s in REGISTRY:
        return replace(REGISTRY[s])
    if not _SYMBOL_RE.fullmatch(s):
        raise ValueError(f"bad symbol {symbol!r}: letters, digits, '-', '.', '=' and '!' only")
    # unknown → assume a Coinbase spot pair (keyless), 24/7
    base = s.replace("-USD", "").replace("USD", "")
    if not re.fullmatch(r"[A-Z0-9]{1,12}", base):
        raise ValueError(f"bad symbol {symbol!r}")
    return AssetSpec(base, f"{base} spot (Coinbase)", "coinbase", f"{base}-USD", "crypto", 0.01, 1.0, kind="crypto", tv_symbol=f"COINBASE:{base}USD")


def parse_spec(token: str, default_tf: str = "20") -> AssetSpec:
    """'NQ', 'NQ@20', 'GC@10:NQ-10m-original' → AssetSpec with tf / preset."""
    tf, preset = default_tf, None
    sym = token.strip()
    if ":" in sym and not sym.upper().startswith(("CME", "COMEX", "NYMEX", "COINBASE", "CBOT")):
        sym, preset = sym.split(":", 1)
    if "@" in sym:
        sym, tf = sym.split("@", 1)
    spec = resolve(sym)
    spec.chart_tf = tf
    spec.preset = preset
    return spec
