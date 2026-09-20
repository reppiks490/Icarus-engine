"""icarus-bridge CLI.

  icarus-bridge serve [--tunnel ngrok|cloudflared|none] [--port 8787]
  icarus-bridge doctor
  icarus-bridge test-alert [--side long|short] [--contracts 5] [--position-after N] [--comment L_TP1]
  icarus-bridge tunnel-url
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional

from .config import Settings


# ──────────────────────────────────────────────────────────────────────
# Tunnel helpers (public HTTPS URL for TradingView → this PC)
# ──────────────────────────────────────────────────────────────────────
def _ngrok_public_url(timeout: float = 20.0) -> Optional[str]:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as r:
                data = json.loads(r.read().decode())
            for t in data.get("tunnels", []):
                url = t.get("public_url", "")
                if url.startswith("https://"):
                    return url
        except Exception:
            pass
        time.sleep(1.0)
    return None


def start_tunnel(kind: str, port: int, on_url) -> Optional[subprocess.Popen]:
    """Spawn ngrok/cloudflared and call on_url(public_url) once it's known. Returns the process."""
    kind = (kind or "none").lower()
    if kind == "none":
        return None
    if kind == "ngrok":
        exe = shutil.which("ngrok")
        if not exe:
            print("  [!] ngrok not found on PATH - install from https://ngrok.com/download or use --tunnel cloudflared")
            return None
        proc = subprocess.Popen([exe, "http", str(port), "--log=stdout", "--log-format=json"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def waiter():
            url = _ngrok_public_url()
            if url:
                on_url(url)
            else:
                print("  [!] ngrok started but no public URL after 20s - is your ngrok authtoken configured? (ngrok config add-authtoken ...)")
        threading.Thread(target=waiter, daemon=True).start()
        return proc
    if kind == "cloudflared":
        exe = shutil.which("cloudflared")
        if not exe:
            print("  [!] cloudflared not found - winget install Cloudflare.cloudflared, or use --tunnel ngrok")
            return None
        proc = subprocess.Popen([exe, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        def reader():
            assert proc.stdout is not None
            for line in proc.stdout:
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m:
                    on_url(m.group(0))
        threading.Thread(target=reader, daemon=True).start()
        return proc
    print(f"  [!] unknown tunnel kind: {kind}")
    return None


# ──────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────
def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    from .webhook import create_app

    cfg = Settings.load()
    if args.port:
        cfg.port = args.port
    if args.mode:
        cfg.execution_mode = args.mode
    app = create_app(cfg)

    print(f"\nICARUS Bridge  mode={cfg.execution_mode}  broker={getattr(app.state.broker, 'name', '?')}  port={cfg.port}")
    print(f"  dashboard : http://127.0.0.1:{cfg.port}/")
    print(f"  webhook   : http://127.0.0.1:{cfg.port}/webhook  (local - TradingView needs the tunnel URL below)")
    if cfg.webhook_secret in ("", "change-me"):
        print("  [!] WEBHOOK_SECRET is the default - set a real one in .env before exposing this")
    if cfg.admin_token in ("", "change-me-too"):
        print("  [!] ADMIN_TOKEN is the default - set a real one in .env")

    def on_url(url: str) -> None:
        app.state.public_url = url
        app.state.journal.set_state("public_url", url)
        print(f"\n  * PUBLIC WEBHOOK URL -> {url}/webhook\n    paste this into the TradingView alert's Webhook URL box\n")

    proc = start_tunnel(args.tunnel, cfg.port, on_url)
    try:
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info", access_log=False)
    finally:
        if proc:
            proc.terminate()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = Settings.load()
    ok = True
    print("\nICARUS Bridge doctor\n" + "=" * 40)

    def check(label: str, good: bool, detail: str = "", warn: bool = False) -> None:
        nonlocal ok
        mark = "OK " if good else ("!! " if warn else "XX ")
        if not good and not warn:
            ok = False
        print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")

    # deps
    for mod in ("fastapi", "uvicorn", "alpaca", "mcp", "httpx"):
        try:
            __import__(mod); check(f"python package {mod}", True)
        except Exception as ex:
            check(f"python package {mod}", False, f"missing ({ex.__class__.__name__}) → pip install -e .")

    # config
    check("EXECUTION_MODE", True, cfg.execution_mode)
    check("WEBHOOK_SECRET set", cfg.webhook_secret not in ("", "change-me"), "default value - change it", warn=True)
    check("ADMIN_TOKEN set", cfg.admin_token not in ("", "change-me-too"), "default value - change it", warn=True)
    check("Alpaca keys present", bool(cfg.alpaca_api_key and cfg.alpaca_secret_key),
          "ALPACA_API_KEY / ALPACA_SECRET_KEY missing in .env", warn=(cfg.execution_mode == "shadow"))
    check("symbol map has NQ1!", "NQ1!" in cfg.symbol_map, str(cfg.symbol_map.get("NQ1!")))

    # broker
    if cfg.execution_mode != "shadow" and cfg.alpaca_api_key:
        try:
            from .brokers.alpaca_broker import AlpacaBroker
            b = AlpacaBroker(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=cfg.alpaca_paper)
            acct = b.account()
            check("Alpaca account", True, f"{'PAPER' if cfg.alpaca_paper else 'LIVE'} equity=${acct['equity']:.2f} status={acct['status']}")
            c = b.clock()
            check("Alpaca clock", True, f"market {'OPEN' if c.is_open else 'closed'}; next open {c.next_open}")
            px = b.latest_price("QQQ")
            check("QQQ quote", px is not None, f"{px}")
            if px:
                from .mapping import shares_per_contract
                spc = shares_per_contract(cfg, px, cfg.default_sl_pts / 20000.0)
                print(f"       sizing: {cfg.sizing_mode} -> {spc:.1f} QQQ shares per NQ contract (5 contracts = {5*spc:.0f} shares ~ ${5*spc*px:,.0f} notional; max {cfg.max_position_shares})")
                if 5 * spc > cfg.max_position_shares:
                    check("MAX_POSITION_SHARES vs 5-contract size", False, "the clamp will cut your default 5-contract entries - raise MAX_POSITION_SHARES or lower NOTIONAL_PER_CONTRACT_USD", warn=True)
            pos = b.positions()
            check("open paper positions", True, str([(p['symbol'], p['qty']) for p in pos]) or "none")
        except Exception as ex:
            check("Alpaca connectivity", False, f"{type(ex).__name__}: {ex}")
    elif cfg.execution_mode == "shadow":
        print("  [-- ] shadow mode: Alpaca not contacted")

    # tunnel
    check("ngrok on PATH", bool(shutil.which("ngrok")), "found" if shutil.which("ngrok") else "not found (optional: --tunnel cloudflared)", warn=True)
    check("cloudflared on PATH", bool(shutil.which("cloudflared")), "found" if shutil.which("cloudflared") else "not found (optional)", warn=True)

    # pine template present?
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tpl = os.path.join(here, "pine", "ALERT_TEMPLATE.json")
    check("alert template", os.path.exists(tpl), tpl)
    print("\n" + ("all critical checks passed" if ok else "fix the XX items above") + "\n")
    return 0 if ok else 1


def cmd_test_alert(args: argparse.Namespace) -> int:
    """POST a synthetic order-fill through the REAL webhook path (secret included)."""
    import urllib.request
    cfg = Settings.load()
    pos = args.position_after if args.position_after is not None else (args.contracts if args.side == "long" else -args.contracts)
    mp = "flat" if abs(pos) < 1e-9 else ("long" if pos > 0 else "short")
    payload = {
        "secret": cfg.webhook_secret, "event": "order_fill", "ticker": args.ticker,
        "action": "buy" if args.side == "long" else "sell", "contracts": str(args.contracts),
        "order_id": "Long" if args.side == "long" else "Short", "comment": args.comment,
        "order_price": str(args.price), "position_size": str(abs(pos)), "market_position": mp,
        "prev_market_position": args.prev, "bar_close": str(args.price), "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "meta": f"sys=RATE;side={args.side};tp1=15;tp2=30;sl=45;q1=2;q2=3;ref={args.price}",
    }
    url = f"http://127.0.0.1:{args.port or cfg.port}/webhook"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(r.read().decode())
    except Exception as ex:
        print(f"request failed: {ex}\nis the bridge running? (icarus-bridge serve)")
        return 1
    return 0


def cmd_tunnel_url(args: argparse.Namespace) -> int:
    url = _ngrok_public_url(3.0)
    print(url + "/webhook" if url else "no ngrok tunnel detected on :4040")
    return 0 if url else 1


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="icarus-bridge", description="TradingView → Alpaca paper bridge")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the webhook receiver + dashboard (+ tunnel)")
    s.add_argument("--tunnel", default="ngrok", choices=["ngrok", "cloudflared", "none"])
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--mode", default=None, choices=["mirror", "bracket", "shadow"], help="override EXECUTION_MODE")
    s.set_defaults(fn=cmd_serve)

    d = sub.add_parser("doctor", help="check config, dependencies, Alpaca connectivity, sizing")
    d.set_defaults(fn=cmd_doctor)

    t = sub.add_parser("test-alert", help="send a synthetic order-fill to the local webhook")
    t.add_argument("--side", default="long", choices=["long", "short"])
    t.add_argument("--contracts", type=float, default=5)
    t.add_argument("--position-after", type=float, default=None, help="signed position AFTER the fill (default ±contracts)")
    t.add_argument("--prev", default="flat", help="prev_market_position: flat|long|short")
    t.add_argument("--comment", default="")
    t.add_argument("--ticker", default="NQ1!")
    t.add_argument("--price", type=float, default=20000.0)
    t.add_argument("--port", type=int, default=None)
    t.set_defaults(fn=cmd_test_alert)

    u = sub.add_parser("tunnel-url", help="print the current ngrok public webhook URL")
    u.set_defaults(fn=cmd_tunnel_url)

    m = sub.add_parser("demo", help="dashboard rehearsal: shadow broker + scripted session, no Alpaca, no extra deps")
    m.add_argument("--port", type=int, default=8790)
    m.add_argument("--speed", type=float, default=1.0, help="script speed multiplier")
    m.add_argument("--open", action="store_true", help="open the browser")
    m.set_defaults(fn=lambda a: __import__("icarus_bridge.preview", fromlist=["serve"]).serve(a.port, a.speed, a.open))

    args = p.parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
