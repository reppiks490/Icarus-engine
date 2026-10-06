from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import time
from typing import Any, Callable, Iterable, Iterator

BASE_URL = "https://api.unusualwhales.com"
WEBSOCKET_URL = "wss://api.unusualwhales.com/socket?token={token}"


@dataclass(frozen=True)
class EndpointFamily:
    name: str
    method: str
    path: str
    pagination: str = "none"
    response_key: str | None = None
    stream_channel: str | None = None
    safe_probe: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    license_hint: str | None = None


@dataclass(frozen=True)
class ResolvedPath:
    path: str
    unresolved: tuple[str, ...]


# Paths are taken from Unusual Whales' published Public API documentation.
ENDPOINTS: tuple[EndpointFamily, ...] = (
    EndpointFamily("option_trades", "GET", "/api/option-trades", "cursor", stream_channel="option_trades", params={"limit": 1}),
    EndpointFamily("option_full_tape", "GET", "/api/option-trades/full-tape/{date}", "download", safe_probe=False),
    EndpointFamily("flow_alerts", "GET", "/api/option-trades/flow-alerts", "cursor", stream_channel="flow-alerts", params={"limit": 1}),
    EndpointFamily("option_contract_screener", "GET", "/api/screener/option-contracts", "page", stream_channel="contract_screener", params={"limit": 1}),
    EndpointFamily("unusual_options", "GET", "/api/option-activity/unusual", "page", params={"limit": 1}),
    EndpointFamily("stock_screener", "GET", "/api/screener/stocks", "offset", stream_channel="stock_screener", params={"limit": 1}),
    EndpointFamily("market_tide", "GET", "/api/market/market-tide", "date", stream_channel="market_tide"),
    EndpointFamily("etf_tide", "GET", "/api/market/{ticker}/etf-tide", "date"),
    EndpointFamily("sector_tide", "GET", "/api/market/{sector}/sector-tide", "date"),
    EndpointFamily("gex_levels", "GET", "/api/stock/{ticker}/gex-levels", "date", stream_channel="gex:{ticker}"),
    EndpointFamily("greek_exposure", "GET", "/api/stock/{ticker}/greek-exposure", "date"),
    EndpointFamily("spot_gex", "GET", "/api/stock/{ticker}/spot-exposures", "date", stream_channel="gex:{ticker}"),
    EndpointFamily("gex_strike", "GET", "/api/stock/{ticker}/spot-exposures/strike", "page", stream_channel="gex_strike:{ticker}", params={"limit": 1}),
    EndpointFamily("gex_strike_expiry", "GET", "/api/stock/{ticker}/spot-exposures/expiry-strike", "page", stream_channel="gex_strike_expiry:{ticker}", params={"limit": 1}),
    EndpointFamily("greek_flow", "GET", "/api/stock/{ticker}/greek-flow", "date", stream_channel="greek_flow:{ticker}"),
    EndpointFamily("oi_change", "GET", "/api/market/oi-change", "date", params={"limit": 1}),
    EndpointFamily("dark_pool", "GET", "/api/darkpool/{ticker}", "cursor", stream_channel="off_lit_trades", params={"limit": 1}),
    EndpointFamily("dark_pool_price_levels", "GET", "/api/darkpool/{ticker}/price-levels", "date"),
    EndpointFamily("flex_contracts", "GET", "/api/flex-options", "page", params={"limit": 1}),
    EndpointFamily("flex_market", "GET", "/api/flex-options/market", "date"),
    EndpointFamily("flex_ticker_history", "GET", "/api/flex-options/{ticker}", "none"),
    EndpointFamily("short_screener", "GET", "/api/short_screener", "offset", params={"limit": 1}),
    EndpointFamily("short_interest", "GET", "/api/shorts/{ticker}/interest-float/v2", "none"),
    EndpointFamily("institutions", "GET", "/api/institutions", "page", params={"limit": 1}),
    EndpointFamily("institutional_ownership", "GET", "/api/institution/{ticker}/ownership", "page", params={"limit": 1}),
    EndpointFamily("institutional_holdings", "GET", "/api/institution/{name}/holdings", "page", params={"limit": 1}),
    EndpointFamily("congress_recent", "GET", "/api/congress/recent-trades", "page", params={"limit": 1}),
    EndpointFamily("congress_unusual", "GET", "/api/congress/unusual-trades", "page", params={"limit": 1}),
    EndpointFamily("earnings_history", "GET", "/api/earnings/{ticker}", "none"),
    EndpointFamily("analyst_ratings", "GET", "/api/screener/analysts", "cursor", params={"limit": 1}),
    EndpointFamily("financials", "GET", "/api/stock/{ticker}/financials", "none"),
    EndpointFamily("balance_sheets", "GET", "/api/stock/{ticker}/balance-sheets", "none"),
    EndpointFamily("company_profile", "GET", "/api/companies/{ticker}/profile", "none", license_hint="Advanced+"),
    EndpointFamily("earnings_estimates", "GET", "/api/companies/{ticker}/earnings-estimates", "none", license_hint="Advanced+"),
    EndpointFamily("company_dividends", "GET", "/api/companies/{ticker}/dividends", "none", license_hint="Advanced+"),
    EndpointFamily("company_splits", "GET", "/api/companies/{ticker}/splits", "none", license_hint="Advanced+"),
    EndpointFamily("option_contract_history", "GET", "/api/option-contract/{id}/historic", "none", safe_probe=False),
    EndpointFamily("option_contract_flow", "GET", "/api/option-contract/{id}/flow", "date", safe_probe=False),
    EndpointFamily("nope", "GET", "/api/stock/{ticker}/nope", "date"),
    EndpointFamily("flow_per_strike_intraday", "GET", "/api/stock/{ticker}/flow-per-strike-intraday", "date"),
)

