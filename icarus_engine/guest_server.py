"""Capability-limited guest gateway for ICARUS.

The guest surface is intentionally separate from the live dashboard/server:
- live ICARUS state is read-only;
- guest input/preset changes live only in this process's in-memory workspace;
- backtest/"rewarm" actions schedule isolated replay jobs against frozen cached bars;
- every live admin/execution/research mutation route is denied here.

The server binds loopback only. A tunnel such as cloudflared may expose this
port, while the opaque capability token remains part of the path. Never reuse
the ICARUS admin token as the guest token.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .backtest import JOBS, start_job, validate_backtest_params
from .runtime import preset_path, validate_values

_MAX_BODY_BYTES = 128 * 1024
_MIN_TOKEN_LEN = 24
_DENIED_DETAIL = "guest access is isolated from live Icarus"


class GuestWorkspace:
    """Ephemeral guest-only experiment state.

    Nothing here writes inputs files, mutates AssetRunner inputs/configuration,
    or calls Portfolio mutators. A process restart intentionally clears it.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._inputs: Dict[str, Dict[str, Any]] = {}
        self._presets: Dict[str, Optional[str]] = {}

    def state(self, asset: str) -> Dict[str, Any]:
        sym = asset.upper()
        with self._lock:
            return {
                "asset": sym,
                "inputs": dict(self._inputs.get(sym, {})),
                "preset": self._presets.get(sym),
                "isolated": True,
            }

    def patch_inputs(self, asset: str, values: Dict[str, Any]) -> Dict[str, Any]:
        sym = asset.upper()
        vals = dict(values)
        validate_values(vals)
        with self._lock:
            merged = dict(self._inputs.get(sym, {}))
            merged.update(vals)
            self._inputs[sym] = merged
        return self.state(sym)

    def set_preset(self, asset: str, preset: Optional[str]) -> Dict[str, Any]:
        sym = asset.upper()
        with self._lock:
            self._presets[sym] = preset or None
        return self.state(sym)

    def reset(self, asset: str) -> Dict[str, Any]:
        sym = asset.upper()
        with self._lock:
            self._inputs.pop(sym, None)
            self._presets.pop(sym, None)
        return self.state(sym)


