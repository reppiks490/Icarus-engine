"""FastAPI app: TradingView webhook receiver + admin API + live dashboard.

  POST /webhook            TradingView posts here (secret inside the JSON body)
  GET  /                   live dashboard (auto-refresh)
  GET  /healthz            liveness (no auth)
  GET  /status             full status JSON        (admin token)
  GET  /admin/alerts       recent alerts            (admin token)
  GET  /admin/orders       recent orders            (admin token)
  GET  /admin/report       TV-vs-paper reality gap  (admin token)
  GET  /admin/log          recent log               (admin token)
  GET  /admin/config       config (secrets masked)  (admin token)
  POST /admin/pause        {"reason": "..."}        (admin token)
  POST /admin/resume                                (admin token)
  POST /admin/flatten      {"confirm": true}        (admin token)
  POST /admin/simulate     alert JSON to inject     (admin token)
  POST /admin/state        {"key":..,"value":..}    (admin token)

The admin token travels as `Authorization: Bearer <ADMIN_TOKEN>`; bind the
server to localhost or put it behind the tunnel with the token kept private.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .config import Settings
from .executor import ExecutionEngine
from .journal import Journal
from .models import AlertParseError, parse_alert

log = logging.getLogger("icarus_bridge")


def build_broker(cfg: Settings):
    if cfg.execution_mode == "shadow":
        from .brokers.shadow import ShadowBroker
        return ShadowBroker(market_open=True)
    from .brokers.alpaca_broker import AlpacaBroker
    return AlpacaBroker(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=cfg.alpaca_paper)


def create_app(cfg: Optional[Settings] = None, broker=None, journal: Optional[Journal] = None) -> FastAPI:
    cfg = cfg or Settings.load()
    journal = journal or Journal(cfg.db_path)
    broker = broker or build_broker(cfg)
    engine = ExecutionEngine(cfg, broker, journal)

    app = FastAPI(title="ICARUS Bridge", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.cfg = cfg
    app.state.engine = engine
    app.state.journal = journal
    app.state.broker = broker
    app.state.public_url = None
    journal.log("INFO", f"bridge started: mode={cfg.execution_mode} broker={getattr(broker, 'name', '?')}")

    # ── equity sampler: one row every 20 s while the broker answers (feeds the equity chart + day P&L) ──
    def _sampler() -> None:
        while True:
            try:
                acct = broker.account()
                eq = float(acct.get("equity") or 0.0)
                unreal = 0.0
                try:
                    unreal = sum(float(p.get("unrealized_pl") or 0.0) for p in broker.positions())
                except Exception:
                    pass
                if eq > 0:
                    journal.add_equity(eq, float(acct.get("cash") or 0.0), unreal)
                    today = time.strftime("%Y-%m-%d")
                    day = journal.get_state("day_start", {}) or {}
                    if day.get("date") != today:
                        journal.set_state("day_start", {"date": today, "equity": eq})
            except Exception:
                pass
            time.sleep(20)
    threading.Thread(target=_sampler, daemon=True, name="equity-sampler").start()

    # ── auth ──
    def admin(authorization: str = Header(default="")) -> None:
        tok = authorization.replace("Bearer", "", 1).strip()
        if not cfg.admin_token or tok != cfg.admin_token:
            raise HTTPException(status_code=401, detail="bad admin token")

    # ── webhook ──
    @app.post("/webhook")
    async def webhook(request: Request):
        body = await request.body()
        client_ip = request.client.host if request.client else ""
        fwd = request.headers.get("x-forwarded-for", "") or request.headers.get("cf-connecting-ip", "")
        src_ip = (fwd.split(",")[0].strip() if fwd else client_ip)
        if cfg.enforce_ip_allowlist and src_ip not in cfg.allowed_ips:
            journal.log("WARN", f"webhook rejected: ip {src_ip} not in allowlist")
            raise HTTPException(status_code=403, detail="source ip not allowed")
        try:
            alert = parse_alert(body, expected_secret=cfg.webhook_secret)
        except AlertParseError as ex:
            journal.log("WARN", f"webhook parse error from {src_ip}: {ex} | body={body[:300]!r}")
            # 200 so TradingView doesn't disable the alert after repeated failures; the reason is journaled
            return JSONResponse({"ok": False, "error": str(ex)}, status_code=200)
        res = engine.handle_alert(alert)
        return {"ok": res.status in ("executed", "partial", "journaled", "duplicate"), "status": res.status,
                "note": res.note, "symbol": res.symbol, "target_shares": res.target_shares}

    # ── health / status ──
    @app.get("/healthz")
    def healthz():
        return {"ok": True, "mode": cfg.execution_mode, "paused": engine.paused(), "ts": time.time()}

    @app.get("/status", dependencies=[Depends(admin)])
    def status():
        st = engine.status()
        st["public_url"] = app.state.public_url
        st["config"] = cfg.public_dict()
        st["recent_alerts"] = journal.recent_alerts(15)
        st["recent_orders"] = journal.recent_orders(15)
        return st

    @app.get("/status/public")
    def status_public():
        """Dashboard feed — no secrets, no token (bind to localhost or accept that it's readable)."""
        st = engine.status()
        acct = st.get("account") or {}
        day = journal.get_state("day_start", {}) or {}
        gap = journal.tv_vs_paper(60)
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
            "alerts": journal.recent_alerts(25), "orders": journal.recent_orders(25), "log": journal.recent_log(40),
            "equity_series": journal.equity_series(86400.0), "counts_today": journal.counts_today(),
            "gap": {"n": len(gap), "latency": lat[-40:], "slippage_bps": slip[-40:],
                    "median_latency_sec": (lat[len(lat) // 2] if lat else None),
                    "median_slippage_bps": (slip[len(slip) // 2] if slip else None),
                    "rows": gap[:12]},
            "limits": {"max_position_shares": cfg.max_position_shares, "daily_loss_limit_usd": cfg.daily_loss_limit_usd,
                       "sizing_mode": cfg.sizing_mode, "notional_per_contract_usd": cfg.notional_per_contract_usd,
                       "leverage_factor": cfg.leverage_factor, "symbol_map": cfg.symbol_map},
            "public_url": app.state.public_url or journal.get_state("public_url"), "broker_error": st.get("broker_error"),
        }

    # ── admin ──
    @app.get("/admin/alerts", dependencies=[Depends(admin)])
    def alerts(limit: int = 50):
        return journal.recent_alerts(limit)

    @app.get("/admin/orders", dependencies=[Depends(admin)])
    def orders(limit: int = 50):
        return journal.recent_orders(limit)

    @app.get("/admin/report", dependencies=[Depends(admin)])
    def report(limit: int = 200):
        return journal.tv_vs_paper(limit)

    @app.get("/admin/log", dependencies=[Depends(admin)])
    def logs(limit: int = 100):
        return journal.recent_log(limit)

    @app.get("/admin/config", dependencies=[Depends(admin)])
    def config():
        return cfg.public_dict()

    @app.post("/admin/pause", dependencies=[Depends(admin)])
    async def pause(request: Request):
        body = await _json(request)
        engine.pause(str(body.get("reason", "manual")))
        return {"ok": True, "paused": True}

    @app.post("/admin/resume", dependencies=[Depends(admin)])
    def resume():
        engine.resume()
        return {"ok": True, "paused": False}

    @app.post("/admin/flatten", dependencies=[Depends(admin)])
    async def flatten(request: Request):
        body = await _json(request)
        if not body.get("confirm"):
            raise HTTPException(status_code=400, detail="pass {\"confirm\": true}")
        return engine.flatten_all(str(body.get("reason", "manual")))

    @app.post("/admin/simulate", dependencies=[Depends(admin)])
    async def simulate(request: Request):
        body = await request.body()
        try:
            alert = parse_alert(body)   # secret not required on the admin path
        except AlertParseError as ex:
            raise HTTPException(status_code=400, detail=str(ex))
        res = engine.handle_alert(alert, simulated=True)
        return {"status": res.status, "note": res.note, "symbol": res.symbol, "target_shares": res.target_shares,
                "orders": res.orders}

    @app.post("/admin/state", dependencies=[Depends(admin)])
    async def set_state(request: Request):
        body = await _json(request)
        key = str(body.get("key", "")).strip()
        if not key or key in ("paused",):
            raise HTTPException(status_code=400, detail="bad key")
        journal.set_state(key, body.get("value"))
        return {"ok": True, "key": key, "value": body.get("value")}

    # ── dashboard ──
    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")

    return app


async def _json(request: Request) -> Dict[str, Any]:
    try:
        raw = await request.body()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")
