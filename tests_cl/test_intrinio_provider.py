from cl_lab.providers.intrinio import (
    classify_response,
    parse_sdk_catalog,
    probe_catalog,
    resolve_probe_target,
    walk_next_page,
)

README = """
- API version: 2.135.4
- Package version: 7.2.0
Class | Method | HTTP request | Description
------------ | ------------- | ------------- | -------------
*AccountApi* | [**get_account_current_usage**](docs/AccountApi.md#get_account_current_usage) | **GET** /account/current_usage | Account Current Usage
*CompanyApi* | [**get_company**](docs/CompanyApi.md#get_company) | **GET** /companies/{identifier} | Lookup Company
*WeirdApi* | [**unsafe_batch**](docs/WeirdApi.md#unsafe_batch) | **POST** /widgets/{mystery}/batch | Weird Batch
"""


def test_parse_sdk_catalog_accounts_for_every_table_row():
    meta, rows = parse_sdk_catalog(README)
    assert meta["api_version"] == "2.135.4"
    assert meta["package_version"] == "7.2.0"
    assert [x.path for x in rows] == ["/account/current_usage", "/companies/{identifier}", "/widgets/{mystery}/batch"]
    assert rows[1].method == "GET"


def test_resolve_probe_target_and_unresolved_placeholder():
    target = resolve_probe_target("/companies/{identifier}")
    assert target.path == "/companies/AAPL"
    assert target.unresolved == ()
    bad = resolve_probe_target("/widgets/{mystery}/batch")
    assert bad.unresolved == ("mystery",)


def test_http_classification_distinguishes_entitlement_and_limits():
    assert classify_response(200, "{}") == "ACCESSIBLE"
    assert classify_response(401, "bad api key") == "AUTH_ERROR"
    assert classify_response(403, "You do not have access to this product") == "RESTRICTED"
    assert classify_response(403, "10 minute usage limit reached") == "RATE_LIMITED"
    assert classify_response(429, "slow down") == "RATE_LIMITED"
    assert classify_response(422, "missing parameter") == "INVALID_PARAMETERS"
    assert classify_response(503, "oops") == "SERVER_ERROR"


def test_probe_catalog_never_drops_rows_or_leaks_key():
    _, rows = parse_sdk_catalog(README)
    seen = []

    def requester(method, url, headers, params=None, body=None):
        seen.append((method, url, headers, params))
        if url.endswith("/account/current_usage"):
            return 200, '{"ok":true}'
        if url.endswith("/companies/AAPL"):
            return 403, "not authorized for product"
        raise AssertionError("POST should not be sent")

    result = probe_catalog(rows, "super-secret-key", requester=requester)
    assert len(result) == 3
    assert [r["access"] for r in result] == ["ACCESSIBLE", "RESTRICTED", "PROBE_UNRESOLVED"]
    assert all("super-secret-key" not in str(r) for r in result)
    assert all("super-secret-key" not in url for _, url, _, _ in seen)
    assert all(h["Authorization"] == "Bearer super-secret-key" for _, _, h, _ in seen)


def test_cursor_walker_resumes_and_stops():
    calls = []

    def fetch(cursor):
        calls.append(cursor)
        if cursor is None:
            return {"items": [1, 2], "next_page": "abc"}
        if cursor == "abc":
            return {"items": [3], "next_page": None}
        raise AssertionError(cursor)

    pages = list(walk_next_page(fetch, start_cursor=None, max_pages=5))
    assert [p["items"] for p in pages] == [[1, 2], [3]]
    assert calls == [None, "abc"]
