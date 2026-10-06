import json

from cl_lab.providers.unusual_whales import (
    ENDPOINTS,
    ack_is_ok,
    classify_response,
    join_message,
    probe_catalog,
    resolve_path,
    walk_cursor,
    walk_pages,
    BufferedStreamCollector,
)


def test_catalog_covers_core_families_with_exact_paths():
    paths = {e.name: e.path for e in ENDPOINTS}
    required = {
        "option_trades": "/api/option-trades",
        "option_full_tape": "/api/option-trades/full-tape/{date}",
        "flow_alerts": "/api/option-trades/flow-alerts",
        "stock_screener": "/api/screener/stocks",
        "market_tide": "/api/market/market-tide",
        "gex_levels": "/api/stock/{ticker}/gex-levels",
        "greek_exposure": "/api/stock/{ticker}/greek-exposure",
        "gex_strike": "/api/stock/{ticker}/spot-exposures/strike",
        "greek_flow": "/api/stock/{ticker}/greek-flow",
        "oi_change": "/api/market/oi-change",
        "dark_pool": "/api/darkpool/{ticker}",
        "flex_contracts": "/api/flex-options",
        "short_screener": "/api/short_screener",
        "institutions": "/api/institutions",
        "institutional_ownership": "/api/institution/{ticker}/ownership",
        "institutional_holdings": "/api/institution/{name}/holdings",
        "congress_recent": "/api/congress/recent-trades",
        "earnings_history": "/api/earnings/{ticker}",
        "analyst_ratings": "/api/screener/analysts",
        "financials": "/api/stock/{ticker}/financials",
    }
    for name, path in required.items():
        assert paths[name] == path
    assert len(ENDPOINTS) >= 25


def test_resolve_path_uses_safe_known_fixtures_and_marks_unknown():
    good = resolve_path("/api/stock/{ticker}/gex-levels")
    assert good.path == "/api/stock/AAPL/gex-levels"
    assert good.unresolved == ()
    institution = resolve_path("/api/institution/{name}/holdings")
    assert institution.path == "/api/institution/0000102909/holdings"
    bad = resolve_path("/api/foo/{mystery}")
    assert bad.unresolved == ("mystery",)


def test_response_classification():
    assert classify_response(200, "{}") == "ACCESSIBLE"
    assert classify_response(401, "invalid key") == "AUTH_ERROR"
    assert classify_response(403, "plan does not include endpoint") == "RESTRICTED"
    assert classify_response(429, "too many") == "RATE_LIMITED"
    assert classify_response(422, "bad params") == "INVALID_PARAMETERS"
    assert classify_response(503, "unavailable") == "SERVER_ERROR"


def test_probe_accounts_for_every_family_and_does_not_leak_secret():
    subset = [e for e in ENDPOINTS if e.name in {"market_tide", "gex_levels", "option_full_tape"}]
    calls = []

    def requester(method, url, headers, params=None):
        calls.append((method, url, headers, params))
        if url.endswith("/api/market/market-tide"):
            return 200, "{}"
        if url.endswith("/api/stock/AAPL/gex-levels"):
            return 403, "upgrade plan"
        raise AssertionError("download-only family must not be generically probed")

    rows = probe_catalog(subset, "super-secret", requester=requester)
    assert len(rows) == 3
    by_name = {r["name"]: r for r in rows}
    assert by_name["market_tide"]["access"] == "ACCESSIBLE"
    assert by_name["gex_levels"]["access"] == "RESTRICTED"
    assert by_name["option_full_tape"]["access"] == "PROBE_UNRESOLVED"
    assert all("super-secret" not in str(r) for r in rows)
    assert all("super-secret" not in url for _, url, _, _ in calls)
    assert all(h["Authorization"] == "Bearer super-secret" for _, _, h, _ in calls)


def test_page_and_cursor_walkers_stop_and_resume():
    page_calls = []
    def fetch_page(page):
        page_calls.append(page)
        return {"data": [page], "has_more": page < 3}
    assert [x["data"] for x in walk_pages(fetch_page, start_page=2, max_pages=5)] == [[2], [3]]
    assert page_calls == [2, 3]

    cursor_calls = []
    def fetch_cursor(cursor):
        cursor_calls.append(cursor)
        return {"data": [cursor], "next": "b" if cursor == "a" else None}
    assert list(walk_cursor(fetch_cursor, start_cursor="a", next_key="next", max_pages=3))[-1]["next"] is None
    assert cursor_calls == ["a", "b"]


def test_join_and_ack_contract():
    msg = join_message("market_tide")
    assert json.loads(msg) == {"channel": "market_tide", "msg_type": "join"}
    assert ack_is_ok({"status": "ok", "channel": "market_tide"}, "market_tide")
    assert not ack_is_ok({"status": "error", "channel": "market_tide"}, "market_tide")


def test_bounded_stream_reconnects_rejoins_ignores_bad_json_and_flushes():
    flushes = []

    class FakeSocket:
        def __init__(self, messages):
            self.messages = iter(messages)
            self.sent = []
        def send(self, msg):
            self.sent.append(msg)
        def recv(self):
            value = next(self.messages)
            if isinstance(value, BaseException):
                raise value
            return value
        def close(self):
            pass

    sockets = [
        FakeSocket([
            json.dumps({"status": "ok", "channel": "market_tide"}),
            "not-json",
            json.dumps({"channel": "market_tide", "value": 1}),
            ConnectionError("drop"),
        ]),
        FakeSocket([
            json.dumps({"status": "ok", "channel": "market_tide"}),
            json.dumps({"channel": "market_tide", "value": 2}),
            json.dumps({"channel": "market_tide", "value": 3}),
        ]),
    ]

    def factory():
        return sockets.pop(0)

    collector = BufferedStreamCollector(
        socket_factory=factory,
        channels=["market_tide"],
        flush_callback=lambda batch: flushes.append(list(batch)),
        buffer_size=2,
        max_reconnects=1,
        max_messages=3,
        sleep=lambda _: None,
    )
    summary = collector.run()
    assert summary["messages"] == 3
    assert summary["malformed"] == 1
    assert summary["reconnects"] == 1
    assert sum(len(b) for b in flushes) == 3
    assert [b[0]["value"] for b in flushes if b] == [1, 3]
