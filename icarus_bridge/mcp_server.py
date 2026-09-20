"""MCP (stdio) control surface for the running bridge.

Register with Claude Code:
  claude mcp add icarus-bridge -e ICARUS_BRIDGE_URL=http://127.0.0.1:8787 -e ICARUS_ADMIN_TOKEN=<token> -- <python> -m icarus_bridge.mcp_server

Every tool is a thin call to the bridge's admin API, so the daemon stays the
single source of truth and Claude can never race the webhook thread.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import httpx
from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("ICARUS_BRIDGE_URL", "http://127.0.0.1:8787").rstrip("/")
TOKEN = os.environ.get("ICARUS_ADMIN_TOKEN", "")

mcp = FastMCP(
    "icarus-bridge",
    instructions=(
        "Control surface for the ICARUS Bridge: a local daemon that receives TradingView strategy "
        "webhooks and mirrors them onto an Alpaca PAPER account (NQ signals → QQQ proxy). Read tools are "
        "safe. pause_trading / resume_trading / flatten_all / simulate_alert change live paper state — "
        "confirm with the user before calling them unless they asked for exactly that action."
    ),
)


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=20.0, headers={"Authorization": f"Bearer {TOKEN}"})


def _get(path: str, **params: Any) -> Any:
    with _client() as c:
        r = c.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()


def _post(path: str, body: Optional[Dict[str, Any]] = None, raw: Optional[str] = None) -> Any:
    with _client() as c:
        r = c.post(path, content=raw if raw is not None else json.dumps(body or {}),
                   headers={"Content-Type": "application/json"})
        if r.status_code >= 400:
            return {"error": r.status_code, "detail": r.text}
        return r.json()


def _safe(fn):
    try:
        return fn()
    except httpx.ConnectError:
        return {"error": f"bridge not reachable at {BASE} — start it with: icarus-bridge serve"}
    except httpx.HTTPStatusError as ex:
        return {"error": ex.response.status_code, "detail": ex.response.text}
    except Exception as ex:  # noqa: BLE001
        return {"error": f"{type(ex).__name__}: {ex}"}


# ── read tools ──
@mcp.tool()
def bridge_status() -> dict:
    """Health + account + positions + resting orders + last alert age + pause state of the bridge."""
    return _safe(lambda: _get("/status"))


@mcp.tool()
def list_alerts(limit: int = 30) -> list:
    """Recent TradingView alerts as received (parsed fields, mapping, execution status, note)."""
    return _safe(lambda: _get("/admin/alerts", limit=limit))


@mcp.tool()
def list_orders(limit: int = 30) -> list:
    """Recent paper orders the bridge placed (kind, purpose, fill price, status)."""
    return _safe(lambda: _get("/admin/orders", limit=limit))


@mcp.tool()
def positions() -> dict:
    """Current paper positions and open orders straight from the broker."""
    def run():
        st = _get("/status")
        return {"positions": st.get("positions"), "open_orders": st.get("open_orders"),
                "symbol_state": st.get("symbol_state"), "market": st.get("market")}
    return _safe(run)


@mcp.tool()
def reality_gap_report(limit: int = 100) -> dict:
    """TV-vs-paper report: for each strategy fill, the paper fill(s) it produced, latency, and slippage.
    Use it to judge how honest the TradingView backtest fills are versus real paper execution."""
    def run():
        rows = _get("/admin/report", limit=limit)
        lat = [r["latency_sec"] for r in rows if r.get("latency_sec") is not None]
        summary = {"fills": len(rows), "with_paper_fill": sum(1 for r in rows if r.get("paper_fill_avg")),
                   "median_latency_sec": (sorted(lat)[len(lat) // 2] if lat else None),
                   "max_latency_sec": (max(lat) if lat else None)}
        return {"summary": summary, "rows": rows}
    return _safe(run)


@mcp.tool()
def recent_log(limit: int = 60) -> list:
    """Bridge log lines (INFO/WARN/ERROR), newest first."""
    return _safe(lambda: _get("/admin/log", limit=limit))


@mcp.tool()
def get_config() -> dict:
    """Effective bridge configuration (secrets masked): mode, symbol map, sizing, risk limits."""
    return _safe(lambda: _get("/admin/config"))


# ── control tools (state-changing) ──
@mcp.tool()
def pause_trading(reason: str = "paused via MCP") -> dict:
    """Stop acting on new alerts (they are still journaled). Existing positions/stops are untouched."""
    return _safe(lambda: _post("/admin/pause", {"reason": reason}))


@mcp.tool()
def resume_trading() -> dict:
    """Resume acting on alerts after a pause (manual or daily-loss breaker)."""
    return _safe(lambda: _post("/admin/resume"))


@mcp.tool()
def flatten_all(confirm: bool = False, reason: str = "flatten via MCP") -> dict:
    """EMERGENCY: cancel every open order and close every paper position. Requires confirm=true."""
    if not confirm:
        return {"error": "refused: call again with confirm=true"}
    return _safe(lambda: _post("/admin/flatten", {"confirm": True, "reason": reason}))


@mcp.tool()
def simulate_alert(side: str = "long", contracts: float = 5, position_after: Optional[float] = None,
                   ticker: str = "NQ1!", order_price: float = 20000.0, order_id: str = "", comment: str = "",
                   system: str = "RATE", tp1: float = 15, tp2: float = 30, sl: float = 45, q1: float = 2, q2: float = 3,
                   raw_json: str = "") -> dict:
    """Inject a synthetic TradingView order-fill alert into the pipeline (bypasses the webhook secret).
    Either pass raw_json (exactly what TradingView would send) or describe the fill:
      side=long/short, contracts=fill size, position_after=signed position AFTER the fill (default = ±contracts).
    In shadow mode nothing leaves the machine; in mirror/bracket mode this places REAL paper orders."""
    if raw_json.strip():
        return _safe(lambda: _post("/admin/simulate", raw=raw_json))
    pos = position_after if position_after is not None else (contracts if side == "long" else -contracts)
    mp = "flat" if abs(pos) < 1e-9 else ("long" if pos > 0 else "short")
    payload = {
        "event": "order_fill", "ticker": ticker, "action": "buy" if side == "long" else "sell",
        "contracts": str(contracts), "order_id": order_id or ("Long" if side == "long" else "Short"),
        "comment": comment, "order_price": str(order_price), "position_size": str(abs(pos)),
        "market_position": mp, "prev_market_position": "flat" if abs(pos) >= abs(contracts) - 1e-9 else mp,
        "bar_close": str(order_price), "time": "simulated",
        "meta": f"sys={system};side={side};tp1={tp1};tp2={tp2};sl={sl};q1={q1};q2={q2};ref={order_price}",
    }
    return _safe(lambda: _post("/admin/simulate", raw=json.dumps(payload)))


@mcp.tool()
def set_state(key: str, value: str) -> dict:
    """Write a runtime state key in the bridge journal (e.g. notes). 'paused' is reserved — use pause/resume."""
    try:
        val: Any = json.loads(value)
    except json.JSONDecodeError:
        val = value
    return _safe(lambda: _post("/admin/state", {"key": key, "value": val}))


@mcp.resource("icarus://status")
def status_resource() -> str:
    """Live bridge status as JSON."""
    return json.dumps(_safe(lambda: _get("/status")), indent=2, default=str)


def main() -> None:
    mcp.run()   # stdio transport


if __name__ == "__main__":
    main()
