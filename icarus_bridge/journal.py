"""SQLite journal — every alert, every order, engine state, and a rolling log.

Single-writer friendly (WAL mode); the MCP process only reads or writes the
`state` table, the daemon does everything else.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at REAL NOT NULL,
  event TEXT, ticker TEXT, symbol TEXT, system TEXT,
  action TEXT, contracts REAL, order_id TEXT, comment TEXT,
  order_price REAL, position_size REAL, market_position TEXT,
  tv_time TEXT, meta TEXT, raw TEXT,
  status TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_id INTEGER, ts REAL NOT NULL,
  symbol TEXT, side TEXT, qty REAL, kind TEXT,
  limit_price REAL, stop_price REAL,
  broker_order_id TEXT, status TEXT, filled_qty REAL, fill_price REAL,
  purpose TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS state (
  key TEXT PRIMARY KEY, value TEXT, updated_at REAL
);
CREATE TABLE IF NOT EXISTS log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, msg TEXT
);
CREATE TABLE IF NOT EXISTS equity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, equity REAL, cash REAL, unrealized REAL
);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity(ts);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(received_at);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);
CREATE INDEX IF NOT EXISTS idx_log_ts ON log(ts);
"""


class Journal:
    def __init__(self, path: str = "icarus_bridge.db"):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            # migrations for databases created before these columns existed
            for stmt in ("ALTER TABLE alerts ADD COLUMN proxy_quote REAL",):
                try:
                    self._conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass

    # ── helpers ──
    def _rows(self, sql: str, args: tuple = ()) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]

    def _exec(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, args)
            return int(cur.lastrowid or 0)

    # ── alerts ──
    def add_alert(self, a: Dict[str, Any], symbol: Optional[str], status: str, note: str = "",
                  proxy_quote: Optional[float] = None) -> int:
        return self._exec(
            """INSERT INTO alerts(received_at,event,ticker,symbol,system,action,contracts,order_id,comment,
               order_price,position_size,market_position,tv_time,meta,raw,status,note,proxy_quote)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (a.get("received_at", time.time()), a.get("event"), a.get("ticker"), symbol, a.get("system"),
             a.get("action"), a.get("contracts"), a.get("order_id"), a.get("comment"),
             a.get("order_price"), a.get("position_size"), a.get("market_position"), a.get("time"),
             json.dumps(a.get("meta") or {}), json.dumps(a.get("raw") or {}, default=str), status, note, proxy_quote))

    def set_alert_quote(self, alert_id: int, proxy_quote: Optional[float]) -> None:
        self._exec("UPDATE alerts SET proxy_quote=? WHERE id=?", (proxy_quote, alert_id))

    def update_alert(self, alert_id: int, status: str, note: str = "") -> None:
        self._exec("UPDATE alerts SET status=?, note=? WHERE id=?", (status, note, alert_id))

    def recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._rows("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (int(limit),))
        for r in rows:
            for k in ("meta", "raw"):
                try:
                    r[k] = json.loads(r[k]) if r[k] else {}
                except Exception:
                    pass
        return rows

    def recent_dedup_keys(self, window_sec: float) -> List[str]:
        cutoff = time.time() - window_sec
        rows = self._rows("SELECT raw FROM alerts WHERE received_at >= ? AND status != 'duplicate'", (cutoff,))
        keys = []
        for r in rows:
            try:
                d = json.loads(r["raw"])
                keys.append(str(d.get("_dedup_key", "")))
            except Exception:
                pass
        return keys

    # ── orders ──
    def add_order(self, alert_id: Optional[int], symbol: str, side: str, qty: float, kind: str,
                  purpose: str, limit_price: Optional[float] = None, stop_price: Optional[float] = None,
                  broker_order_id: str = "", status: str = "submitted", note: str = "") -> int:
        return self._exec(
            """INSERT INTO orders(alert_id,ts,symbol,side,qty,kind,limit_price,stop_price,broker_order_id,status,purpose,note)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (alert_id, time.time(), symbol, side, qty, kind, limit_price, stop_price, broker_order_id, status, purpose, note))

    def update_order(self, order_row_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE orders SET {cols} WHERE id=?", (*fields.values(), order_row_id))

    def recent_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (int(limit),))

    def orders_for_alert(self, alert_id: int) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM orders WHERE alert_id=? ORDER BY id", (alert_id,))

    # ── state ──
    def get_state(self, key: str, default: Any = None) -> Any:
        rows = self._rows("SELECT value FROM state WHERE key=?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except Exception:
            return rows[0]["value"]

    def set_state(self, key: str, value: Any) -> None:
        self._exec("INSERT INTO state(key,value,updated_at) VALUES(?,?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                   (key, json.dumps(value), time.time()))

    def all_state(self) -> Dict[str, Any]:
        out = {}
        for r in self._rows("SELECT key, value FROM state"):
            try:
                out[r["key"]] = json.loads(r["value"])
            except Exception:
                out[r["key"]] = r["value"]
        return out

    # ── log ──
    def log(self, level: str, msg: str) -> None:
        self._exec("INSERT INTO log(ts,level,msg) VALUES(?,?,?)", (time.time(), level, msg))
        # keep the table bounded
        self._exec("DELETE FROM log WHERE id < (SELECT MAX(id) FROM log) - 5000")

    def recent_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM log ORDER BY id DESC LIMIT ?", (int(limit),))

    # ── equity history ──
    def add_equity(self, equity: float, cash: Optional[float], unrealized: Optional[float]) -> None:
        self._exec("INSERT INTO equity(ts,equity,cash,unrealized) VALUES(?,?,?,?)", (time.time(), equity, cash, unrealized))
        self._exec("DELETE FROM equity WHERE ts < ?", (time.time() - 14 * 86400,))

    def equity_series(self, since_sec: float = 86400.0, max_points: int = 600) -> List[Dict[str, Any]]:
        rows = self._rows("SELECT ts, equity, cash, unrealized FROM equity WHERE ts >= ? ORDER BY ts",
                          (time.time() - since_sec,))
        if len(rows) > max_points:                      # thin evenly, keep the last point
            step = len(rows) / max_points
            rows = [rows[int(i * step)] for i in range(max_points - 1)] + [rows[-1]]
        return rows

    def counts_today(self) -> Dict[str, Any]:
        """Alert outcome counts + per-system counts since local midnight."""
        import datetime as _dt
        midnight = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        rows = self._rows("SELECT status, system, COUNT(*) AS n FROM alerts WHERE received_at >= ? GROUP BY status, system", (midnight,))
        by_status: Dict[str, int] = {}
        by_system: Dict[str, int] = {}
        for r in rows:
            by_status[r["status"] or "?"] = by_status.get(r["status"] or "?", 0) + r["n"]
            by_system[r["system"] or "?"] = by_system.get(r["system"] or "?", 0) + r["n"]
        fills = self._rows("SELECT COUNT(*) AS n FROM orders WHERE ts >= ? AND status='filled'", (midnight,))
        return {"by_status": by_status, "by_system": by_system, "paper_fills": fills[0]["n"] if fills else 0}

    # ── analytics ──
    def tv_vs_paper(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Pair each order-fill alert with the paper fills it produced (slippage / reality-gap view)."""
        alerts = self._rows(
            "SELECT id, received_at, ticker, symbol, system, action, order_id, comment, order_price, "
            "position_size, market_position, proxy_quote FROM alerts WHERE event='order_fill' AND status IN ('executed','partial') "
            "ORDER BY id DESC LIMIT ?", (int(limit),))
        out = []
        for a in alerts:
            fills = self._rows("SELECT side, qty, kind, purpose, fill_price, filled_qty, status, ts FROM orders "
                               "WHERE alert_id=? AND purpose IN ('mirror','entry','add','reduce','close','reverse')", (a["id"],))
            filled = [f for f in fills if f.get("fill_price")]
            avg = None
            if filled:
                q = sum(f["filled_qty"] or f["qty"] for f in filled)
                avg = sum((f["fill_price"] or 0) * (f["filled_qty"] or f["qty"]) for f in filled) / q if q else None
            latency = (min(f["ts"] for f in fills) - a["received_at"]) if fills else None
            # slippage vs the proxy quote the bridge saw when the alert arrived, signed so + = worse
            slip_bps = None
            q = a.get("proxy_quote")
            if avg and q:
                buying = (a.get("action") == "buy")
                slip_bps = ((avg - q) / q * 1e4) * (1 if buying else -1)
            out.append({**a, "paper_fill_avg": avg, "paper_orders": len(fills), "latency_sec": latency, "slippage_bps": slip_bps})
        return out

    def close(self) -> None:
        with self._lock:
            self._conn.close()
