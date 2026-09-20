"""Broker adapters. `Broker` is the protocol the engine drives; swap the adapter
to move from Alpaca paper (equities proxy) to a real futures broker later."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class BrokerOrder:
    id: str
    symbol: str
    side: str                 # buy | sell
    qty: float
    kind: str                 # market | limit | stop | bracket
    status: str = "new"       # new | accepted | filled | canceled | rejected | partially_filled | held
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    filled_qty: float = 0.0
    fill_price: Optional[float] = None
    legs: List["BrokerOrder"] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Clock:
    is_open: bool
    next_open: str = ""
    next_close: str = ""


class Broker(Protocol):
    name: str

    def account(self) -> Dict[str, Any]: ...
    def clock(self) -> Clock: ...
    def latest_price(self, symbol: str) -> Optional[float]: ...
    def position(self, symbol: str) -> float: ...                       # signed shares
    def positions(self) -> List[Dict[str, Any]]: ...
    def open_orders(self, symbol: Optional[str] = None) -> List[BrokerOrder]: ...
    def cancel_orders(self, symbol: Optional[str] = None) -> int: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def submit_market(self, symbol: str, side: str, qty: float, *, extended: bool = False) -> BrokerOrder: ...
    def submit_stop(self, symbol: str, side: str, qty: float, stop_price: float) -> BrokerOrder: ...
    def submit_bracket(self, symbol: str, side: str, qty: float, take_profit: float, stop_loss: float) -> BrokerOrder: ...
    def replace_stop(self, order_id: str, stop_price: float) -> BrokerOrder: ...
    def close_position(self, symbol: str) -> Optional[BrokerOrder]: ...
    def wait_filled(self, order_id: str, timeout: float = 10.0) -> BrokerOrder: ...
    def recent_fills(self, limit: int = 50) -> List[Dict[str, Any]]: ...
