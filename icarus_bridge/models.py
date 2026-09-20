"""Alert payload parsing — pure, dependency-free, heavily defensive.

TradingView sends whatever text is in the alert's Message box, with
{{placeholders}} substituted. Two payload shapes are accepted:

1) ORDER-FILL alerts (the alert template in pine/ALERT_TEMPLATE.json):
   {"secret": "...", "event": "order_fill", "ticker": "NQ1!", "action": "buy",
    "contracts": "5", "order_id": "Long", "comment": "", "order_price": "20123.5",
    "position_size": "5", "market_position": "long", "prev_market_position": "flat",
    "bar_close": "20120.25", "time": "2026-09-12T14:30:00Z",
    "meta": "sys=RATE;side=long;tp1=15;tp2=30;sl=45;q1=2;q2=3;ref=20120.25"}

   Numerics are quoted in the template on purpose: an empty placeholder
   would otherwise produce invalid JSON. Everything is coerced here.

2) alert() calls from the script (stop updates etc.) — JSON built in Pine:
   {"secret":"...","event":"stop_update","sys":"RATE","side":"long",
    "stop":20105.25,"ref":20140.0,"tag":"L_NETBE"}

`meta` uses key=value;key=value (NOT JSON) because TradingView does not
escape quotes inside {{strategy.order.alert_message}}.
"""
from __future__ import annotations

import json
import re
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class AlertParseError(ValueError):
    pass


_PLACEHOLDER = re.compile(r"\{\{[^}]+\}\}")


def _num(v: Any, default: Optional[float] = None) -> Optional[float]:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s == "" or s.lower() in ("na", "nan", "null", "none"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def parse_meta(s: Any) -> Dict[str, Any]:
    """'sys=RATE;tp1=15;tp2=30' -> {'sys': 'RATE', 'tp1': 15.0, ...}. Accepts JSON too."""
    if s is None:
        return {}
    if isinstance(s, dict):
        return dict(s)
    text = str(s).strip()
    if text == "" or _PLACEHOLDER.search(text):
        return {}
    if text.startswith("{"):
        try:
            d = json.loads(text)
            return d if isinstance(d, dict) else {}
        except json.JSONDecodeError:
            pass
    out: Dict[str, Any] = {}
    for part in re.split(r"[;,\n]", text):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        n = _num(v)
        out[k] = n if n is not None and re.fullmatch(r"-?\d+(\.\d+)?", v) else v
    return out


@dataclass
class Alert:
    event: str                      # order_fill | stop_update | text
    ticker: str = ""
    action: str = ""                # buy | sell (as sent by TV; lower-cased)
    contracts: float = 0.0
    order_id: str = ""              # Long / Short / TideLong / TideShort / L1 / L2 ...
    comment: str = ""               # L_TP1 / L_SL / L_NETBE / PB→MKT ...
    order_price: Optional[float] = None
    position_size: float = 0.0      # signed contracts AFTER the fill (TV convention)
    market_position: str = ""       # long | short | flat
    prev_market_position: str = ""
    bar_close: Optional[float] = None
    time: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)
    received_at: float = field(default_factory=_time.time)

    # ── derived helpers ──
    @property
    def system(self) -> str:
        """RATE / TIDE / other — from meta.sys, else inferred from the order id."""
        s = str(self.meta.get("sys", "")).upper()
        if s:
            return s
        oid = self.order_id.lower()
        if oid.startswith("tide") or oid in ("t1", "t2"):
            return "TIDE"
        if oid in ("long", "short", "l1", "l2", "s1", "s2"):
            return "RATE"
        return "OTHER"

    @property
    def is_entry(self) -> bool:
        """A fill that opened or reversed into a position (vs. a reduction/exit)."""
        if self.event != "order_fill" or abs(self.position_size) < 1e-9:
            return False
        return self.prev_market_position in ("flat", "") or self.prev_market_position != self.market_position

    @property
    def is_flat_after(self) -> bool:
        return self.event == "order_fill" and (self.market_position == "flat" or abs(self.position_size) < 1e-9)

    def dedup_key(self) -> str:
        if self.event == "order_fill":
            return f"fill|{self.ticker}|{self.time}|{self.order_id}|{self.action}|{self.contracts}|{self.position_size}"
        if self.event == "stop_update":
            return f"stop|{self.meta.get('sys','')}|{self.meta.get('side','')}|{self.meta.get('stop','')}"
        return f"text|{self.raw.get('text','')[:120]}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event, "ticker": self.ticker, "action": self.action,
            "contracts": self.contracts, "order_id": self.order_id, "comment": self.comment,
            "order_price": self.order_price, "position_size": self.position_size,
            "market_position": self.market_position, "prev_market_position": self.prev_market_position,
            "bar_close": self.bar_close, "time": self.time, "meta": self.meta,
            "system": self.system, "received_at": self.received_at,
        }


