"""Execution engine.

MIRROR mode (default): TradingView's strategy is the brain. Every order-fill
alert tells us the strategy's position AFTER the fill; we reconcile the paper
account to that position (scaled contracts → shares) and keep a protective stop
resting on the broker so a dead tunnel/PC can't leave a naked position. Stop
moves the strategy makes (net-BE, BE, trail) arrive as `stop_update` alerts
and are mirrored too.

BRACKET mode: on an entry fill we place the strategy's own TP1/TP2/SL geometry
as two bracket orders on the broker and let the broker manage exits; TV alerts
are then used only to flatten/reverse. Closer to how a live futures broker
would run it; less faithful to TV's own exit accounting.

SHADOW mode: identical logic against the in-memory ShadowBroker — nothing
leaves the machine.

The planner (`plan_mirror`) is a pure function so the sequencing rules can be
unit-tested without any broker.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .brokers import Broker, BrokerOrder
from .config import Settings
from .journal import Journal
from .mapping import (apply_pct, levels_from_alert, map_symbol, pct_from_prices, round_price,
                      shares_per_contract, target_shares)
from .models import Alert


@dataclass
class Action:
    kind: str                       # cancel_orders | close | market | stop | bracket | replace_stop | noop
    side: str = ""                  # buy | sell
    qty: int = 0
    price: Optional[float] = None   # stop / limit price
    take_profit: Optional[float] = None
    purpose: str = ""               # close | reverse | entry | reduce | mirror | stop | bracket
    note: str = ""


@dataclass
class Result:
    status: str                     # executed | partial | skipped_* | error | duplicate
    note: str = ""
    actions: List[Action] = field(default_factory=list)
    orders: List[Dict[str, Any]] = field(default_factory=list)
    symbol: Optional[str] = None
    target_shares: Optional[int] = None


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


# ──────────────────────────────────────────────────────────────────────
# Pure planner
# ──────────────────────────────────────────────────────────────────────
def plan_mirror(current: int, target: int, *, protective_stop_price: Optional[float] = None,
                has_open_orders: bool = False) -> List[Action]:
    """Sequence of broker actions that takes a signed share position from `current`
    to `target`, then (optionally) leaves a protective stop for the whole target."""
    acts: List[Action] = []
    changing = current != target
    if has_open_orders and (changing or protective_stop_price is not None):
        acts.append(Action("cancel_orders", purpose="housekeeping", note="clear resting exits before touching the position"))
    if changing:
        if current != 0 and target != 0 and _sign(current) != _sign(target):
            acts.append(Action("close", side="sell" if current > 0 else "buy", qty=abs(current), purpose="reverse",
                               note="equities can't flip in one order: close first"))
            acts.append(Action("market", side="buy" if target > 0 else "sell", qty=abs(target), purpose="reverse"))
        elif target == 0:
            acts.append(Action("close", side="sell" if current > 0 else "buy", qty=abs(current), purpose="close"))
        else:
            delta = target - current
            purpose = "entry" if current == 0 else ("reduce" if abs(target) < abs(current) else "add")
            acts.append(Action("market", side="buy" if delta > 0 else "sell", qty=abs(delta), purpose=purpose))
    if target != 0 and protective_stop_price is not None:
        acts.append(Action("stop", side="sell" if target > 0 else "buy", qty=abs(target), price=protective_stop_price,
                           purpose="stop"))
    if not acts:
        acts.append(Action("noop", note="already in sync"))
    return acts


def split_bracket_qty(total: int, q1: float, q2: float) -> tuple[int, int]:
    """Split `total` shares into the strategy's TP1/TP2 legs by the contract ratio q1:q2."""
    if total <= 0:
        return 0, 0
    if q1 <= 0 and q2 <= 0:
        q1, q2 = 1.0, 1.0
    n1 = int(math.floor(total * q1 / (q1 + q2)))
    n1 = max(1, min(n1, total - 1)) if total >= 2 else total
    return n1, total - n1


