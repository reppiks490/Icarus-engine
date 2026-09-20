"""TradingView broker-emulator semantics, in Python.

Reproduces the parts of `strategy.*` the ICARUS script relies on, with the
same fill rules TradingView applies when Bar Magnifier is OFF and
process_orders_on_close = false:

  * strategy.entry / strategy.close market orders placed on bar N fill at the
    OPEN of bar N+1 (slippage 0).
  * strategy.exit brackets are attached to an entry and go live the moment the
    entry fills; `profit=`/`loss=` are tick distances from the actual fill,
    `limit=`/`stop=` are absolute prices. Each exit id is a one-cancels-other
    pair for its quantity; re-issuing an exit id replaces it.
  * Inside a bar the emulator assumes the price path
        open -> high -> low -> close   when the open is closer to the high
        open -> low  -> high -> close  otherwise
    and fills resting limits/stops in the order that path reaches them. A
    level already breached at the open fills at the open (gap-through).
  * An entry in the opposite direction reverses: every open trade is closed
    at that fill, then the new trade opens (Pine nets positions).
  * pyramiding caps the number of same-direction open trades.
  * Partial exits split a trade into closed pieces, each its own closedtrade
    with the parent entry's id / bar / price (what strategy.closedtrades.* reads).
  * commission_type = cash_per_contract charges `commission` per contract on
    every fill (entry and exit).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .pine.timeframe import Bar


@dataclass
class OpenTrade:
    entry_id: str
    direction: int              # +1 long, -1 short
    qty: int                    # remaining contracts
    qty_orig: int
    entry_price: float
    entry_bar: int
    entry_ts: int
    entry_comment: str = ""
    seq: int = 0
    best: float = 0.0           # most favourable price seen since the fill (excursion tracking)
    worst: float = 0.0          # least favourable price seen since the fill

    def touch(self, px: float) -> None:
        if self.direction > 0:
            self.best = max(self.best, px); self.worst = min(self.worst, px)
        else:
            self.best = min(self.best, px); self.worst = max(self.worst, px)


@dataclass
class ClosedTrade:
    entry_id: str
    direction: int
    qty: int
    entry_price: float
    entry_bar: int
    entry_ts: int
    exit_price: float
    exit_bar: int
    exit_ts: int
    exit_comment: str
    profit: float               # net of commission (Pine strategy.closedtrades.profit)
    entry_comment: str = ""
    exit_kind: str = ""          # tp | sl | close | reverse
    runup: float = 0.0           # TradingView "Favorable excursion": best gross excursion up to the exit fill, less the entry commission
    drawdown: float = 0.0        # TradingView "Adverse excursion": worst gross excursion (<= 0) less the entry commission
    bars: int = 0                # TradingView "Duration (bars)": exit bar - entry bar


@dataclass
class PendingEntry:
    id: str
    direction: int
    qty: int
    limit: Optional[float]
    comment: str
    alert_message: str
    placed_bar: int
    seq: int


@dataclass
class ExitOrder:
    id: str
    from_entry: str
    qty: Optional[int]
    profit_ticks: Optional[float]
    loss_ticks: Optional[float]
    limit: Optional[float]
    stop: Optional[float]
    comment_profit: str
    comment_loss: str
    seq: int
    # resolved when live:
    live: bool = False
    limit_px: Optional[float] = None
    stop_px: Optional[float] = None
    filled: int = 0


@dataclass
class PendingClose:
    entry_id: str
    comment: str
    seq: int


@dataclass
class Fill:
    ts: int
    bar: int
    entry_id: str
    side: str                   # buy | sell
    qty: int
    price: float
    kind: str                   # entry | exit | close | reverse
    comment: str
    profit: Optional[float] = None
    position_after: int = 0     # signed contracts after this fill


class Emulator:
    def __init__(self, initial_capital: float = 500000.0, commission: float = 2.0, mintick: float = 0.01,
                 contract_size: float = 1.0, pyramiding: int = 2, slippage_ticks: int = 0):
        self.initial_capital = float(initial_capital)
        self.slippage_ticks = int(slippage_ticks)            # TradingView Properties -> Slippage: market and stop fills, never limits
        self.commission = float(commission)
        self.mintick = float(mintick)
        self.contract_size = float(contract_size)
        self.pyramiding = int(pyramiding)
        self.open: List[OpenTrade] = []
        self.closed: List[ClosedTrade] = []
        self.fills: List[Fill] = []
        self.netprofit = 0.0
        self._pending_entries: List[PendingEntry] = []
        self._pending_closes: List[PendingClose] = []
        self._exits: Dict[str, ExitOrder] = {}          # exit id -> order (attached or live)
        self._seq = 0
        self.bar_index = -1
        self.last_bar: Optional[Bar] = None

    # ── helpers ──
    def _nseq(self) -> int:
        self._seq += 1
        return self._seq

    def round_tick(self, px: float) -> float:
        t = self.mintick
        return round(round(px / t) * t, 10) if t > 0 else px

    def _slip(self, px: float, side_dir: int) -> float:
        """Adverse slippage for a fill that BUYS (side_dir +1) or SELLS (-1) at market/stop."""
        return px + side_dir * self.slippage_ticks * self.mintick if self.slippage_ticks else px

    @property
    def position_size(self) -> int:
        return sum(t.direction * t.qty for t in self.open)

    def qty_open(self, entry_id: str) -> int:
        return sum(t.qty for t in self.open if t.entry_id == entry_id)

    def open_profit(self, mark: float) -> float:
        return sum(t.direction * (mark - t.entry_price) * t.qty * self.contract_size for t in self.open)

    def equity(self, mark: Optional[float] = None) -> float:
        m = mark if mark is not None else (self.last_bar.c if self.last_bar else None)
        entry_fees = self.commission * sum(t.qty for t in self.open)
        return self.initial_capital + self.netprofit - entry_fees + (self.open_profit(m) if m is not None else 0.0)

    # ── script API (effective from the next bar) ──
    def entry(self, id: str, direction: int, qty: int, limit: Optional[float] = None, comment: str = "",
              alert_message: str = "") -> None:
        self._pending_entries = [p for p in self._pending_entries if p.id != id]
        self._pending_entries.append(PendingEntry(id, int(direction), int(qty), limit, comment, alert_message,
                                                  self.bar_index, self._nseq()))

    def exit(self, id: str, from_entry: str, qty: Optional[int] = None, profit: Optional[float] = None,
             loss: Optional[float] = None, limit: Optional[float] = None, stop: Optional[float] = None,
             comment_profit: str = "", comment_loss: str = "") -> None:
        ex = ExitOrder(id, from_entry, (int(qty) if qty is not None else None), profit, loss, limit, stop,
                       comment_profit, comment_loss, self._nseq())
        # an entry already open → resolve levels now (live from next bar); else attach until the entry fills
        if self.qty_open(from_entry) > 0:
            self._resolve_exit(ex, self._avg_price(from_entry), self._dir(from_entry))
        self._exits[id] = ex

    def close(self, entry_id: str, comment: str = "") -> None:
        if self.qty_open(entry_id) > 0 or any(p.id == entry_id for p in self._pending_entries):
            self._pending_closes = [c for c in self._pending_closes if c.entry_id != entry_id]
            self._pending_closes.append(PendingClose(entry_id, comment, self._nseq()))

    def cancel(self, id: str) -> None:
        self._pending_entries = [p for p in self._pending_entries if p.id != id]
        self._exits.pop(id, None)

    # ── internals ──
    def _avg_price(self, entry_id: str) -> float:
        ts = [t for t in self.open if t.entry_id == entry_id]
        q = sum(t.qty for t in ts)
        return sum(t.entry_price * t.qty for t in ts) / q if q else 0.0

    def _dir(self, entry_id: str) -> int:
        for t in self.open:
            if t.entry_id == entry_id:
                return t.direction
        return 0

    def _resolve_exit(self, ex: ExitOrder, fill: float, direction: int) -> None:
        ex.live = True
        ex.limit_px = None
        ex.stop_px = None
        if ex.limit is not None:
            ex.limit_px = self.round_tick(ex.limit)
        elif ex.profit_ticks is not None:
            ex.limit_px = self.round_tick(fill + direction * round(ex.profit_ticks) * self.mintick)
        if ex.stop is not None:
            ex.stop_px = self.round_tick(ex.stop)
        elif ex.loss_ticks is not None:
            ex.stop_px = self.round_tick(fill - direction * round(ex.loss_ticks) * self.mintick)

    def _record_fill(self, bar: Bar, entry_id: str, side: str, qty: int, price: float, kind: str, comment: str,
                     profit: Optional[float] = None) -> None:
        self.fills.append(Fill(bar.ts, self.bar_index, entry_id, side, qty, price, kind, comment, profit,
                               self.position_size))

    def _close_trade_qty(self, t: OpenTrade, qty: int, price: float, bar: Bar, comment: str, kind: str) -> float:
        qty = min(qty, t.qty)
        t.touch(price)                                        # the trade travelled to the exit price on this bar
        gross = t.direction * (price - t.entry_price) * qty * self.contract_size
        comm = self.commission * qty * 2.0
        profit = gross - comm
        runup = max(0.0, t.direction * (t.best - t.entry_price) * qty * self.contract_size - self.commission * qty)
        ddown = min(0.0, t.direction * (t.worst - t.entry_price)) * qty * self.contract_size - self.commission * qty
        self.closed.append(ClosedTrade(t.entry_id, t.direction, qty, t.entry_price, t.entry_bar, t.entry_ts,
                                       price, self.bar_index, bar.ts, comment, profit, t.entry_comment, kind,
                                       runup, ddown, self.bar_index - t.entry_bar))
        self.netprofit += profit
        t.qty -= qty
        if t.qty <= 0:
            self.open.remove(t)
        self._record_fill(bar, t.entry_id, "sell" if t.direction > 0 else "buy", qty, price, kind, comment, profit)
        # exits of a fully closed entry die with it
        if self.qty_open(t.entry_id) == 0:
            for eid in [k for k, v in self._exits.items() if v.from_entry == t.entry_id]:
                self._exits.pop(eid, None)
        return profit

    def _close_all(self, price: float, bar: Bar, comment: str, kind: str) -> None:
        for t in list(self.open):
            self._close_trade_qty(t, t.qty, price, bar, comment, kind)

    def _open_trade(self, p: PendingEntry, price: float, bar: Bar) -> None:
        t = OpenTrade(p.id, p.direction, p.qty, p.qty, price, self.bar_index, bar.ts, p.comment, self._nseq(), best=price, worst=price)
        self.open.append(t)
        self._record_fill(bar, p.id, "buy" if p.direction > 0 else "sell", p.qty, price, "entry", p.comment or p.id)
        # attached exits go live from this fill (same bar included)
        for ex in self._exits.values():
            if ex.from_entry == p.id and not ex.live:
                self._resolve_exit(ex, price, p.direction)

    def _fill_entry(self, p: PendingEntry, price: float, bar: Bar) -> bool:
        pos = self.position_size
        if pos != 0 and (pos > 0) != (p.direction > 0):
            self._close_all(price, bar, p.comment or p.id, "reverse")
        elif len([t for t in self.open if t.direction == p.direction]) >= self.pyramiding:
            return False                                     # pyramiding limit → order ignored
        self._open_trade(p, price, bar)
        return True

    # ── bar processing (call BEFORE evaluating the script on this bar) ──
    def process_bar(self, bar: Bar, bar_index: int) -> None:
        self.bar_index = bar_index
        self.last_bar = bar
        o, h, l, c = bar.o, bar.h, bar.l, bar.c

        # 1) market orders at the open, in submission order
        market = [("entry", p) for p in self._pending_entries if p.limit is None] + [("close", q) for q in self._pending_closes]
        market.sort(key=lambda x: x[1].seq)
        for kind, obj in market:
            if kind == "entry":
                self._fill_entry(obj, self._slip(o, obj.direction), bar)
                self._pending_entries.remove(obj)
            else:
                left = self.qty_open(obj.entry_id)             # strategy.close(id): the id's size, filled FIFO like every exit
                for t in sorted(list(self.open), key=lambda t: t.seq):
                    if left <= 0:
                        break
                    q = min(left, t.qty)
                    self._close_trade_qty(t, q, self._slip(o, -t.direction), bar, obj.comment, "close")
                    left -= q
                self._pending_entries = [p for p in self._pending_entries if p.id != obj.entry_id]
        self._pending_closes = []

        # 2) resting orders along the intrabar path
        if abs(h - o) <= abs(o - l):
            legs = [(o, h), (h, l), (l, c)]
        else:
            legs = [(o, l), (l, h), (h, c)]
        first = True
        for a, b in legs:
            for t in self.open:
                t.touch(a)
            self._walk_leg(a, b, first, bar)
            for t in self.open:                               # trades that survived the leg saw its end point
                t.touch(b)
            first = False

    def _walk_leg(self, a: float, b: float, first: bool, bar: Bar) -> None:
        up = b >= a
        progress = True
        guard = 0
        while progress and guard < 64:
            progress = False
            guard += 1
            cands = []                                        # (distance_from_a, seq, kind, obj, level)
            # pending limit entries
            for p in self._pending_entries:
                if p.limit is None:
                    continue
                lvl = self.round_tick(p.limit)
                hit = (p.direction > 0 and ((a <= lvl) or (not up and b <= lvl <= a))) or \
                      (p.direction < 0 and ((a >= lvl) or (up and a <= lvl <= b)))
                if hit:
                    px = a if ((p.direction > 0 and a <= lvl) or (p.direction < 0 and a >= lvl)) else lvl
                    cands.append((abs(px - a), p.seq, "lentry", p, px))
            # live exits
            for ex in self._exits.values():
                if not ex.live:
                    continue
                d = self._dir(ex.from_entry)
                if d == 0:
                    continue
                if ex.limit_px is not None:
                    lvl = ex.limit_px
                    hit = (d > 0 and ((a >= lvl) or (up and a <= lvl <= b))) or \
                          (d < 0 and ((a <= lvl) or (not up and b <= lvl <= a)))
                    if hit:
                        px = a if ((d > 0 and a >= lvl) or (d < 0 and a <= lvl)) else lvl
                        cands.append((abs(px - a), ex.seq, "tp", ex, px))
                if ex.stop_px is not None:
                    lvl = ex.stop_px
                    hit = (d > 0 and ((a <= lvl) or (not up and b <= lvl <= a))) or \
                          (d < 0 and ((a >= lvl) or (up and a <= lvl <= b)))
                    if hit:
                        px = a if ((d > 0 and a <= lvl) or (d < 0 and a >= lvl)) else lvl
                        cands.append((abs(px - a), ex.seq, "sl", ex, px))
            if not cands:
                return
            cands.sort(key=lambda x: (x[0], x[1]))
            _, _, kind, obj, px = cands[0]
            # Continue from the reached price. Newly activated breached orders
            # execute here; they cannot revisit a level earlier in this leg.
            a = px
            for t in self.open:
                t.touch(a)
            if kind == "lentry":
                self._pending_entries.remove(obj)
                self._fill_entry(obj, px, bar)
                progress = True
                continue
            ex: ExitOrder = obj
            avail = self.qty_open(ex.from_entry)
            trades = sorted(self.open, key=lambda t: t.seq)  # FIFO: TradingView reduces the position starting with the OLDEST open trade,
            #                                                   "even if the exit command specifies the entry ID of a different open trade"
            want = avail if ex.qty is None else min(ex.qty - ex.filled, avail)
            if want <= 0:
                self._exits.pop(ex.id, None)
                progress = True
                continue
            comment = ex.comment_profit if kind == "tp" else ex.comment_loss
            left = want
            for t in trades:
                if left <= 0:
                    break
                q = min(left, t.qty)
                fill_px = px if kind == "tp" else self._slip(px, -t.direction)   # stops slip, limits do not
                self._close_trade_qty(t, q, fill_px, bar, comment, kind)
                left -= q
            ex.filled += want
            self._exits.pop(ex.id, None)                      # the OCO pair is done for this id
            progress = True

    # ── views for the dashboard / journal ──
    def open_trades_view(self) -> List[dict]:
        return [t.__dict__.copy() for t in self.open]

    def live_exits(self) -> List[dict]:
        return [{"id": e.id, "from": e.from_entry, "qty": e.qty, "limit": e.limit_px, "stop": e.stop_px,
                 "tp_comment": e.comment_profit, "sl_comment": e.comment_loss} for e in self._exits.values() if e.live]

    def pending_view(self) -> List[dict]:
        return [{"id": p.id, "dir": p.direction, "qty": p.qty, "limit": p.limit} for p in self._pending_entries] + \
               [{"close": c.entry_id, "comment": c.comment} for c in self._pending_closes]
