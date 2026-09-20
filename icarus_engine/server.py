"""Dashboard + JSON API for the engine (standard library only).

  GET  /                          dashboard (open /?asset=NQ for a single-asset tab)
  GET  /status/public             portfolio + every asset's strategy state
  GET  /api/chart/<SYM>?n=240     bars, overlays (RATE line, TP/SL, VWAP, Kalman), fills
  GET  /api/trades/<SYM>          closed trades (this run: history + live)
  GET  /api/inputs/<SYM>          effective inputs, their sources, and per-input metadata
  GET  /api/input-meta            every input: label, group, kind, default, range, options, tooltip
  GET  /api/presets               presets/*.json (name + _meta)
  GET  /api/assets                asset registry (what can be added)
  GET  /api/commands              the command list the dashboard palette renders
  GET  /api/export/<SYM>.csv      the asset's trade list as CSV
  GET  /healthz
  POST /admin/pause | /admin/resume        {"asset": "NQ"} or all          (Bearer token)
  POST /admin/flatten                      {"confirm": true, "asset"?: "NQ"}
  POST /admin/inputs                       {"asset": "NQ"|"*", "values": {...}, "persist": true}  → re-warm
  POST /admin/inputs/reset                 {"asset": "NQ"}  (deletes inputs.<SYM>.json, re-warm)
  POST /admin/preset                       {"asset": "NQ", "preset": "NQ-10m-original"|null}
  POST /admin/assets/add                   {"symbol": "GC", "tf": "20", "preset"?: ...}
  POST /admin/assets/remove                {"symbol": "GC"}
  POST /admin/rewarm                       {"asset": "NQ"}
"""
from __future__ import annotations

import hmac
import json
import os
import re
import threading
from contextlib import ExitStack
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .assets import REGISTRY, parse_spec
from .backtest import JOBS, start_job
from .parity import compare_lists, engine_trades_from_rows, read_tv_trades_text
from .runtime import Portfolio, _read_json, preset_path
from .strategy.meta import load_meta
from .advisory import MAX_BODY_BYTES, strict_json
from .research_service import ResearchWorkspace


def _no_json_constants(name: str):
    raise ValueError(f"{name} is not allowed")


def _reason(body: Dict[str, Any], default: str = "manual") -> str:
    """Free text that ends up in the journal: printable, short."""
    return re.sub(r"[^\w .:()/-]", "", str(body.get("reason", default)))[:40] or default

COMMANDS = [
    {"id": "backtest", "label": "Backtest (Strategy Tester)", "desc": "Run the strategy on the cached bars with any preset / inputs / fill mode and read TradingView's Strategy Tester numbers.", "scope": "asset", "danger": False},
    {"id": "pause", "label": "Pause entries", "desc": "No new entries on the selected asset (or all). Exits keep running.", "scope": "asset|all", "danger": False},
    {"id": "resume", "label": "Resume entries", "desc": "Lift a pause.", "scope": "asset|all", "danger": False},
    {"id": "flatten", "label": "Flatten", "desc": "Close every open paper position now, at the last price.", "scope": "asset|all", "danger": True},
    {"id": "rewarm", "label": "Re-warm", "desc": "Rebuild the asset's engine from the cached history (after editing inputs).", "scope": "asset", "danger": False},
    {"id": "inputs", "label": "Edit inputs", "desc": "Open the Inputs tab for the asset.", "scope": "asset", "danger": False},
    {"id": "preset", "label": "Apply preset", "desc": "Load one of the presets/ configurations onto the asset and re-warm.", "scope": "asset", "danger": False},
    {"id": "reset-inputs", "label": "Reset asset overrides", "desc": "Delete inputs.<SYM>.json so the asset falls back to the preset.", "scope": "asset", "danger": True},
    {"id": "add-asset", "label": "Add asset", "desc": "Start a new asset (NQ ES YM GC SI PL PA BTCF MBT BTC ETH SOL …).", "scope": "all", "danger": False},
    {"id": "remove-asset", "label": "Remove asset", "desc": "Stop and drop an asset from the engine.", "scope": "asset", "danger": True},
    {"id": "export", "label": "Export trades CSV", "desc": "Download the asset's trade list (TradingView-like columns).", "scope": "asset", "danger": False},
    {"id": "open-tab", "label": "Open in its own tab", "desc": "Full-screen view of one asset in a new browser tab.", "scope": "asset", "danger": False},
    {"id": "theme", "label": "Toggle theme", "desc": "Dark / light.", "scope": "all", "danger": False},
]


