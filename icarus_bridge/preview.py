"""Demo / preview server — zero third-party dependencies.

Runs the REAL engine + journal against the in-memory ShadowBroker, replays a
scripted trading day (entry → TP1 → net-BE stop move → BE → reversal → EOD
flat) with a wandering QQQ price, samples equity, and serves the dashboard on
http://127.0.0.1:8790 using only the standard library.

  icarus-bridge demo            (or: python -m icarus_bridge.preview)

It answers the same /status/public, /webhook and /admin/* routes the FastAPI
app does, so the dashboard and the MCP server work against it unchanged.
Nothing touches Alpaca.
"""
from __future__ import annotations

import json
import math
import random
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse, parse_qs

from .brokers.shadow import ShadowBroker
from .config import Settings
from .executor import ExecutionEngine
from .journal import Journal
from .models import AlertParseError, parse_alert


def _fill(secret: str, side: str, contracts: float, pos_after: float, prev: str, comment: str = "", px: float = 20000.0,
          order_id: str = "", system: str = "RATE", t: str = "") -> str:
    mp = "flat" if abs(pos_after) < 1e-9 else ("long" if pos_after > 0 else "short")
    return json.dumps({
        "secret": secret, "event": "order_fill", "ticker": "NQ1!", "action": "buy" if side == "long" else "sell",
        "contracts": str(contracts), "order_id": order_id or ("Long" if side == "long" else "Short"), "comment": comment,
        "order_price": f"{px:.2f}", "position_size": str(abs(pos_after)), "market_position": mp, "prev_market_position": prev,
        "bar_close": f"{px:.2f}", "time": t or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "meta": f"sys={system};side={side};tp1=15;tp2=30;sl=45;q1=2;q2=3;ref={px:.2f};regime=0.71",
    })


def _stop(secret: str, side: str, stop: float, ref: float, tag: str) -> str:
    return json.dumps({"secret": secret, "event": "stop_update", "sys": "RATE", "side": side, "stop": stop, "ref": ref, "tag": tag})