def _guest_asset_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Project only operator-safe fields; omit provenance, logs, internals and controls."""
    allowed = (
        "symbol", "name", "product", "contract", "next_contract", "session_mode",
        "tf", "mintick", "contract_size", "multiplier", "chart_type", "price",
        "price_age", "feed_delay", "warm", "rewarming", "bar_age", "last_bar_ts",
        "market", "equity", "capital", "netprofit", "open_profit", "position",
        "open_trades", "exits", "trades_total", "wins_total", "live_trades",
        "live_profit",
    )
    out = {k: summary.get(k) for k in allowed if k in summary}
    state = summary.get("state") or {}
    out["state"] = {k: state.get(k) for k in (
        "rate_regime_str", "rate_avg_price", "tp1_price", "tp2_price", "sl_price",
        "daily_pnl", "entry_allowed", "in_session",
    ) if k in state}
    return out


def _public_status(port) -> Dict[str, Any]:
    raw = port.status()
    return {
        "mode": "guest-sandbox",
        "isolated": True,
        "now": raw.get("now"),
        "uptime_sec": raw.get("uptime_sec"),
        "equity": raw.get("equity"),
        "capital": raw.get("capital"),
        "net": raw.get("net"),
        "live_profit": raw.get("live_profit"),
        "open_profit": raw.get("open_profit"),
        "positions": raw.get("positions"),
        "all_warm": raw.get("all_warm"),
        "assets": [_guest_asset_summary(a) for a in raw.get("assets", [])],
    }


def _asset(port, symbol: str):
    return port.runners.get((symbol or "").upper())


def _validate_preset(port, value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("preset must be a string")
    path = preset_path(port.base_dir, value)
    if not os.path.isfile(path):
        raise FileNotFoundError(value)
    return value


def _read_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    raw_len = handler.headers.get("Content-Length", "0")
    try:
        length = int(raw_len)
    except ValueError:
        raise ValueError("invalid Content-Length") from None
    if length < 0 or length > _MAX_BODY_BYTES:
        raise ValueError("request body too large")
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("body must be a JSON object") from None
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    return body


def serve(port, http_port: int = 8792, *, guest_token: str, start: bool = True):
    """Serve the isolated guest surface on loopback.

    This takes a Portfolio only as a read source and as the source passed to the
    already-isolated backtest scheduler. It never invokes live admin mutators.
    """
    if not isinstance(guest_token, str) or len(guest_token) < _MIN_TOKEN_LEN or "/" in guest_token:
        raise ValueError(f"guest token must be at least {_MIN_TOKEN_LEN} characters and contain no slash")

    workspace = GuestWorkspace()

    class H(BaseHTTPRequestHandler):
        server_version = "icarus-guest"
        sys_version = ""
        timeout = 30

        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, allow_nan=False, default=str).encode("utf-8"))

        def _route(self) -> Optional[Tuple[str, str]]:
            path = urlparse(self.path).path
            parts = path.split("/")
            if len(parts) < 3 or parts[1] != "g":
                return None
            supplied = parts[2]
            if not hmac.compare_digest(supplied, guest_token):
                return None
            inner = "/" + "/".join(parts[3:]) if len(parts) > 3 else "/"
            return supplied, inner

        def _require_asset(self, body: Dict[str, Any]):
            raw = body.get("asset")
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError("asset is required")
            sym = raw.strip().upper()
            runner = _asset(port, sym)
            if runner is None:
                raise KeyError(sym)
            return sym, runner

        def _denied(self) -> None:
            self._json(403, {"detail": _DENIED_DETAIL})

        def do_GET(self) -> None:  # noqa: N802
            routed = self._route()
            if routed is None:
                return self._json(404, {"detail": "not found"})
            _, path = routed
            q = parse_qs(urlparse(self.path).query)

            if path in ("/", "/api/live/status"):
                return self._json(200, _public_status(port))

            if path.startswith("/api/live/chart/"):
                sym = path.rsplit("/", 1)[1].upper()
                runner = _asset(port, sym)
                if runner is None:
                    return self._json(404, {"detail": "unknown asset"})
                try:
                    n = max(20, min(800, int(q.get("n", [240])[0])))
                except (TypeError, ValueError):
                    n = 240
                return self._json(200, runner.chart(n))

            if path.startswith("/api/live/trades/"):
                sym = path.rsplit("/", 1)[1].upper()
                runner = _asset(port, sym)
                if runner is None:
                    return self._json(404, {"detail": "unknown asset"})
                try:
                    limit = max(1, min(500, int(q.get("limit", [100])[0])))
                except (TypeError, ValueError):
                    limit = 100
                return self._json(200, {"asset": sym, "trades": runner.trades(limit)})

            if path.startswith("/api/experiment/state/"):
                sym = path.rsplit("/", 1)[1].upper()
                runner = _asset(port, sym)
                if runner is None:
                    return self._json(404, {"detail": "unknown asset"})
                state = workspace.state(sym)
                base = runner.inputs.to_dict()
                effective = dict(base)
                effective.update(state["inputs"])
                state.update({"base": base, "effective": effective})
                return self._json(200, state)

            if path == "/api/experiment/presets":
                root = os.path.join(port.base_dir, "presets")
                names = []
                if os.path.isdir(root):
                    names = sorted(f[:-5] for f in os.listdir(root) if f.endswith(".json"))
                return self._json(200, {"presets": names})

            if path.startswith("/api/experiment/jobs/"):
                job_id = path.rsplit("/", 1)[1]
                job = JOBS.get(job_id)
                if not job:
                    return self._json(404, {"detail": "unknown job"})
                return self._json(200, job)

            return self._json(404, {"detail": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            routed = self._route()
            if routed is None:
                return self._json(404, {"detail": "not found"})
            _, path = routed

            # Belt-and-suspenders deny: no live/admin mutation namespace is
            # routable through this server, regardless of future UI changes.
            if path.startswith("/admin/") or not path.startswith("/api/experiment/"):
                return self._denied()

            try:
                body = _read_body(self)
                sym, _runner = self._require_asset(body)

                if path == "/api/experiment/inputs":
                    values = body.get("values")
                    if not isinstance(values, dict):
                        raise ValueError("values must be an object")
                    return self._json(200, workspace.patch_inputs(sym, values))

                if path == "/api/experiment/reset":
                    return self._json(200, workspace.reset(sym))

                if path == "/api/experiment/preset":
                    preset = _validate_preset(port, body.get("preset"))
                    return self._json(200, workspace.set_preset(sym, preset))

                if path in ("/api/experiment/backtest", "/api/experiment/rewarm"):
                    state = workspace.state(sym)
                    params = {k: v for k, v in body.items() if k != "asset"}
                    request_inputs = params.pop("inputs", None)
                    if request_inputs is not None and not isinstance(request_inputs, dict):
                        raise ValueError("inputs must be an object")
                    merged_inputs = dict(state["inputs"])
                    if request_inputs:
                        merged_inputs.update(request_inputs)
                    if merged_inputs:
                        params["inputs"] = merged_inputs
                    if state.get("preset") and "preset" not in params:
                        params["preset"] = state["preset"]
                    if params.get("preset") not in (None, ""):
                        _validate_preset(port, params.get("preset"))
                    params = validate_backtest_params(params)
                    scheduled = {"asset": sym, **params}
                    job_id = start_job(port, scheduled)
                    payload = {"ok": True, "job": job_id, "asset": sym, "isolated": True}
                    if path.endswith("/rewarm"):
                        payload["note"] = "isolated replay rewarm started; live Icarus is unchanged"
                    else:
                        payload["note"] = "isolated backtest started; live Icarus is unchanged"
                    return self._json(200, payload)

                return self._denied()

            except FileNotFoundError as ex:
                return self._json(404, {"detail": f"preset {ex.args[0]} not found"})
            except KeyError as ex:
                return self._json(404, {"detail": f"unknown asset {ex.args[0]}"})
            except (ValueError, TypeError, OverflowError) as ex:
                return self._json(400, {"detail": str(ex)})

    srv = ThreadingHTTPServer(("127.0.0.1", http_port), H)
    srv.daemon_threads = True
    srv.workspace = workspace
    srv.guest_token = guest_token
    if not start:
        return srv
    srv.serve_forever()