def serve(port: Portfolio, http_port: int = 8791, token: str = "icarus", start: bool = True):
    html_path = Path(__file__).parent / "dashboard.html"
    meta = load_meta()
    research = ResearchWorkspace(port)

    class H(BaseHTTPRequestHandler):
        server_version = "icarus"
        sys_version = ""
        timeout = 30                                              # idle connections must not hold a thread forever

        def log_message(self, *a: Any) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: Dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src https://www.youtube-nocookie.com; frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, allow_nan=False, default=str).encode("utf-8"))

        def _host_ok(self) -> bool:
            """Loopback only: a DNS-rebinding page carries its own hostname in Host."""
            host = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]").lower()
            return host in ("127.0.0.1", "localhost", "::1")

        def _auth(self) -> bool:
            scheme, _, tok = self.headers.get("Authorization", "").partition(" ")
            return bool(token) and scheme.lower() == "bearer" and hmac.compare_digest(tok, token)

        def _int(self, q: Dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
            try:
                return max(lo, min(hi, int(q.get(key, [default])[0])))
            except (TypeError, ValueError):
                return default

        def _runner(self, sym: str):
            return port.runners.get((sym or "").upper())

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._json(403, {"detail": "bad host"})
            p = urlparse(self.path)
            q = parse_qs(p.query)
            if p.path == "/":
                return self._send(200, html_path.read_bytes(), "text/html")
            if p.path == "/research-ui.js":
                return self._send(200, (html_path.parent / "research-ui.js").read_bytes(), "text/javascript")
            if p.path == "/sources-ui.js":
                return self._send(200, (html_path.parent / "sources-ui.js").read_bytes(), "text/javascript")
            if p.path in ("/experience-ui.js", "/experience-ui.css"):
                ctype = "text/javascript" if p.path.endswith(".js") else "text/css"
                return self._send(200, (html_path.parent / p.path[1:]).read_bytes(), ctype)
            if p.path == "/healthz":
                return self._json(200, {"ok": True, "assets": list(port.order), "warm": all(r.warm for r in port.runners.values()) if port.runners else False})
            if p.path == "/status/public":
                return self._json(200, port.status())
            if p.path == "/api/input-meta":
                return self._json(200, meta)
            if p.path.startswith("/api/research"):
                if not self._auth():
                    return self._json(401, {"detail": "bad admin token"})
                try:
                    if p.path == "/api/research":
                        return self._json(200, research.status())
                    if p.path == "/api/research/adaptation":
                        return self._json(200, research.adaptation.status())
                    if p.path == "/api/research/source-watch":
                        return self._json(200, research.source_watch.status())
                    if p.path == "/api/research/events":
                        return self._json(200, research.events(q.get("asset", [""])[0]))
                    if p.path == "/api/research/analysis":
                        return self._json(200, research.analysis.status())
                    if p.path.startswith("/api/research/analysis/"):
                        return self._json(200, research.analysis.job(p.path.rsplit("/", 1)[1]))
                    if p.path == "/api/research/activation":
                        return self._json(200, research.activation.status())
                    if p.path == "/api/research/sources":
                        return self._json(200, research.market_sources.status())
                    if p.path == "/api/research/records":
                        return self._json(200, research.market_sources.records(kind=q.get("kind", ["asset"])[0],
                            asset=q.get("asset", [None])[0], cik=q.get("cik", [None])[0],
                            limit=int(q.get("limit", ["100"])[0])))
                    if p.path.startswith("/api/research/jobs/"):
                        return self._json(200, research.job(p.path.rsplit("/", 1)[1]))
                    if p.path.startswith("/api/research/proposals/"):
                        return self._json(200, research.ledger.get_proposal(p.path.rsplit("/", 1)[1]))
                except (ValueError, TypeError, KeyError) as ex:
                    return self._json(400, {"detail": str(ex)})
                return self._json(404, {"detail": "unknown research resource"})
            if p.path == "/api/presets":
                out = []
                pdir = os.path.join(port.base_dir, "presets")
                if os.path.isdir(pdir):
                    for f in sorted(os.listdir(pdir)):
                        if f.endswith(".json"):
                            d = _read_json(os.path.join(pdir, f))
                            out.append({"name": f[:-5], "meta": d.get("_meta", {}), "count": len([k for k in d if not k.startswith("_")])})
                return self._json(200, out)
            if p.path == "/api/assets":
                return self._json(200, {"registry": [{"symbol": s.symbol, "name": s.name, "feed": s.feed, "calendar": s.calendar, "mintick": s.mintick, "multiplier": s.multiplier, "kind": s.kind} for s in REGISTRY.values()],
                                        "running": list(port.order)})
            if p.path == "/api/commands":
                return self._json(200, COMMANDS)
            if p.path.startswith("/api/export/"):
                r = self._runner(p.path.rsplit("/", 1)[1].replace(".csv", ""))
                if not r:
                    return self._json(404, {"error": "unknown asset"})
                return self._send(200, r.export_csv().encode("utf-8"), "text/csv", {"Content-Disposition": f'attachment; filename="{r.symbol}_trades.csv"'})
            if p.path.startswith("/api/chart/"):
                r = self._runner(p.path.rsplit("/", 1)[1])
                if not r:
                    return self._json(404, {"error": "unknown asset"})
                return self._json(200, r.chart(self._int(q, "n", 240, 20, 800)))
            if p.path.startswith("/api/trades/"):
                r = self._runner(p.path.rsplit("/", 1)[1])
                if not r:
                    return self._json(404, {"error": "unknown asset"})
                return self._json(200, r.trades(self._int(q, "limit", 100, 1, 2000)))
            if p.path.startswith("/api/backtest/"):
                rest = p.path[len("/api/backtest/"):]
                job_id, _, tail = rest.partition("/")
                job = JOBS.get(job_id)
                if not job:
                    return self._json(404, {"error": "unknown backtest job"})
                if tail == "trades.csv":
                    if job["status"] != "done":
                        return self._json(409, {"error": "not finished"})
                    return self._send(200, job["result"]["csv"].encode("utf-8"), "text/csv",
                                      {"Content-Disposition": f'attachment; filename="backtest_{job["result"]["asset"]}_{job_id}.csv"'})
                out = {k: job[k] for k in ("id", "status", "progress", "started", "params", "error")}
                out["finished"] = job.get("finished")
                if job["status"] == "done" and q.get("full", ["1"])[0] != "0":
                    out["result"] = {k: v for k, v in job["result"].items() if k != "csv"}
                return self._json(200, out)
            if p.path.startswith("/api/inputs/"):
                r = self._runner(p.path.rsplit("/", 1)[1])
                if not r:
                    return self._json(404, {"error": "unknown asset"})
                over = _read_json(os.path.join(port.base_dir, f"inputs.{r.symbol}.json"))
                return self._json(200, {"asset": r.symbol, "effective": r.inputs.to_dict(), "base": r.inputs_base.to_dict(), "sources": r.cfg.sources,
                                        "overrides": {k: v for k, v in over.items() if not k.startswith("_")}, "preset": r.cfg.preset, "pts_scale": r.pts_scale})
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._json(403, {"detail": "bad host"})
            p = urlparse(self.path)
            if p.path == "/research/events":
                secret = os.environ.get("ICARUS_INGEST_SECRET", "")
                if not secret:
                    return self._json(503, {"detail": "event receiver is not configured"})
                if not self.headers.get("X-Icarus-Signature") or not self.headers.get("X-Icarus-Timestamp"):
                    return self._json(401, {"detail": "signed event required"})
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    if not 0 < n <= MAX_BODY_BYTES or self.headers.get("Transfer-Encoding"):
                        return self._json(413, {"detail": "invalid event body length"})
                    event = research.ledger.ingest_signed_event(self.rfile.read(n), self.headers["X-Icarus-Timestamp"],
                                                                self.headers["X-Icarus-Signature"], secret)
                    return self._json(200, {"ok": True, "event_id": event["event_id"], "execution_authorized": False})
                except (ValueError, TypeError) as ex:
                    return self._json(400, {"detail": str(ex)})
            if not p.path.startswith("/admin/"):
                return self._json(404, {"error": "not found"})
            if not self._auth():                                  # authenticate BEFORE reading any body
                return self._json(401, {"detail": "bad admin token"})
            try:
                n = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                return self._json(400, {"detail": "bad Content-Length"})
            if n < 0 or n > (1 << 20):
                return self._json(413, {"detail": "body too large"})
            raw = self.rfile.read(n) if n else b""
            try:
                body = strict_json(raw) if p.path.startswith("/admin/research/") else (json.loads(raw, parse_constant=_no_json_constants) if raw else {})
            except ValueError as ex:
                return self._json(400, {"detail": f"bad JSON body: {ex}"})
            if not isinstance(body, dict):
                return self._json(400, {"detail": "JSON body must be an object"})
            asset = str(body.get("asset") or body.get("symbol") or "").upper()
            targets = [self._runner(asset)] if asset and asset != "*" else list(port.runner_list())
            if asset and asset != "*" and targets == [None]:
                return self._json(404, {"detail": f"unknown asset {asset}"})
            try:
                if p.path == "/admin/research/studies":
                    return self._json(200, research.start(body))
                if p.path == "/admin/research/adaptation":
                    return self._json(200, research.configure_adaptation(body))
                if p.path == "/admin/research/source-watch":
                    return self._json(200, research.configure_source_watch(body))
                if p.path == "/admin/research/cancel":
                    return self._json(200, research.cancel(body.get("job")))
                if p.path == "/admin/research/proposals":
                    return self._json(200, research.propose_study(body))
                if p.path == "/admin/research/export":
                    candidate = research.export(body.get("proposal_id"))
                    return self._json(200, candidate)
                if p.path == "/admin/research/analysis":
                    return self._json(200, research.analysis.start(body))
                if p.path == "/admin/research/analysis/cancel":
                    if set(body) != {"id"}:
                        raise ValueError("analysis cancellation requires id only")
                    return self._json(200, research.analysis.journal.cancel(body["id"]))
                if p.path == "/admin/research/activate":
                    return self._json(200, research.activate(body))
                if p.path == "/admin/research/rollback":
                    return self._json(200, research.rollback(body))
                if p.path == "/admin/research/recover":
                    return self._json(200, research.recover(body))
                if p.path == "/admin/research/collect":
                    if not {"source"} <= set(body) or set(body) - {"source", "options"}:
                        raise ValueError("collection requires source and optional options")
                    return self._json(200, research.market_sources.collect(body["source"], body.get("options")))
                if p.path == "/admin/pause":
                    for r in targets:
                        r.set_paused(True)
                    if not asset or asset == "*":
                        port.paused = True
                    port.journal.log("WARN", f"PAUSED {asset or 'ALL'}: {_reason(body)}")
                    return self._json(200, {"ok": True, "note": f"paused {asset or 'all'} - no new entries"})
                if p.path == "/admin/resume":
                    for r in targets:
                        r.set_paused(False)
                    if not asset or asset == "*":
                        port.paused = False
                    port.journal.log("INFO", f"RESUMED {asset or 'ALL'}")
                    return self._json(200, {"ok": True, "note": f"resumed {asset or 'all'}"})
                if p.path == "/admin/flatten":
                    if not body.get("confirm"):
                        return self._json(400, {"detail": "pass {\"confirm\": true}"})
                    closed = {r.symbol: r.flatten(_reason(body, "dashboard")) for r in targets}
                    return self._json(200, {"ok": True, "closed": closed, "note": f"flattened {sum(closed.values())} position(s)"})
                if p.path in ("/admin/inputs", "/admin/inputs/reset", "/admin/preset", "/admin/rewarm"):
                    from .runtime import resolve_inputs as _resolve
                    vals = body.get("values", {}) if p.path == "/admin/inputs" else None
                    if vals is not None and not isinstance(vals, dict):
                        raise ValueError("values must be an object")
                    kwargs = {}
                    if p.path == "/admin/preset":
                        name = body.get("preset") or None
                        if name and not os.path.exists(preset_path(port.base_dir, str(name))):
                            return self._json(404, {"detail": f"preset {name} not found"})
                        kwargs["preset"] = name
                    reset = p.path == "/admin/inputs/reset"
                    with ExitStack() as locks:
                        # Hold every target from preflight through replay: no fill
                        # may race between acceptance and a later worker thread.
                        for r in sorted(targets, key=lambda r: r.symbol):
                            locks.enter_context(r.lock)
                            r.ensure_configurable()
                        for r in targets:
                            sp = replace(r.spec)
                            name = port.preset_for(r)
                            if "preset" in kwargs:
                                sp.preset = kwargs["preset"]
                                name = kwargs["preset"] or port.preset
                            inp, _, _ = _resolve(sp, port.base_dir, port.profile, name, vals,
                                                 skip_asset_overrides=reset)
                            r.ensure_cached_timeframes(inp)
                        for r in targets:
                            port.rewarm_asset(r.symbol, vals, bool(body.get("persist", True)) if vals is not None else False,
                                              reset=reset, **kwargs)
                    done = [r.symbol for r in targets]
                    return self._json(200, {"ok": True, "note": f"configuration applied and re-warmed {done}", "assets": done})
                if p.path == "/admin/assets/add":
                    tok = str(body.get("symbol", "")).strip()
                    if not tok:
                        return self._json(400, {"detail": "symbol required"})
                    spec = parse_spec(tok, str(body.get("tf") or port.runner_list()[0].spec.chart_tf if port.runner_list() else "20"))
                    if body.get("preset"):
                        spec.preset = body["preset"]
                    r = port.add_asset(spec)
                    return self._json(200, {"ok": True, "note": f"{r.symbol} added ({spec.name}, {spec.chart_tf}m); warming up", "asset": r.symbol})
                if p.path == "/admin/assets/remove":
                    ok = port.remove_asset(str(body.get("symbol", "")))
                    return self._json(200 if ok else 404, {"ok": ok, "note": f"{body.get('symbol')} {'removed' if ok else 'not found'}"})
                if p.path == "/admin/backtest":
                    from .backtest import validate_backtest_params
                    r = self._runner(asset)
                    if not r:
                        return self._json(404, {"detail": f"unknown asset {asset}"})
                    if not r.warm:
                        return self._json(409, {"detail": f"{r.symbol} is still warming up"})
                    fields = ("preset", "fill_on", "chart_type", "session", "slippage_ticks", "commission", "capital",
                              "leverage", "window_start", "window_end", "inputs")
                    params = validate_backtest_params({k: body[k] for k in fields if k in body})
                    params["asset"] = r.symbol
                    if "preset" in params and not os.path.exists(preset_path(port.base_dir, params["preset"])):
                        return self._json(404, {"detail": f"preset {params['preset']} not found"})
                    job_id = start_job(port, params)
                    return self._json(200, {"ok": True, "job": job_id, "note": f"backtest {r.symbol} started"})
                if p.path == "/admin/backtest/compare":
                    job = JOBS.get(str(body.get("job", "")))
                    if not job or job["status"] != "done":
                        return self._json(404, {"detail": "unknown or unfinished backtest job"})
                    text = str(body.get("csv", ""))
                    if not text.strip():
                        return self._json(400, {"detail": "csv text required"})
                    tv = read_tv_trades_text(text)
                    eng = engine_trades_from_rows(job["result"]["trades"])
                    rep_ = compare_lists(eng, tv, int(job["result"]["config"]["tf"]) * 60, int(body.get("tol", 1) or 1))
                    return self._json(200, {"ok": True, "report": rep_})
            except (ValueError, TypeError) as ex:
                return self._json(400, {"detail": str(ex)})
            except Exception as ex:
                port.journal.log("ERROR", f"admin {p.path}: {type(ex).__name__}: {ex}")
                return self._json(500, {"detail": f"{type(ex).__name__}: {ex}"})
            self._json(404, {"error": "not found"})

    class ResearchHTTPServer(ThreadingHTTPServer):
        def serve_forever(self, poll_interval=.5):
            research.start_background()
            try:
                return super().serve_forever(poll_interval)
            finally:
                research.close()

        def server_close(self):
            research.close()
            return super().server_close()

    srv = ResearchHTTPServer(("127.0.0.1", http_port), H)
    srv.research = research
    srv.daemon_threads = True
    if not start:
        return srv
    srv.serve_forever()
