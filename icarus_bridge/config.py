"""Settings — read once from environment / .env (python-dotenv is optional)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:  # dotenv is optional; plain env vars still work
        return
    # project-local .env first, then the user's home .icarus-bridge/.env
    for p in (Path.cwd() / ".env", Path.home() / ".icarus-bridge" / ".env"):
        if p.exists():
            load_dotenv(p, override=False)


def _bool(v: str | None, default: bool) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "y")


def _float(v: str | None, default: float) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def _int(v: str | None, default: int) -> int:
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        return default


def _list(v: str | None, default: List[str]) -> List[str]:
    if v is None or v.strip() == "":
        return default
    return [x.strip() for x in v.split(",") if x.strip()]


def _symbol_map(v: str | None) -> Dict[str, str]:
    """'NQ1!:QQQ,ES1!:SPY' -> {'NQ1!': 'QQQ', 'ES1!': 'SPY'} (keys upper-cased)."""
    default = {
        "NQ1!": "QQQ", "NQ": "QQQ", "MNQ1!": "QQQ", "MNQ": "QQQ", "NQ1": "QQQ",
        "ES1!": "SPY", "ES": "SPY", "MES1!": "SPY", "MES": "SPY",
        "RTY1!": "IWM", "YM1!": "DIA",
        "QQQ": "QQQ", "SPY": "SPY", "TQQQ": "TQQQ",
    }
    if not v:
        return default
    out = dict(default)
    for pair in v.split(","):
        if ":" in pair:
            k, s = pair.split(":", 1)
            out[k.strip().upper()] = s.strip().upper()
    return out


@dataclass
class Settings:
    # ── Alpaca ──
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True

    # ── HTTP ──
    host: str = "0.0.0.0"
    port: int = 8787
    webhook_secret: str = "change-me"
    admin_token: str = "change-me-too"
    enforce_ip_allowlist: bool = False
    allowed_ips: List[str] = field(default_factory=lambda: [
        # TradingView's published webhook source IPs
        "52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7",
    ])

    # ── Execution ──
    execution_mode: str = "mirror"          # mirror | bracket | shadow
    symbol_map: Dict[str, str] = field(default_factory=lambda: _symbol_map(None))
    leverage_factor: float = 1.0            # 1.0 for QQQ, 3.0 for TQQQ (scales % levels)
    sizing_mode: str = "notional"           # notional | fixed_shares | risk
    notional_per_contract_usd: float = 20000.0
    fixed_shares_per_contract: float = 40.0
    risk_per_contract_usd: float = 300.0    # risk mode: shares = risk / (sl_pct * price)
    max_position_shares: int = 400
    daily_loss_limit_usd: float = 2000.0
    allow_extended_hours: bool = False
    protective_stop: bool = True
    default_tp1_pts: float = 15.0
    default_tp2_pts: float = 30.0
    default_sl_pts: float = 45.0
    dedup_window_sec: float = 90.0

    # ── Storage ──
    db_path: str = "icarus_bridge.db"
    log_path: str = "icarus_bridge.log"

    @classmethod
    def load(cls) -> "Settings":
        _load_dotenv()
        e = os.environ.get
        s = cls(
            alpaca_api_key=e("ALPACA_API_KEY", ""),
            alpaca_secret_key=e("ALPACA_SECRET_KEY", ""),
            alpaca_paper=_bool(e("ALPACA_PAPER"), True),
            host=e("HOST", "0.0.0.0"),
            port=_int(e("PORT"), 8787),
            webhook_secret=e("WEBHOOK_SECRET", "change-me"),
            admin_token=e("ADMIN_TOKEN", "change-me-too"),
            enforce_ip_allowlist=_bool(e("ENFORCE_IP_ALLOWLIST"), False),
            allowed_ips=_list(e("ALLOWED_IPS"), cls().allowed_ips),
            execution_mode=e("EXECUTION_MODE", "mirror").strip().lower(),
            symbol_map=_symbol_map(e("SYMBOL_MAP")),
            leverage_factor=_float(e("LEVERAGE_FACTOR"), 1.0),
            sizing_mode=e("SIZING_MODE", "notional").strip().lower(),
            notional_per_contract_usd=_float(e("NOTIONAL_PER_CONTRACT_USD"), 20000.0),
            fixed_shares_per_contract=_float(e("FIXED_SHARES_PER_CONTRACT"), 40.0),
            risk_per_contract_usd=_float(e("RISK_PER_CONTRACT_USD"), 300.0),
            max_position_shares=_int(e("MAX_POSITION_SHARES"), 400),
            daily_loss_limit_usd=_float(e("DAILY_LOSS_LIMIT_USD"), 2000.0),
            allow_extended_hours=_bool(e("ALLOW_EXTENDED_HOURS"), False),
            protective_stop=_bool(e("PROTECTIVE_STOP"), True),
            default_tp1_pts=_float(e("DEFAULT_TP1_PTS"), 15.0),
            default_tp2_pts=_float(e("DEFAULT_TP2_PTS"), 30.0),
            default_sl_pts=_float(e("DEFAULT_SL_PTS"), 45.0),
            dedup_window_sec=_float(e("DEDUP_WINDOW_SEC"), 90.0),
            db_path=e("DB_PATH", "icarus_bridge.db"),
            log_path=e("LOG_PATH", "icarus_bridge.log"),
        )
        if s.execution_mode not in ("mirror", "bracket", "shadow"):
            s.execution_mode = "mirror"
        if s.sizing_mode not in ("notional", "fixed_shares", "risk"):
            s.sizing_mode = "notional"
        return s

    def public_dict(self) -> dict:
        """Config view safe to show in the dashboard / MCP (no secrets)."""
        d = self.__dict__.copy()
        d["alpaca_api_key"] = ("set" if self.alpaca_api_key else "MISSING")
        d["alpaca_secret_key"] = ("set" if self.alpaca_secret_key else "MISSING")
        d["webhook_secret"] = ("set" if self.webhook_secret not in ("", "change-me") else "DEFAULT — change it")
        d["admin_token"] = ("set" if self.admin_token not in ("", "change-me-too") else "DEFAULT — change it")
        return d