def parse_alert(body: bytes | str, *, expected_secret: str = "") -> Alert:
    """Parse a webhook body. Raises AlertParseError with a human-readable hint."""
    text = body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
    text = text.strip()
    if not text:
        raise AlertParseError("empty body")

    if _PLACEHOLDER.search(text):
        raise AlertParseError(
            "body still contains {{placeholders}} — the alert was created on an indicator/price "
            "condition, not on the STRATEGY (use 'Order fills and alert() function calls')")

    data: Dict[str, Any]
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as ex:
            # Tolerate a bare (unquoted) meta value that broke the JSON: strip it and retry
            fixed = re.sub(r'"meta"\s*:\s*[^,}]*', '"meta": ""', text)
            try:
                data = json.loads(fixed)
            except json.JSONDecodeError:
                raise AlertParseError(f"invalid JSON: {ex.msg} at pos {ex.pos}") from None
        if not isinstance(data, dict):
            raise AlertParseError("JSON body must be an object")
    else:
        # Plain-text alert() message — keep it, but it carries no order info
        data = {"event": "text", "text": text}

    event = str(data.get("event", "")).strip().lower()
    if not event:
        # Heuristic: order-fill templates always carry an action or position field
        event = "order_fill" if ("action" in data or "position_size" in data) else "text"

    # Only payloads that can move money must carry the secret; plain text is journal-only anyway.
    if expected_secret and event != "text":
        got = str(data.get("secret", ""))
        if got != expected_secret:
            raise AlertParseError("bad or missing secret")

    a = Alert(
        event=event,
        ticker=str(data.get("ticker", "")).strip().upper(),
        action=str(data.get("action", "")).strip().lower(),
        contracts=abs(_num(data.get("contracts"), 0.0) or 0.0),
        order_id=str(data.get("order_id", "")).strip(),
        comment=str(data.get("comment", "")).strip(),
        order_price=_num(data.get("order_price")),
        position_size=_num(data.get("position_size"), 0.0) or 0.0,
        market_position=str(data.get("market_position", "")).strip().lower(),
        prev_market_position=str(data.get("prev_market_position", "")).strip().lower(),
        bar_close=_num(data.get("bar_close")),
        time=str(data.get("time", "")).strip(),
        meta=parse_meta(data.get("meta")),
        raw={k: v for k, v in data.items() if k != "secret"},
    )
    # stop_update / other alert() JSON: promote top-level fields into meta
    if event != "order_fill":
        for k in ("sys", "side", "stop", "ref", "tag", "text"):
            if k in data and k not in a.meta:
                a.meta[k] = data[k]
        if "stop" in a.meta:
            a.meta["stop"] = _num(a.meta["stop"])
        if "ref" in a.meta:
            a.meta["ref"] = _num(a.meta["ref"])

    # TV's market_position is the state AFTER the fill; make position_size sign agree with it
    if a.event == "order_fill":
        if a.market_position == "short" and a.position_size > 0:
            a.position_size = -a.position_size
        if a.market_position == "flat":
            a.position_size = 0.0
        if a.market_position == "" and a.position_size != 0:
            a.market_position = "long" if a.position_size > 0 else "short"
    return a
