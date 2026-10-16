"""Asset registry: contract identity, bar source, alignment and P&L sizing.

`multiplier` is the emulator contract size: P&L = price points × multiplier ×
contracts. Futures and their micro counterparts are intentionally separate
AssetSpec objects; a micro must never alias to the parent contract because that
would corrupt P&L, risk sizing and broker reconciliation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Dict, Optional


@dataclass
class AssetSpec:
    symbol: str
    name: str
    feed: str                        # yahoo | coinbase
    ticker: str                      # source symbol (NQ=F, BTC-USD)
    calendar: str                    # cme | cme_crypto | crypto
    mintick: float
    multiplier: float                # $ / quote-currency units per 1.0 price point per contract
    kind: str = "futures"            # futures | crypto
    tv_symbol: str = ""
    chart_tf: str = "20"
    preset: Optional[str] = None
    chart_type: str = "real"
    fill_on: str = "real"
    slippage_ticks: int = 0
    capital: float = 500000.0
    commission: float = 2.0
    anchor_et: Optional[str] = None
    session: str = "rth"             # rth | eth
    group: str = "equity"            # existing CME holiday-calendar group
    security_source: str = "chart"
    roll: str = "volume"
    exchange: str = ""
    asset_class: str = ""
    micro_of: Optional[str] = None
    feed_mode: str = ""              # capability, not a claim that the provider is reachable right now


def _future(
    symbol: str,
    name: str,
    ticker: str,
    mintick: float,
    multiplier: float,
    tv_symbol: str,
    *,
    exchange: str,
    asset_class: str,
    micro_of: Optional[str] = None,
    session: str = "rth",
    group: str = "equity",
    roll: str = "volume",
    calendar: str = "cme",
) -> AssetSpec:
    return AssetSpec(
        symbol, name, "yahoo", ticker, calendar, mintick, multiplier,
        tv_symbol=tv_symbol, session=session, group=group, roll=roll,
        exchange=exchange, asset_class=asset_class, micro_of=micro_of,
        feed_mode="public_delayed",
    )


REGISTRY: Dict[str, AssetSpec] = {
    # Equity index futures. Existing strategy defaults stay RTH for parity.
    "NQ": _future("NQ", "Nasdaq 100 E-mini", "NQ=F", 0.25, 20.0, "CME_MINI:NQ1!", exchange="CME", asset_class="equity_index"),
    "MNQ": _future("MNQ", "Micro E-mini Nasdaq 100", "MNQ=F", 0.25, 2.0, "CME_MINI:MNQ1!", exchange="CME", asset_class="equity_index", micro_of="NQ"),
    "ES": _future("ES", "S&P 500 E-mini", "ES=F", 0.25, 50.0, "CME_MINI:ES1!", exchange="CME", asset_class="equity_index"),
    "MES": _future("MES", "Micro E-mini S&P 500", "MES=F", 0.25, 5.0, "CME_MINI:MES1!", exchange="CME", asset_class="equity_index", micro_of="ES"),
    "YM": _future("YM", "Dow E-mini", "YM=F", 1.0, 5.0, "CBOT_MINI:YM1!", exchange="CBOT", asset_class="equity_index"),
    "MYM": _future("MYM", "Micro E-mini Dow", "MYM=F", 1.0, 0.5, "CBOT_MINI:MYM1!", exchange="CBOT", asset_class="equity_index", micro_of="YM"),
    "RTY": _future("RTY", "E-mini Russell 2000", "RTY=F", 0.10, 50.0, "CME_MINI:RTY1!", exchange="CME", asset_class="equity_index"),
    "M2K": _future("M2K", "Micro E-mini Russell 2000", "M2K=F", 0.10, 5.0, "CME_MINI:M2K1!", exchange="CME", asset_class="equity_index", micro_of="RTY"),

    # Metals. GC/SI and their repaired micro identities retain existing RTH parity;
    # the newly added copper lane uses the full ETH session.
    "GC": _future("GC", "Gold", "GC=F", 0.10, 100.0, "COMEX:GC1!", exchange="COMEX", asset_class="metal", group="metals", roll="none"),
    "MGC": _future("MGC", "Micro Gold", "MGC=F", 0.10, 10.0, "COMEX:MGC1!", exchange="COMEX", asset_class="metal", micro_of="GC", group="metals", roll="none"),
    "SI": _future("SI", "Silver", "SI=F", 0.005, 5000.0, "COMEX:SI1!", exchange="COMEX", asset_class="metal", group="metals", roll="none"),
    "SIL": _future("SIL", "Micro Silver", "SIL=F", 0.005, 1000.0, "COMEX:SIL1!", exchange="COMEX", asset_class="metal", micro_of="SI", group="metals", roll="none"),
    "PL": _future("PL", "Platinum", "PL=F", 0.10, 50.0, "NYMEX:PL1!", exchange="NYMEX", asset_class="metal", group="metals", roll="none"),
    "PA": _future("PA", "Palladium", "PA=F", 0.10, 100.0, "NYMEX:PA1!", exchange="NYMEX", asset_class="metal", group="metals", roll="none"),
    "HG": _future("HG", "Copper", "HG=F", 0.0005, 25000.0, "COMEX:HG1!", exchange="COMEX", asset_class="metal", session="eth", group="metals", roll="none"),
    "MHG": _future("MHG", "Micro Copper", "MHG=F", 0.0005, 2500.0, "COMEX:MHG1!", exchange="COMEX", asset_class="metal", micro_of="HG", session="eth", group="metals", roll="none"),

    # Energy: full Globex/ETH coverage avoids applying the equity RTH clock.
    "CL": _future("CL", "WTI Crude Oil", "CL=F", 0.01, 1000.0, "NYMEX:CL1!", exchange="NYMEX", asset_class="energy", session="eth", roll="none"),
    "MCL": _future("MCL", "Micro WTI Crude Oil", "MCL=F", 0.01, 100.0, "NYMEX:MCL1!", exchange="NYMEX", asset_class="energy", micro_of="CL", session="eth", roll="none"),
    "NG": _future("NG", "Henry Hub Natural Gas", "NG=F", 0.001, 10000.0, "NYMEX:NG1!", exchange="NYMEX", asset_class="energy", session="eth", roll="none"),
    "MNG": _future("MNG", "Micro Henry Hub Natural Gas", "MNG=F", 0.001, 1000.0, "NYMEX:MNG1!", exchange="NYMEX", asset_class="energy", micro_of="NG", session="eth", roll="none"),

    # Major FX futures + current CME micro roots. Price is USD per unit except JPY's
    # standard quote convention; multiplier remains the contract currency amount.
    "6E": _future("6E", "Euro FX", "6E=F", 0.00005, 125000.0, "CME:6E1!", exchange="CME", asset_class="fx", session="eth"),
    "M6E": _future("M6E", "Micro EUR/USD", "M6E=F", 0.0001, 12500.0, "CME:M6E1!", exchange="CME", asset_class="fx", micro_of="6E", session="eth"),
    "6J": _future("6J", "Japanese Yen", "6J=F", 0.0000005, 12500000.0, "CME:6J1!", exchange="CME", asset_class="fx", session="eth"),
    "MJY": _future("MJY", "Micro JPY/USD", "MJY=F", 0.000001, 1250000.0, "CME:MJY1!", exchange="CME", asset_class="fx", micro_of="6J", session="eth"),
    "6B": _future("6B", "British Pound", "6B=F", 0.0001, 62500.0, "CME:6B1!", exchange="CME", asset_class="fx", session="eth"),
    "M6B": _future("M6B", "Micro GBP/USD", "M6B=F", 0.0001, 6250.0, "CME:M6B1!", exchange="CME", asset_class="fx", micro_of="6B", session="eth"),
    "6A": _future("6A", "Australian Dollar", "6A=F", 0.00005, 100000.0, "CME:6A1!", exchange="CME", asset_class="fx", session="eth"),
    "M6A": _future("M6A", "Micro AUD/USD", "M6A=F", 0.0001, 10000.0, "CME:M6A1!", exchange="CME", asset_class="fx", micro_of="6A", session="eth"),

    # Treasury price futures. Both use a $1,000 value per full price point.
    "ZN": _future("ZN", "10-Year T-Note", "ZN=F", 0.015625, 1000.0, "CBOT:ZN1!", exchange="CBOT", asset_class="rates", session="eth"),
    "ZB": _future("ZB", "30-Year U.S. Treasury Bond", "ZB=F", 0.03125, 1000.0, "CBOT:ZB1!", exchange="CBOT", asset_class="rates", session="eth"),

    # CME crypto futures retained as existing research surfaces.
    "BTCF": _future("BTCF", "Bitcoin futures (CME)", "BTC=F", 5.0, 5.0, "CME:BTC1!", exchange="CME", asset_class="crypto_futures", session="eth", group="crypto", roll="none", calendar="cme_crypto"),
    "MBT": _future("MBT", "Micro Bitcoin futures (CME)", "MBT=F", 5.0, 0.1, "CME:MBT1!", exchange="CME", asset_class="crypto_futures", micro_of="BTCF", session="eth", group="crypto", roll="none", calendar="cme_crypto"),

    # Spot crypto remains a separate kind/feed.
    "BTC": AssetSpec("BTC", "Bitcoin spot (Coinbase)", "coinbase", "BTC-USD", "crypto", 0.01, 1.0, kind="crypto", tv_symbol="COINBASE:BTCUSD", exchange="COINBASE", asset_class="crypto_spot", feed_mode="public_realtime"),
    "ETH": AssetSpec("ETH", "Ether spot (Coinbase)", "coinbase", "ETH-USD", "crypto", 0.01, 1.0, kind="crypto", tv_symbol="COINBASE:ETHUSD", exchange="COINBASE", asset_class="crypto_spot", feed_mode="public_realtime"),
    "SOL": AssetSpec("SOL", "Solana spot (Coinbase)", "coinbase", "SOL-USD", "crypto", 0.01, 1.0, kind="crypto", tv_symbol="COINBASE:SOLUSD", exchange="COINBASE", asset_class="crypto_spot", feed_mode="public_realtime"),
}


ALIASES = {
    "NQ1!": "NQ", "ES1!": "ES", "YM1!": "YM", "RTY1!": "RTY",
    "GC1!": "GC", "GOLD": "GC", "SI1!": "SI", "SILVER": "SI",
    "PL1!": "PL", "PLATINUM": "PL", "PA1!": "PA", "PALLADIUM": "PA",
    "BTC=F": "BTCF", "BTC1!": "BTCF", "BTCUSD": "BTC", "BTC-USD": "BTC",
    "NASDAQ": "NQ", "SP500": "ES", "DOW": "YM", "RUSSELL2000": "RTY",
}
# Every first-class futures identity accepts its own continuous-style short alias
# and Yahoo source symbol. Explicit entries above win for special names (BTC1!).
for _symbol, _spec in REGISTRY.items():
    if _spec.kind == "futures":
        ALIASES.setdefault(f"{_symbol}1!", _symbol)
        if _spec.ticker.endswith("=F"):
            ALIASES.setdefault(_spec.ticker, _symbol)


_SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9=!.\-]{0,15}")


def resolve(symbol: str) -> AssetSpec:
    s = symbol.strip().upper().split(":")[-1]
    s = ALIASES.get(s, s)
    if s in REGISTRY:
        return replace(REGISTRY[s])
    if not _SYMBOL_RE.fullmatch(s):
        raise ValueError(f"bad symbol {symbol!r}: letters, digits, '-', '.', '=' and '!' only")
    # Backward-compatible convenience: unknown symbols remain Coinbase spot pairs.
    # Known futures and all supported micro roots are resolved above before this path.
    base = s.replace("-USD", "").replace("USD", "")
    if not re.fullmatch(r"[A-Z0-9]{1,12}", base):
        raise ValueError(f"bad symbol {symbol!r}")
    return AssetSpec(
        base, f"{base} spot (Coinbase)", "coinbase", f"{base}-USD", "crypto", 0.01, 1.0,
        kind="crypto", tv_symbol=f"COINBASE:{base}USD", exchange="COINBASE",
        asset_class="crypto_spot", feed_mode="public_realtime",
    )


def parse_spec(token: str, default_tf: str = "20") -> AssetSpec:
    """'NQ', 'NQ@20', 'GC@10:NQ-10m-original' → AssetSpec with tf / preset."""
    tf, preset = default_tf, None
    sym = token.strip()
    if ":" in sym and not sym.upper().startswith(("CME", "CME_MINI", "COMEX", "NYMEX", "COINBASE", "CBOT", "CBOT_MINI")):
        sym, preset = sym.split(":", 1)
    if "@" in sym:
        sym, tf = sym.split("@", 1)
    spec = resolve(sym)
    spec.chart_tf = tf
    spec.preset = preset
    return spec