_FIXTURES = {
    "ticker": "AAPL",
    "sector": "Technology",
    "name": "0000102909",  # Vanguard CIK from UW documentation example.
    "date": "2025-07-25",  # only used for operation-specific/non-generic paths.
    "expiry": "2026-12-18",
    "quarter": "2026Q2",
}


def resolve_path(path: str, fixtures: dict[str, str] | None = None) -> ResolvedPath:
    values = dict(_FIXTURES)
    if fixtures:
        values.update(fixtures)
    missing: list[str] = []

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.append(key)
            return match.group(0)
        return str(values[key])

    return ResolvedPath(re.sub(r"\{([^{}]+)\}", repl, path), tuple(sorted(set(missing))))


def classify_response(status: int, body: str = "") -> str:
    text = (body or "").lower()
    if 200 <= status < 300:
        return "ACCESSIBLE"
    if status == 401:
        return "AUTH_ERROR"
    if status == 429:
        return "RATE_LIMITED"
    if status == 403:
        if any(word in text for word in ("rate limit", "usage limit", "too many")):
            return "RATE_LIMITED"
        return "RESTRICTED"
    if status in (400, 404, 405, 409, 422):
        return "INVALID_PARAMETERS"
    if 500 <= status < 600:
        return "SERVER_ERROR"
    return "ERROR"


def _redact(text: Any, secret: str) -> str:
    out = str(text)
    if secret:
        out = out.replace(secret, "[REDACTED]")
    return out