# ──────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────
class ExecutionEngine:
    def __init__(self, cfg: Settings, broker: Broker, journal: Journal):
        self.cfg = cfg
        self.broker = broker
        self.journal = journal
        self._lock = threading.RLock()
        self.started_at = time.time()
        self.last_alert_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self._quote_cache: Dict[str, tuple] = {}     # symbol -> (ts, price)

    def quote(self, symbol: str, max_age: float = 4.0) -> Optional[float]:
        """Latest proxy price with a short cache so the dashboard poll doesn't hammer the data API."""
        now = time.time()
        hit = self._quote_cache.get(symbol)
        if hit and now - hit[0] < max_age:
            return hit[1]
        try:
            px = self.broker.latest_price(symbol)
        except Exception:
            px = None
        if px is not None:
            self._quote_cache[symbol] = (now, px)
        return px if px is not None else (hit[1] if hit else None)

    # ── state helpers (per symbol, persisted) ──
    def _sym_state(self, symbol: str) -> Dict[str, Any]:
        return self.journal.get_state(f"sym:{symbol}", {}) or {}

    def _set_sym_state(self, symbol: str, st: Dict[str, Any]) -> None:
        self.journal.set_state(f"sym:{symbol}", st)

    def paused(self) -> bool:
        return bool(self.journal.get_state("paused", False))

    def pause(self, reason: str = "") -> None:
        self.journal.set_state("paused", True)
        self.journal.set_state("pause_reason", reason)
        self.journal.log("WARN", f"PAUSED: {reason}")

    def resume(self) -> None:
        self.journal.set_state("paused", False)
        self.journal.set_state("pause_reason", "")
        self.journal.log("INFO", "RESUMED")

    def _log(self, level: str, msg: str) -> None:
        self.journal.log(level, msg)

    # ── daily loss breaker ──
    def _daily_loss_check(self) -> Optional[str]:
        try:
            acct = self.broker.account()
        except Exception as ex:  # broker down → do not trade
            return f"broker account unavailable: {ex}"
        equity = float(acct.get("equity") or 0.0)
        today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        day = self.journal.get_state("day_start", {}) or {}
        if day.get("date") != today:
            self.journal.set_state("day_start", {"date": today, "equity": equity})
            return None
        start = float(day.get("equity") or equity)
        if self.cfg.daily_loss_limit_usd > 0 and (equity - start) <= -abs(self.cfg.daily_loss_limit_usd):
            self.pause(f"daily loss limit hit: {equity - start:.2f} vs -{self.cfg.daily_loss_limit_usd:.2f}")
            return "daily loss limit"
        return None

    # ── entry point ──
    def handle_alert(self, alert: Alert, *, simulated: bool = False) -> Result:
        with self._lock:
            self.last_alert_at = time.time()
            symbol = map_symbol(alert.ticker, self.cfg.symbol_map) if alert.ticker else None
            if alert.event == "stop_update" and not symbol:
                # stop updates carry the system + side; resolve symbol from the last mapped ticker
                symbol = self.journal.get_state("last_symbol")
            a = alert.to_dict()
            a["raw"] = dict(alert.raw, _dedup_key=alert.dedup_key(), _simulated=simulated)

            # de-dup (TradingView can re-fire on reconnects)
            if alert.dedup_key() in self.journal.recent_dedup_keys(self.cfg.dedup_window_sec) and not simulated:
                aid = self.journal.add_alert(a, symbol, "duplicate", "same alert seen within dedup window")
                return Result("duplicate", "duplicate alert ignored", symbol=symbol)

            if alert.event == "text":
                self.journal.add_alert(a, symbol, "journaled", "plain alert() text — no order info")
                return Result("journaled", "text alert journaled", symbol=symbol)

            if not symbol:
                self.journal.add_alert(a, None, "skipped_unmapped", f"no proxy for ticker '{alert.ticker}' — add it to SYMBOL_MAP")
                return Result("skipped_unmapped", f"ticker {alert.ticker} not mapped")

            if self.paused():
                self.journal.add_alert(a, symbol, "skipped_paused", str(self.journal.get_state("pause_reason", "")))
                return Result("skipped_paused", "bridge is paused", symbol=symbol)

            if self.cfg.execution_mode != "shadow":
                why = self._daily_loss_check()
                if why:
                    self.journal.add_alert(a, symbol, "skipped_risk", why)
                    return Result("skipped_risk", why, symbol=symbol)

            aid = self.journal.add_alert(a, symbol, "processing", proxy_quote=self.quote(symbol, 0.0))
            self.journal.set_state("last_symbol", symbol)
            try:
                if alert.event == "stop_update":
                    res = self._handle_stop_update(alert, symbol, aid)
                elif self.cfg.execution_mode == "bracket":
                    res = self._handle_fill_bracket(alert, symbol, aid)
                else:
                    res = self._handle_fill_mirror(alert, symbol, aid)
            except Exception as ex:
                self.last_error = f"{type(ex).__name__}: {ex}"
                self._log("ERROR", f"alert {aid}: {self.last_error}")
                self.journal.update_alert(aid, "error", self.last_error)
                return Result("error", self.last_error, symbol=symbol)
            self.journal.update_alert(aid, res.status, res.note)
            return res

    # ── market-hours guard ──
    def _market_ok(self) -> tuple[bool, str]:
        try:
            c = self.broker.clock()
        except Exception as ex:
            return False, f"clock unavailable: {ex}"
        if c.is_open:
            return True, ""
        if self.cfg.allow_extended_hours:
            return True, "extended-hours (marketable limit)"
        return False, f"market closed (next open {c.next_open})"

    # ── order helpers ──
    def _run_action(self, act: Action, symbol: str, aid: int, extended: bool) -> Optional[BrokerOrder]:
        b = self.broker
        if act.kind == "cancel_orders":
            n = b.cancel_orders(symbol)
            self.journal.add_order(aid, symbol, "", 0, "cancel", act.purpose, status="done", note=f"cancelled {n} open order(s)")
            return None
        if act.kind == "close":
            o = b.close_position(symbol)
            if o is None:
                return None
            row = self.journal.add_order(aid, symbol, act.side, act.qty, "market", act.purpose, broker_order_id=o.id, status=o.status)
            o = b.wait_filled(o.id, 15.0)
            self.journal.update_order(row, status=o.status, filled_qty=o.filled_qty, fill_price=o.fill_price)
            return o
        if act.kind == "market":
            o = b.submit_market(symbol, act.side, act.qty, extended=extended)
            row = self.journal.add_order(aid, symbol, act.side, act.qty, "market", act.purpose, broker_order_id=o.id, status=o.status)
            o = b.wait_filled(o.id, 15.0)
            self.journal.update_order(row, status=o.status, filled_qty=o.filled_qty, fill_price=o.fill_price)
            return o
        if act.kind == "stop":
            o = b.submit_stop(symbol, act.side, act.qty, act.price or 0.0)
            self.journal.add_order(aid, symbol, act.side, act.qty, "stop", act.purpose, stop_price=act.price,
                                   broker_order_id=o.id, status=o.status)
            return o
        if act.kind == "bracket":
            o = b.submit_bracket(symbol, act.side, act.qty, act.take_profit or 0.0, act.price or 0.0)
            self.journal.add_order(aid, symbol, act.side, act.qty, "bracket", act.purpose, limit_price=act.take_profit,
                                   stop_price=act.price, broker_order_id=o.id, status=o.status)
            return o
        return None

    # ── MIRROR ──
    def _handle_fill_mirror(self, alert: Alert, symbol: str, aid: int) -> Result:
        ok, why = self._market_ok()
        if not ok:
            return Result("skipped_market_closed", why, symbol=symbol)
        extended = bool(why)  # non-empty why == extended-hours note

        price = self.broker.latest_price(symbol)
        levels = levels_from_alert(alert, self.cfg)
        spc = shares_per_contract(self.cfg, price or 0.0, levels.sl_pct)
        target = target_shares(alert.position_size, spc, self.cfg.max_position_shares)
        current = int(round(self.broker.position(symbol)))
        st = self._sym_state(symbol)
        has_open = len(self.broker.open_orders(symbol)) > 0

        # protective stop: new geometry on an entry/reversal, inherited on a reduction
        stop_price: Optional[float] = None
        if self.cfg.protective_stop and target != 0:
            entering = current == 0 or _sign(current) != _sign(target) or alert.is_entry
            if entering or not st.get("stop_price"):
                ref = price or (levels.ref_price or 0.0)
                stop_price = round_price(apply_pct(ref, -levels.sl_pct if target > 0 else levels.sl_pct))
            else:
                stop_price = float(st["stop_price"])

        actions = plan_mirror(current, target, protective_stop_price=stop_price, has_open_orders=has_open)
        orders: List[Dict[str, Any]] = []
        fill_px: Optional[float] = None
        for act in actions:
            if act.kind == "noop":
                continue
            o = self._run_action(act, symbol, aid, extended)
            if o is not None:
                orders.append({"id": o.id, "kind": act.kind, "side": act.side, "qty": act.qty, "status": o.status,
                               "fill_price": o.fill_price, "price": act.price})
                if act.kind in ("market", "close") and o.fill_price and act.purpose in ("entry", "reverse", "add"):
                    fill_px = o.fill_price
        # re-anchor the stop to the actual fill on entries (tighter fidelity than the pre-trade quote)
        if stop_price is not None and fill_px and target != 0 and (current == 0 or _sign(current) != _sign(target) or alert.is_entry):
            new_stop = round_price(apply_pct(fill_px, -levels.sl_pct if target > 0 else levels.sl_pct))
            if abs(new_stop - stop_price) / max(stop_price, 1e-9) > 0.0005:
                self.broker.cancel_orders(symbol)
                o = self.broker.submit_stop(symbol, "sell" if target > 0 else "buy", abs(target), new_stop)
                self.journal.add_order(aid, symbol, o.side, abs(target), "stop", "stop", stop_price=new_stop,
                                       broker_order_id=o.id, status=o.status, note="re-anchored to fill")
                stop_price = new_stop
        # persist per-symbol state
        if target == 0:
            self._set_sym_state(symbol, {})
        else:
            self._set_sym_state(symbol, {
                "side": "long" if target > 0 else "short", "shares": target, "stop_price": stop_price,
                "sl_pct": levels.sl_pct, "tp1_pct": levels.tp1_pct, "tp2_pct": levels.tp2_pct,
                "entry_fill": fill_px or st.get("entry_fill") or price, "tv_ref": levels.ref_price,
                "system": alert.system, "updated": time.time(),
            })
        final = int(round(self.broker.position(symbol)))
        status = "executed" if final == target else "partial"
        note = f"{current}→{target} shares ({alert.position_size:+g} contracts × {spc:.2f}); stop={stop_price}; levels={levels.source}"
        if status == "partial":
            note += f"; broker shows {final}"
        self._log("INFO", f"[{symbol}] {alert.system} {alert.order_id}/{alert.comment} {note}")
        return Result(status, note, actions, orders, symbol, target)

    # ── BRACKET ──
    def _handle_fill_bracket(self, alert: Alert, symbol: str, aid: int) -> Result:
        ok, why = self._market_ok()
        if not ok:
            return Result("skipped_market_closed", why, symbol=symbol)
        extended = bool(why)
        price = self.broker.latest_price(symbol)
        levels = levels_from_alert(alert, self.cfg)
        spc = shares_per_contract(self.cfg, price or 0.0, levels.sl_pct)
        target = target_shares(alert.position_size, spc, self.cfg.max_position_shares)
        current = int(round(self.broker.position(symbol)))
        orders: List[Dict[str, Any]] = []

        if target == 0:
            # TV flat (EOD / flip / stop) → flatten here too
            acts = plan_mirror(current, 0, has_open_orders=True)
            for act in acts:
                if act.kind != "noop":
                    o = self._run_action(act, symbol, aid, extended)
                    if o: orders.append({"id": o.id, "kind": act.kind, "status": o.status, "fill_price": o.fill_price})
            self._set_sym_state(symbol, {})
            return Result("executed", f"flattened ({current}→0)", acts, orders, symbol, 0)

        reversing = current != 0 and _sign(current) != _sign(target)
        if alert.is_entry or reversing or current == 0:
            if current != 0:
                for act in plan_mirror(current, 0, has_open_orders=True):
                    if act.kind != "noop":
                        o = self._run_action(act, symbol, aid, extended)
                        if o: orders.append({"id": o.id, "kind": act.kind, "status": o.status, "fill_price": o.fill_price})
            ref = price or (levels.ref_price or 0.0)
            side = "buy" if target > 0 else "sell"
            sgn = 1 if target > 0 else -1
            q1, q2 = split_bracket_qty(abs(target), float(alert.meta.get("q1", 2) or 2), float(alert.meta.get("q2", 3) or 3))
            sl = round_price(apply_pct(ref, -sgn * levels.sl_pct))
            legs = [(q1, round_price(apply_pct(ref, sgn * levels.tp1_pct))), (q2, round_price(apply_pct(ref, sgn * levels.tp2_pct)))]
            acts = []
            for q, tp in legs:
                if q <= 0:
                    continue
                act = Action("bracket", side=side, qty=q, price=sl, take_profit=tp, purpose="bracket")
                acts.append(act)
                o = self._run_action(act, symbol, aid, extended)
                if o: orders.append({"id": o.id, "kind": "bracket", "qty": q, "tp": tp, "sl": sl, "status": o.status})
            self._set_sym_state(symbol, {"side": "long" if target > 0 else "short", "shares": target, "stop_price": sl,
                                         "sl_pct": levels.sl_pct, "tp1_pct": levels.tp1_pct, "tp2_pct": levels.tp2_pct,
                                         "entry_fill": ref, "tv_ref": levels.ref_price, "system": alert.system,
                                         "updated": time.time(), "mode": "bracket"})
            return Result("executed", f"brackets placed: {legs} sl={sl}", acts, orders, symbol, target)

        # a reduction fill from TV (TP1 etc.) — the broker's own brackets handle it; journal only
        return Result("executed", f"bracket mode: TV reduction {alert.comment} noted; broker legs manage exits", [], [], symbol, target)

    # ── STOP UPDATE (net-BE / BE / trail moves from the strategy) ──
    def _handle_stop_update(self, alert: Alert, symbol: str, aid: int) -> Result:
        st = self._sym_state(symbol)
        current = int(round(self.broker.position(symbol)))
        if current == 0:
            return Result("skipped_flat", "stop update with no open position", symbol=symbol)
        stop_fut = alert.meta.get("stop"); ref_fut = alert.meta.get("ref")
        if not isinstance(stop_fut, (int, float)) or not isinstance(ref_fut, (int, float)) or ref_fut <= 0:
            return Result("skipped_bad_payload", "stop_update needs numeric 'stop' and 'ref'", symbol=symbol)
        price = self.broker.latest_price(symbol) or float(st.get("entry_fill") or 0.0)
        if price <= 0:
            return Result("skipped_no_quote", "no proxy quote", symbol=symbol)
        pct = pct_from_prices(float(stop_fut), float(ref_fut), self.cfg.leverage_factor)   # signed, relative to NOW
        new_stop = round_price(price * (1.0 + pct))
        old_stop = st.get("stop_price")
        # never loosen
        if old_stop:
            if current > 0 and new_stop < float(old_stop) - 1e-9:
                return Result("skipped_loosen", f"refused to loosen long stop {old_stop}→{new_stop}", symbol=symbol)
            if current < 0 and new_stop > float(old_stop) + 1e-9:
                return Result("skipped_loosen", f"refused to loosen short stop {old_stop}→{new_stop}", symbol=symbol)
        # replace: prefer in-place replace on resting stop legs, else cancel+resubmit
        replaced = False
        for o in self.broker.open_orders(symbol):
            if o.kind == "stop" or (o.kind == "bracket" and o.legs):
                targets = [o] if o.kind == "stop" else [l for l in o.legs if l.kind == "stop"]
                for leg in targets:
                    try:
                        self.broker.replace_stop(leg.id, new_stop)
                        replaced = True
                    except Exception:
                        pass
        if not replaced:
            self.broker.cancel_orders(symbol)
            o = self.broker.submit_stop(symbol, "sell" if current > 0 else "buy", abs(current), new_stop)
            self.journal.add_order(aid, symbol, o.side, abs(current), "stop", "stop", stop_price=new_stop,
                                   broker_order_id=o.id, status=o.status, note=f"stop_update {alert.meta.get('tag','')}")
        else:
            self.journal.add_order(aid, symbol, "sell" if current > 0 else "buy", abs(current), "replace_stop", "stop",
                                   stop_price=new_stop, status="done", note=f"stop_update {alert.meta.get('tag','')}")
        st["stop_price"] = new_stop
        st["stop_tag"] = alert.meta.get("tag", "")
        st["updated"] = time.time()
        self._set_sym_state(symbol, st)
        self._log("INFO", f"[{symbol}] stop → {new_stop} ({alert.meta.get('tag','')})")
        return Result("executed", f"stop moved {old_stop}→{new_stop} ({alert.meta.get('tag','')})", symbol=symbol)

    # ── admin ──
    def flatten_all(self, reason: str = "manual") -> Dict[str, Any]:
        with self._lock:
            out = {"cancelled": 0, "closed": []}
            try:
                out["cancelled"] = self.broker.cancel_orders(None)
            except Exception as ex:
                out["cancel_error"] = str(ex)
            for p in self.broker.positions():
                try:
                    o = self.broker.close_position(p["symbol"])
                    out["closed"].append({"symbol": p["symbol"], "qty": p["qty"], "order": o.id if o else None})
                    self.journal.add_order(None, p["symbol"], "sell" if p["qty"] > 0 else "buy", abs(p["qty"]), "market",
                                           "flatten", broker_order_id=o.id if o else "", status=o.status if o else "n/a", note=reason)
                except Exception as ex:
                    out["closed"].append({"symbol": p["symbol"], "error": str(ex)})
            for k in list(self.journal.all_state().keys()):
                if k.startswith("sym:"):
                    self.journal.set_state(k, {})
            self._log("WARN", f"FLATTEN ALL ({reason}): {out}")
            return out

    def status(self) -> Dict[str, Any]:
        st = {
            "mode": self.cfg.execution_mode, "broker": getattr(self.broker, "name", "?"),
            "paused": self.paused(), "pause_reason": self.journal.get_state("pause_reason", ""),
            "uptime_sec": time.time() - self.started_at,
            "last_alert_age_sec": (time.time() - self.last_alert_at) if self.last_alert_at else None,
            "last_error": self.last_error,
            "symbol_state": {k[4:]: v for k, v in self.journal.all_state().items() if k.startswith("sym:")},
        }
        try:
            syms = {s for s in self.cfg.symbol_map.values()} | {k[4:] for k in self.journal.all_state() if k.startswith("sym:")}
            st["quotes"] = {s: self.quote(s) for s in sorted(syms) if s}
            st["account"] = self.broker.account()
            c = self.broker.clock()
            st["market"] = {"is_open": c.is_open, "next_open": c.next_open, "next_close": c.next_close}
            st["positions"] = self.broker.positions()
            st["open_orders"] = [o.__dict__ | {"legs": [l.__dict__ for l in o.legs]} for o in self.broker.open_orders(None)]
        except Exception as ex:
            st["broker_error"] = str(ex)
        return st
