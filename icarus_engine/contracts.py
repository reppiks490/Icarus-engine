"""Continuous-contract roll for the live feed (CME equity-index futures).

TradingView's `NQ1!` is a continuous contract that switches to the next quarterly contract when
the next contract's daily volume exceeds the current one's (help center: "the excess of the daily
volume of the next contract over the daily volume of the current"); in practice the Monday/Tuesday
of expiry week. Yahoo's `NQ=F` instead stays on the expiring contract until the third Friday, then
has no bars that day. So the engine polls the CONTRACT ticker (`NQU26.CME`, `NQZ26.CME`, ...) and
applies the same volume rule once per session; positions are flattened at a roll (a real account
would roll the position at the two contracts' prices - there is no "jump" P&L).
Warm-up history still comes from `NQ=F` (Yahoo's stitched series), which differs from `NQ1!` on
the 4-5 sessions per quarter between the volume roll and expiry - documented in PARITY.md.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

MONTH_CODES = "FGHJKMNQUVXZ"
# symbol -> (root, Yahoo exchange suffix, contract-month cycle)
SPECS: Dict[str, Tuple[str, str, str]] = {
    "NQ": ("NQ", "CME", "HMUZ"), "ES": ("ES", "CME", "HMUZ"), "YM": ("YM", "CBT", "HMUZ"),
}


def third_friday(year: int, month: int) -> date:
    c = calendar.monthcalendar(year, month)
    fridays = [w[calendar.FRIDAY] for w in c if w[calendar.FRIDAY]]
    return date(year, month, fridays[2])


def contract_months(cycle: str, start: date, n: int = 4) -> List[Tuple[int, int]]:
    """(year, month) of the next n contracts in `cycle` whose expiry (3rd Friday) is on/after `start`."""
    out = []
    y, m = start.year, start.month
    while len(out) < n:
        code = MONTH_CODES[m - 1]
        if code in cycle and third_friday(y, m) >= start:
            out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def ticker_for(symbol: str, year: int, month: int) -> str:
    root, exch, _ = SPECS[symbol]
    return f"{root}{MONTH_CODES[month - 1]}{year % 100:02d}.{exch}"


@dataclass
class ContractRoll:
    symbol: str
    today: date
    current: Tuple[int, int] = field(init=False)
    nxt: Tuple[int, int] = field(init=False)
    checked_session: Optional[str] = None
    history: List[str] = field(default_factory=list)

    def __post_init__(self):
        cyc = SPECS[self.symbol][2]
        self.current, self.nxt = contract_months(cyc, self.today, 2)

    @property
    def ticker(self) -> str:
        return ticker_for(self.symbol, *self.current)

    @property
    def next_ticker(self) -> str:
        return ticker_for(self.symbol, *self.nxt)

    def expiry(self) -> date:
        return third_friday(*self.current)

    def advance(self, today: date) -> None:
        """Expiry passed without a volume roll (data gap): move on to the next contract."""
        cyc = SPECS[self.symbol][2]
        self.current, self.nxt = contract_months(cyc, today, 2)

    def decide(self, cur_vol: Optional[float], next_vol: Optional[float]) -> bool:
        """TradingView's rule on the last COMPLETED session's volumes."""
        return bool(cur_vol is not None and next_vol is not None and next_vol > cur_vol)

    def roll(self) -> str:
        cyc = SPECS[self.symbol][2]
        prev = self.ticker
        self.current = self.nxt
        self.nxt = contract_months(cyc, third_friday(*self.current) + timedelta(days=1), 1)[0]
        self.history.append(f"{prev}->{self.ticker}")
        return prev


def last_completed_volume(rows: List[Tuple[int, float, float]], session_open_ts: int) -> Optional[float]:
    """Volume of the last daily row that ended before the current session opened (Yahoo stamps the
    daily bar at 00:00 ET of the trade date; the row for the running session is excluded)."""
    done = [r for r in rows if r[0] < session_open_ts]
    return done[-1][2] if done else None