def _default_requester(method: str, url: str, headers: dict[str, str], params=None) -> tuple[int, str]:
    import urllib.error
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode(params or {}, doseq=True)
    full = url + (("?" + query) if query else "")
    request = urllib.request.Request(full, method=method, headers={**headers, "Accept": "application/json", "User-Agent": "icarus-uw-entitlement/1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), response.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(65536).decode("utf-8", "replace")


def probe_catalog(
    catalog: Iterable[EndpointFamily],
    api_token: str,
    *,
    requester: Callable[..., tuple[int, str]] = _default_requester,
    fixtures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    secret = str(api_token or "")
    rows: list[dict[str, Any]] = []
    for spec in catalog:
        base = {
            "name": spec.name,
            "method": spec.method,
            "endpoint": spec.path,
            "pagination": spec.pagination,
            "stream_channel": spec.stream_channel,
            "license_hint": spec.license_hint,
        }
        target = resolve_path(spec.path, fixtures)
        if not spec.safe_probe:
            rows.append({**base, "access": "PROBE_UNRESOLVED", "reason": "operation-specific probe avoids large/stale download or identifier"})
            continue
        if target.unresolved:
            rows.append({**base, "access": "PROBE_UNRESOLVED", "reason": "unresolved path placeholders", "unresolved": list(target.unresolved)})
            continue
        try:
            status, body = requester(
                spec.method,
                BASE_URL + target.path,
                {"Authorization": f"Bearer {secret}"},
                params=dict(spec.params) or None,
            )
            rows.append({
                **base,
                "resolved_path": target.path,
                "http_status": int(status),
                "access": classify_response(int(status), body),
            })
        except Exception as exc:
            rows.append({
                **base,
                "resolved_path": target.path,
                "access": "NETWORK_ERROR",
                "error": _redact(f"{type(exc).__name__}: {exc}", secret)[:300],
            })
    return rows


def walk_pages(fetch_page: Callable[[int], dict[str, Any]], *, start_page: int = 0, max_pages: int = 100) -> Iterator[dict[str, Any]]:
    page = int(start_page)
    for _ in range(max_pages):
        payload = fetch_page(page)
        yield payload
        if payload.get("has_more") is False:
            break
        # Generic fallback: if data/chains is explicitly empty, stop. Otherwise the
        # provider-specific caller can expose has_more from response metadata.
        rows = payload.get("data", payload.get("chains"))
        if isinstance(rows, list) and not rows:
            break
        page += 1


def walk_cursor(
    fetch_page: Callable[[str | None], dict[str, Any]],
    *,
    start_cursor: str | None = None,
    next_key: str = "next_page",
    max_pages: int = 100,
) -> Iterator[dict[str, Any]]:
    cursor = start_cursor
    seen: set[str] = set()
    for _ in range(max_pages):
        payload = fetch_page(cursor)
        yield payload
        nxt = payload.get(next_key)
        if not nxt:
            break
        nxt = str(nxt)
        if nxt in seen:
            raise RuntimeError("Unusual Whales pagination cursor loop detected")
        seen.add(nxt)
        cursor = nxt


def join_message(channel: str) -> str:
    return json.dumps({"channel": str(channel), "msg_type": "join"}, separators=(",", ":"))


def ack_is_ok(message: dict[str, Any], channel: str | None = None) -> bool:
    if message.get("status") != "ok":
        return False
    returned = message.get("channel")
    return channel is None or returned in (None, channel)


class BufferedStreamCollector:
    """Bounded/reconnectable UW websocket collector with buffered persistence.

    The socket factory is injected so production can use websocket-client while tests
    stay network-free. This class intentionally does not implement an eternal daemon;
    callers bound it by duration and/or max_messages (GitHub Actions-safe behavior).
    """

    def __init__(
        self,
        *,
        socket_factory: Callable[[], Any],
        channels: Iterable[str],
        flush_callback: Callable[[list[dict[str, Any]]], None],
        buffer_size: int = 500,
        flush_interval_seconds: float = 10.0,
        max_reconnects: int = 5,
        max_messages: int | None = None,
        max_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.socket_factory = socket_factory
        self.channels = tuple(channels)
        self.flush_callback = flush_callback
        self.buffer_size = max(1, int(buffer_size))
        self.flush_interval_seconds = max(0.0, float(flush_interval_seconds))
        self.max_reconnects = max(0, int(max_reconnects))
        self.max_messages = max_messages
        self.max_seconds = max_seconds
        self.sleep = sleep
        self.monotonic = monotonic

    def _flush(self, buffer: list[dict[str, Any]]) -> None:
        if not buffer:
            return
        self.flush_callback(list(buffer))
        buffer.clear()

    def _join(self, sock: Any) -> None:
        for channel in self.channels:
            sock.send(join_message(channel))
            raw = sock.recv()
            try:
                reply = json.loads(raw)
            except Exception as exc:
                raise RuntimeError(f"malformed join acknowledgement for {channel}") from exc
            if not ack_is_ok(reply, channel):
                raise RuntimeError(f"join rejected for {channel}: {reply.get('status')}")

    def run(self) -> dict[str, Any]:
        started = self.monotonic()
        last_flush = started
        buffer: list[dict[str, Any]] = []
        messages = 0
        malformed = 0
        reconnects = 0
        joined = 0
        last_channel: str | None = None

        while True:
            if self.max_messages is not None and messages >= self.max_messages:
                break
            if self.max_seconds is not None and self.monotonic() - started >= self.max_seconds:
                break
            sock = None
            try:
                sock = self.socket_factory()
                self._join(sock)
                joined += len(self.channels)
                while True:
                    if self.max_messages is not None and messages >= self.max_messages:
                        break
                    if self.max_seconds is not None and self.monotonic() - started >= self.max_seconds:
                        break
                    raw = sock.recv()
                    try:
                        item = json.loads(raw)
                    except Exception:
                        malformed += 1
                        continue
                    if not isinstance(item, dict):
                        malformed += 1
                        continue
                    # Ignore late status frames after the initial join handshake.
                    if "status" in item and len(item) <= 3:
                        continue
                    buffer.append(item)
                    messages += 1
                    last_channel = item.get("channel") or last_channel
                    now = self.monotonic()
                    if len(buffer) >= self.buffer_size or now - last_flush >= self.flush_interval_seconds:
                        self._flush(buffer)
                        last_flush = now
                break
            except StopIteration:
                # A finite injected source ended cleanly. Production websocket clients do
                # not normally raise StopIteration.
                break
            except Exception:
                if reconnects >= self.max_reconnects:
                    raise
                reconnects += 1
                self.sleep(min(30.0, 2.0 ** (reconnects - 1)))
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass

        self._flush(buffer)
        return {
            "messages": messages,
            "malformed": malformed,
            "reconnects": reconnects,
            "join_acknowledgements": joined,
            "last_channel": last_channel,
        }
