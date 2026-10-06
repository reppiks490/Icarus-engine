from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Iterable, Iterator

from cl_lab.data_fabric.contracts import redact_text

BASE_URL = "https://api-v2.intrinio.com"
SDK_README_URL = "https://raw.githubusercontent.com/intrinio/python-sdk/master/README.md"


@dataclass(frozen=True)
class EndpointSpec:
    api_class: str
    operation: str
    method: str
    path: str
    description: str


@dataclass(frozen=True)
class ProbeTarget:
    path: str
    unresolved: tuple[str, ...]
    params: dict[str, Any]


FIXTURES = {
    "identifier": "AAPL",
    "symbol": "AAPL",
    "ticker": "AAPL",
    "tag": "revenue",
    "statement_code": "income_statement",
    "fiscal_year": "2025",
    "fiscal_period": "FY",
    "pair": "EURUSD",
    "timeframe": "D1",
    "expiration": "2026-12-18",
    "strike": "200",
}

SEARCH_PARAMS = {
    "/companies/search": {"query": "Apple"},
    "/securities/search": {"query": "AAPL"},
    "/data_tags/search": {"query": "revenue"},
    "/owners/search": {"query": "Apple"},
    "/etfs/search": {"query": "QQQ"},
    "/indices/economic/search": {"query": "GDP"},
    "/indices/sic/search": {"query": "software"},
    "/indices/stock_market/search": {"query": "NASDAQ"},
}


def parse_sdk_catalog(readme: str) -> tuple[dict[str, Any], list[EndpointSpec]]:
    api = re.search(r"^- API version:\s*([^\s]+)", readme, re.M)
    package = re.search(r"^- Package version:\s*([^\s]+)", readme, re.M)
    row_re = re.compile(
        r"^\*([^*]+)\*\s*\|\s*\[\*\*([^*]+)\*\*\]\([^)]*\)\s*\|\s*\*\*([A-Z]+)\*\*\s+([^|]+?)\s*\|\s*(.*?)\s*$",
        re.M,
    )
    rows = [
        EndpointSpec(m.group(1).strip(), m.group(2).strip(), m.group(3).strip(), m.group(4).strip(), m.group(5).strip())
        for m in row_re.finditer(readme)
    ]
    if not rows:
        raise ValueError("Intrinio SDK endpoint catalog is empty")
    return {
        "api_version": api.group(1) if api else None,
        "package_version": package.group(1) if package else None,
        "endpoint_count": len(rows),
    }, rows


def resolve_probe_target(path: str, fixtures: dict[str, str] | None = None) -> ProbeTarget:
    values = dict(FIXTURES)
    if fixtures:
        values.update(fixtures)
    unresolved: list[str] = []

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            unresolved.append(key)
            return match.group(0)
        return str(values[key])

    resolved = re.sub(r"\{([^{}]+)\}", repl, path)
    return ProbeTarget(resolved, tuple(sorted(set(unresolved))), dict(SEARCH_PARAMS.get(path, {})))


def classify_response(status: int, body: str = "") -> str:
    text = (body or "").lower()
    if 200 <= status < 300:
        return "ACCESSIBLE"
    if status == 401:
        return "AUTH_ERROR"
    if status == 429:
        return "RATE_LIMITED"
    if status == 403:
        if any(x in text for x in ("limit", "rate", "too many", "usage")):
            return "RATE_LIMITED"
        return "RESTRICTED"
    if status in (400, 404, 405, 409, 422):
        return "INVALID_PARAMETERS"
    if 500 <= status < 600:
        return "SERVER_ERROR"
    return "ERROR"


def _default_requester(method: str, url: str, headers: dict[str, str], params=None, body=None) -> tuple[int, str]:
    import urllib.error
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode(params or {}, doseq=True)
    full = url + (("?" + query) if query else "")
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        full,
        data=data,
        method=method,
        headers={**headers, "Accept": "application/json", "User-Agent": "icarus-intrinio-entitlement/1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return int(response.status), response.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(65536).decode("utf-8", "replace")


def probe_catalog(
    catalog: Iterable[EndpointSpec],
    api_key: str,
    *,
    requester: Callable[..., tuple[int, str]] = _default_requester,
    fixtures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    secret = str(api_key or "")
    rows: list[dict[str, Any]] = []
    for spec in catalog:
        target = resolve_probe_target(spec.path, fixtures)
        base = {
            "api_class": spec.api_class,
            "operation": spec.operation,
            "method": spec.method,
            "endpoint": spec.path,
            "description": spec.description,
        }
        if spec.method != "GET":
            rows.append({**base, "access": "PROBE_UNRESOLVED", "reason": "non-GET endpoint requires operation-specific safe probe body"})
            continue
        if target.unresolved:
            rows.append({**base, "access": "PROBE_UNRESOLVED", "reason": "unresolved path placeholders", "unresolved": list(target.unresolved)})
            continue
        try:
            status, body = requester(
                spec.method,
                BASE_URL + target.path,
                {"Authorization": f"Bearer {secret}"},
                params=target.params or None,
                body=None,
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
                "error": redact_text(f"{type(exc).__name__}: {exc}", [secret])[:300],
            })
    return rows


def walk_next_page(
    fetch_page: Callable[[str | None], dict[str, Any]],
    *,
    start_cursor: str | None = None,
    max_pages: int = 100,
) -> Iterator[dict[str, Any]]:
    cursor = start_cursor
    seen: set[str] = set()
    for _ in range(max_pages):
        page = fetch_page(cursor)
        yield page
        nxt = page.get("next_page")
        if not nxt:
            break
        nxt = str(nxt)
        if nxt in seen:
            raise RuntimeError("Intrinio pagination cursor loop detected")
        seen.add(nxt)
        cursor = nxt