class Demo:
    def __init__(self, port: int = 8790, speed: float = 1.0):
        self.cfg = Settings()
        self.cfg.execution_mode = "shadow"
        self.cfg.webhook_secret = "demo"
        self.cfg.admin_token = "demo"
        self.port = port
        self.speed = speed
        self.tmp = tempfile.mkdtemp(prefix="icarus-demo-")
        self.journal = Journal(str(Path(self.tmp) / "demo.db"))
        self.broker = ShadowBroker({"QQQ": 500.0, "SPY": 640.0, "IWM": 230.0, "DIA": 440.0, "TQQQ": 90.0})
        self.engine = ExecutionEngine(self.cfg, self.broker, self.journal)
        self.public_url = "https://demo-1234.ngrok-free.app"
        self.journal.set_state("public_url", self.public_url)
        self.nq = 20000.0
        self._stop = threading.Event()
        self.journal.log("INFO", "DEMO mode: shadow broker, scripted session — nothing is sent to Alpaca")

    # ── scripted market + strategy ──
    def _tick(self) -> None:
        """Random-walk QQQ (and NQ ≈ 40× QQQ) so ladders, P&L and equity move."""
        q = self.broker.prices["QQQ"]
        q *= 1 + random.gauss(0, 0.00035)
        self.broker.set_price("QQQ", round(q, 2))
        self.nq = q * 40.0
        acct = self.broker.account()
        unreal = sum(p["qty"] * (self.broker.prices["QQQ"] - 500.0) for p in self.broker.positions())
        self.journal.add_equity(acct["equity"], acct["cash"], unreal)
        day = self.journal.get_state("day_start", {}) or {}
        today = time.strftime("%Y-%m-%d")
        if day.get("date") != today:
            self.journal.set_state("day_start", {"date": today, "equity": acct["equity"]})

    def _post(self, body: str) -> None:
        try:
            a = parse_alert(body, expected_secret=self.cfg.webhook_secret)
        except AlertParseError as ex:
            self.journal.log("WARN", f"demo alert rejected: {ex}")
            return
        r = self.engine.handle_alert(a)
        self.journal.log("INFO", f"demo → {r.status}: {r.note}")

    def _script(self) -> None:
        s = self.cfg.webhook_secret
        sleep = lambda x: self._stop.wait(x / self.speed)
        # seed some equity history so the chart has a curve immediately
        for _ in range(60):
            self._tick()
        steps = [
            (4, lambda: self._post(_fill(s, "long", 5, 5, "flat", px=self.nq))),
            (8, lambda: self._post(_fill(s, "long", 2, 3, "long", "L_TP1", px=self.nq + 15))),
            (4, lambda: self._post(_stop(s, "long", self.nq - 10, self.nq, "L_NETBE"))),
            (6, lambda: self._post(_stop(s, "long", self.nq + 1, self.nq, "L_BE"))),
            (8, lambda: self._post(_fill(s, "long", 3, 0, "long", "L_TP2", px=self.nq + 30))),
            (6, lambda: self._post(_fill(s, "short", 5, -5, "flat", px=self.nq, order_id="Short"))),
            (7, lambda: self._post(_fill(s, "short", 2, -3, "short", "S_TP1", px=self.nq - 15, order_id="Short"))),
            (5, lambda: self._post(_stop(s, "short", self.nq + 10, self.nq, "S_NETBE"))),
            (8, lambda: self._post(_fill(s, "long", 8, 5, "short", px=self.nq, order_id="Long"))),   # reversal
            (6, lambda: self._post(_fill(s, "long", 2, 2, "long", px=self.nq, order_id="TideLong", system="TIDE"))),
            (9, lambda: self._post(_fill(s, "long", 7, 0, "long", "L_EOD", px=self.nq))),
        ]
        while not self._stop.is_set():
            for wait, fn in steps:
                for _ in range(int(wait)):
                    if self._stop.is_set():
                        return
                    self._tick()
                    sleep(1.0)
                fn()
            sleep(12)

    def start(self) -> None:
        threading.Thread(target=self._script, daemon=True).start()

    # ── status payload identical in shape to webhook.status_public ──
    def status_public(self) -> Dict[str, Any]:
        st = self.engine.status()
        acct = st.get("account") or {}
        day = self.journal.get_state("day_start", {}) or {}
        gap = self.journal.tv_vs_paper(60)
        lat = sorted(r["latency_sec"] for r in gap if r.get("latency_sec") is not None)
        slip = sorted(r["slippage_bps"] for r in gap if r.get("slippage_bps") is not None)
        return {
            "now": time.time(), "mode": st["mode"], "broker": st["broker"], "paused": st["paused"],
            "pause_reason": st["pause_reason"], "uptime_sec": st["uptime_sec"],
            "last_alert_age_sec": st["last_alert_age_sec"], "last_error": st["last_error"],
            "market": st.get("market"), "quotes": st.get("quotes", {}),
            "account": {k: acct.get(k) for k in ("equity", "cash", "buying_power", "status", "paper")},
            "day_start_equity": day.get("equity"), "day_start_date": day.get("date"),
            "positions": st.get("positions", []), "open_orders": st.get("open_orders", []),
            "symbol_state": st.get("symbol_state", {}),
            "alerts": self.journal.recent_alerts(25), "orders": self.journal.recent_orders(25), "log": self.journal.recent_log(40),
            "equity_series": self.journal.equity_series(86400.0), "counts_today": self.journal.counts_today(),
            "gap": {"n": len(gap), "latency": lat[-40:], "slippage_bps": slip[-40:],
                    "median_latency_sec": (lat[len(lat) // 2] if lat else None),
                    "median_slippage_bps": (slip[len(slip) // 2] if slip else None), "rows": gap[:12]},
            "limits": {"max_position_shares": self.cfg.max_position_shares, "daily_loss_limit_usd": self.cfg.daily_loss_limit_usd,
                       "sizing_mode": self.cfg.sizing_mode, "notional_per_contract_usd": self.cfg.notional_per_contract_usd,
                       "leverage_factor": self.cfg.leverage_factor, "symbol_map": self.cfg.symbol_map},
            "public_url": self.public_url, "broker_error": st.get("broker_error"),
        }


def serve(port: int = 8790, speed: float = 1.0, open_browser: bool = False) -> None:
    demo = Demo(port, speed)
    demo.start()
    html = (Path(__file__).parent / "dashboard.html").read_bytes()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _auth(self) -> bool:
            tok = self.headers.get("Authorization", "").replace("Bearer", "", 1).strip()
            return tok == demo.cfg.admin_token

        def do_GET(self) -> None:  # noqa: N802
            p = urlparse(self.path)
            if p.path in ("/", "/index.html"):
                return self._send(200, html, "text/html")
            if p.path == "/healthz":
                return self._send(200, json.dumps({"ok": True, "mode": "demo"}).encode())
            if p.path == "/status/public":
                return self._send(200, json.dumps(demo.status_public(), default=str).encode())
            if not self._auth():
                return self._send(401, b'{"detail":"bad admin token"}')
            q = parse_qs(p.query)
            lim = int(q.get("limit", ["50"])[0])
            if p.path == "/status":
                st = demo.engine.status(); st["config"] = demo.cfg.public_dict(); st["public_url"] = demo.public_url
                return self._send(200, json.dumps(st, default=str).encode())
            if p.path == "/admin/alerts":
                return self._send(200, json.dumps(demo.journal.recent_alerts(lim), default=str).encode())
            if p.path == "/admin/orders":
                return self._send(200, json.dumps(demo.journal.recent_orders(lim), default=str).encode())
            if p.path == "/admin/report":
                return self._send(200, json.dumps(demo.journal.tv_vs_paper(lim), default=str).encode())
            if p.path == "/admin/log":
                return self._send(200, json.dumps(demo.journal.recent_log(lim), default=str).encode())
            if p.path == "/admin/config":
                return self._send(200, json.dumps(demo.cfg.public_dict(), default=str).encode())
            self._send(404, b'{"detail":"not found"}')

        def do_POST(self) -> None:  # noqa: N802
            p = urlparse(self.path)
            n = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(n) if n else b""
            if p.path == "/webhook":
                try:
                    a = parse_alert(body, expected_secret=demo.cfg.webhook_secret)
                except AlertParseError as ex:
                    return self._send(200, json.dumps({"ok": False, "error": str(ex)}).encode())
                r = demo.engine.handle_alert(a)
                return self._send(200, json.dumps({"ok": True, "status": r.status, "note": r.note}).encode())
            if not self._auth():
                return self._send(401, b'{"detail":"bad admin token"}')
            data = json.loads(body) if body else {}
            if p.path == "/admin/pause":
                demo.engine.pause(str(data.get("reason", "manual"))); return self._send(200, b'{"ok":true,"paused":true}')
            if p.path == "/admin/resume":
                demo.engine.resume(); return self._send(200, b'{"ok":true,"paused":false}')
            if p.path == "/admin/flatten":
                if not data.get("confirm"):
                    return self._send(400, b'{"detail":"pass {\\"confirm\\": true}"}')
                return self._send(200, json.dumps(demo.engine.flatten_all(str(data.get("reason", "manual"))), default=str).encode())
            if p.path == "/admin/simulate":
                try:
                    a = parse_alert(body)
                except AlertParseError as ex:
                    return self._send(400, json.dumps({"detail": str(ex)}).encode())
                r = demo.engine.handle_alert(a, simulated=True)
                return self._send(200, json.dumps({"status": r.status, "note": r.note, "symbol": r.symbol,
                                                   "target_shares": r.target_shares, "orders": r.orders}, default=str).encode())
            if p.path == "/admin/state":
                demo.journal.set_state(str(data.get("key")), data.get("value")); return self._send(200, b'{"ok":true}')
            self._send(404, b'{"detail":"not found"}')

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"\nICARUS Bridge DEMO  ->  http://127.0.0.1:{port}/   (admin token: demo)  Ctrl+C to stop")
    if open_browser:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        demo._stop.set()
        srv.server_close()


if __name__ == "__main__":
    import sys
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8790)
