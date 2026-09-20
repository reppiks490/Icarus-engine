"""ICARUS Bridge — TradingView strategy alerts -> Alpaca paper execution.

Modules (dependency-light core first, adapters last):
  config    — settings from .env / environment
  models    — alert payload parsing (pure)
  mapping   — futures-symbol -> equity-proxy mapping, pts -> % conversion, sizing (pure)
  journal   — SQLite journal of alerts / orders / state / log
  executor  — execution engine (pure planner + broker-driven runner)
  brokers/  — Broker protocol, Alpaca adapter, in-memory shadow broker
  webhook   — FastAPI app: /webhook, dashboard, /status, /admin/*
  mcp_server— MCP (stdio) control surface for Claude Code
  cli       — serve / doctor / test-alert / tunnel
"""

__version__ = "0.1.0"
