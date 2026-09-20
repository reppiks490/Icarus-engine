"""Alpaca paper/live adapter (alpaca-py). Imported lazily so the core stays testable
without the SDK installed.

Notes that shaped this adapter:
  • Alpaca has no futures — NQ signals are mirrored onto an ETF proxy (QQQ/TQQQ).
  • An equity order cannot flip a position long→short in one shot: close first,
    then open. The engine sequences that; this adapter just executes.
  • A position with open sell orders cannot be closed ("insufficient qty available")
    — cancel the symbol's open orders before closing. Done in close_position().
  • Market orders are rejected outside regular hours; extended-hours needs a
    marketable LIMIT with extended_hours=True.
  • Prices ≥ $1 must be whole cents (sub-penny rule).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import BrokerOrder, Clock
from ..mapping import round_price


class AlpacaBroker:
    name = "alpaca"

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        from alpaca.trading.client import TradingClient  # type: ignore
        from alpaca.data.historical import StockHistoricalDataClient  # type: ignore

        if not api_key or not secret_key:
            raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY missing")
        self.paper = paper
        self.tc = TradingClient(api_key, secret_key, paper=paper)
        self.dc = StockHistoricalDataClient(api_key, secret_key)

    # ── helpers ──
    @staticmethod
    def _conv(o: Any) -> BrokerOrder:
        def _f(x: Any) -> Optional[float]:
            try:
                return float(x) if x is not None else None
            except (TypeError, ValueError):
                return None
        side = getattr(getattr(o, "side", None), "value", None) or str(getattr(o, "side", ""))
        kind = getattr(getattr(o, "type", None), "value", None) or str(getattr(o, "type", ""))
        status = getattr(getattr(o, "status", None), "value", None) or str(getattr(o, "status", ""))
        bo = BrokerOrder(
            id=str(getattr(o, "id", "")), symbol=str(getattr(o, "symbol", "")), side=str(side).lower(),
            qty=_f(getattr(o, "qty", 0)) or 0.0, kind=str(kind).lower(), status=str(status).lower(),
            limit_price=_f(getattr(o, "limit_price", None)), stop_price=_f(getattr(o, "stop_price", None)),
            filled_qty=_f(getattr(o, "filled_qty", 0)) or 0.0, fill_price=_f(getattr(o, "filled_avg_price", None)),
        )
        legs = getattr(o, "legs", None) or []
        bo.legs = [AlpacaBroker._conv(l) for l in legs]
        return bo

    # ── Broker protocol ──
    def account(self) -> Dict[str, Any]:
        a = self.tc.get_account()
        return {
            "equity": float(a.equity), "cash": float(a.cash), "buying_power": float(a.buying_power),
            "status": str(getattr(a.status, "value", a.status)), "daytrade_count": getattr(a, "daytrade_count", None),
            "paper": self.paper, "account_number": getattr(a, "account_number", None),
        }

    def clock(self) -> Clock:
        c = self.tc.get_clock()
        return Clock(is_open=bool(c.is_open), next_open=str(c.next_open), next_close=str(c.next_close))

    def latest_price(self, symbol: str) -> Optional[float]:
        from alpaca.data.requests import StockLatestTradeRequest  # type: ignore
        try:
            try:
                from alpaca.data.enums import DataFeed  # type: ignore
                req = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
            except Exception:
                req = StockLatestTradeRequest(symbol_or_symbols=symbol)
            res = self.dc.get_stock_latest_trade(req)
            t = res[symbol] if isinstance(res, dict) else res
            return float(t.price)
        except Exception:
            return None

    def position(self, symbol: str) -> float:
        try:
            p = self.tc.get_open_position(symbol)
        except Exception:
            return 0.0
        q = float(p.qty)
        side = str(getattr(getattr(p, "side", None), "value", getattr(p, "side", "long"))).lower()
        return -abs(q) if side == "short" else abs(q)

    def positions(self) -> List[Dict[str, Any]]:
        out = []
        for p in self.tc.get_all_positions():
            side = str(getattr(getattr(p, "side", None), "value", getattr(p, "side", "long"))).lower()
            q = float(p.qty)
            out.append({
                "symbol": p.symbol, "qty": -abs(q) if side == "short" else abs(q),
                "avg_entry_price": float(p.avg_entry_price), "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl), "current_price": float(getattr(p, "current_price", 0) or 0),
            })
        return out

    def open_orders(self, symbol: Optional[str] = None) -> List[BrokerOrder]:
        from alpaca.trading.requests import GetOrdersRequest  # type: ignore
        from alpaca.trading.enums import QueryOrderStatus  # type: ignore
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol] if symbol else None, nested=True)
        return [self._conv(o) for o in self.tc.get_orders(filter=req)]

    def cancel_orders(self, symbol: Optional[str] = None) -> int:
        if symbol is None:
            res = self.tc.cancel_orders()
            return len(res or [])
        n = 0
        for o in self.open_orders(symbol):
            try:
                self.tc.cancel_order_by_id(o.id); n += 1
            except Exception:
                pass
        return n

    def cancel_order(self, order_id: str) -> bool:
        try:
            self.tc.cancel_order_by_id(order_id)
            return True
        except Exception:
            return False

    def submit_market(self, symbol: str, side: str, qty: float, *, extended: bool = False) -> BrokerOrder:
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest  # type: ignore
        from alpaca.trading.enums import OrderSide, TimeInForce  # type: ignore
        s = OrderSide.BUY if side == "buy" else OrderSide.SELL
        if extended:
            # marketable limit ±0.3% — the only order type allowed outside RTH
            last = self.latest_price(symbol)
            if last is None:
                raise RuntimeError("no quote for extended-hours limit")
            px = round_price(last * (1.003 if side == "buy" else 0.997))
            req = LimitOrderRequest(symbol=symbol, qty=int(qty), side=s, time_in_force=TimeInForce.DAY,
                                    limit_price=px, extended_hours=True)
        else:
            req = MarketOrderRequest(symbol=symbol, qty=int(qty), side=s, time_in_force=TimeInForce.DAY)
        return self._conv(self.tc.submit_order(order_data=req))

    def submit_stop(self, symbol: str, side: str, qty: float, stop_price: float) -> BrokerOrder:
        from alpaca.trading.requests import StopOrderRequest  # type: ignore
        from alpaca.trading.enums import OrderSide, TimeInForce  # type: ignore
        s = OrderSide.BUY if side == "buy" else OrderSide.SELL
        req = StopOrderRequest(symbol=symbol, qty=int(qty), side=s, time_in_force=TimeInForce.GTC,
                               stop_price=round_price(stop_price))
        return self._conv(self.tc.submit_order(order_data=req))

    def submit_bracket(self, symbol: str, side: str, qty: float, take_profit: float, stop_loss: float) -> BrokerOrder:
        from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest  # type: ignore
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass  # type: ignore
        s = OrderSide.BUY if side == "buy" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=symbol, qty=int(qty), side=s, time_in_force=TimeInForce.GTC, order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round_price(take_profit)),
            stop_loss=StopLossRequest(stop_price=round_price(stop_loss)),
        )
        return self._conv(self.tc.submit_order(order_data=req))

    def replace_stop(self, order_id: str, stop_price: float) -> BrokerOrder:
        from alpaca.trading.requests import ReplaceOrderRequest  # type: ignore
        req = ReplaceOrderRequest(stop_price=round_price(stop_price))
        return self._conv(self.tc.replace_order_by_id(order_id, order_data=req))

    def close_position(self, symbol: str) -> Optional[BrokerOrder]:
        q = self.position(symbol)
        if abs(q) < 1e-9:
            return None
        self.cancel_orders(symbol)   # shares held by open exits would block the close
        time.sleep(0.3)
        try:
            o = self.tc.close_position(symbol)
            return self._conv(o)
        except Exception:
            # fall back to an explicit market order
            return self.submit_market(symbol, "sell" if q > 0 else "buy", abs(q))

    def wait_filled(self, order_id: str, timeout: float = 10.0) -> BrokerOrder:
        deadline = time.time() + timeout
        last: Optional[BrokerOrder] = None
        while time.time() < deadline:
            try:
                last = self._conv(self.tc.get_order_by_id(order_id))
                if last.status in ("filled", "canceled", "rejected", "expired"):
                    return last
            except Exception:
                pass
            time.sleep(0.5)
        return last or BrokerOrder(id=order_id, symbol="", side="", qty=0, kind="", status="unknown")

    def recent_fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        from alpaca.trading.requests import GetOrdersRequest  # type: ignore
        from alpaca.trading.enums import QueryOrderStatus  # type: ignore
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=int(limit), nested=True)
        out = []
        for o in self.tc.get_orders(filter=req):
            bo = self._conv(o)
            if bo.status == "filled":
                out.append({"id": bo.id, "symbol": bo.symbol, "side": bo.side, "qty": bo.filled_qty or bo.qty,
                            "price": bo.fill_price, "kind": bo.kind, "ts": str(getattr(o, "filled_at", ""))})
        return out
