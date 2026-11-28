from __future__ import annotations

import pytest

from tools import provider_supplemental_transport as t


def test_unusual_whales_list_tokens_does_not_invent_pagination() -> None:
    # Official list_tokens has no next_token/page parameter; metadata that is not
    # an explicit cursor must not be delegated to the K1 generic parser.
    assert t.next_page('unusual_whales', {'data': [{'token': 'x'}]}, {'limit': 1000}) is None


def test_unusual_whales_documented_next_token_is_preserved() -> None:
    assert t.next_page(
        'unusual_whales',
        {'data': {'next_token': 'cursor-123'}},
        {'token': 'BTC'},
    ) == {'params': {'token': 'BTC', 'next_token': 'cursor-123'}}


def test_unusual_whales_relative_cursor_is_same_authority_only() -> None:
    assert t.next_page(
        'unusual_whales',
        {'next_url': '/api/crypto/trades?next_token=abc'},
        {},
    ) == {'path': '/api/crypto/trades', 'params': {'next_token': 'abc'}}

    with pytest.raises(ValueError, match='authority'):
        t.next_page(
            'unusual_whales',
            {'next_url': 'https://evil.example/api/crypto/trades?next_token=abc'},
            {},
        )


def test_non_unusual_whales_transport_delegates_to_base(monkeypatch) -> None:
    sentinel = {'params': {'page': 2}}
    monkeypatch.setattr(t.base, 'next_page', lambda provider, data, current: sentinel)
    assert t.next_page('alphavantage', {}, {'page': 1}) is sentinel


@pytest.fixture
def offline_transport(monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace

    captured = []

    def open_request(request, timeout):
        captured.append((request, timeout))
        return BytesIO(b'{"data": []}')

    monkeypatch.setitem(t.core.PROVIDERS, 'unusual_whales', t.base.EXTENDED_PROVIDERS['unusual_whales'])
    monkeypatch.setattr(t.urllib.request, 'build_opener', lambda *handlers: SimpleNamespace(open=open_request))
    return captured


def test_unusual_whales_list_tokens_reaches_pinned_host(offline_transport) -> None:
    assert t.request('unusual_whales', '/api/crypto/list_tokens', {'limit': 1000}, 'fixture-key') == {'data': []}
    request, timeout = offline_transport[0]
    assert request.full_url == 'https://api.unusualwhales.com/api/crypto/list_tokens?limit=1000'
    assert request.get_header('Authorization') == 'Bearer fixture-key'
    assert 'fixture-key' not in request.full_url
    assert timeout == 20


@pytest.mark.parametrize('name', ['token', 'access_token', 'api_key', 'apiKey', 'password', 'secret', 'Authorization'])
def test_unusual_whales_query_credentials_are_filtered(name, offline_transport) -> None:
    from urllib.parse import parse_qs, urlsplit

    t.request('unusual_whales', '/api/crypto/trades', {name: 'untrusted-key', 'next_token': 'cursor', 'limit': 10, 'empty': None}, 'fixture-key')
    request, _ = offline_transport[0]
    assert parse_qs(urlsplit(request.full_url).query) == {'next_token': ['cursor'], 'limit': ['10']}
    assert 'untrusted-key' not in request.full_url
    assert request.get_header('Authorization') == 'Bearer fixture-key'


@pytest.mark.parametrize('path', [
    'api/crypto/trades',
    'https://evil.example/api/crypto/trades',
    '//evil.example/api/crypto/trades',
    '//user:password@evil.example/api/crypto/trades',
    '/api/../crypto/trades',
    '/api/crypto/trades?token=untrusted-key',
    '/api/crypto/trades?api_key=untrusted-key',
    '/api/crypto/trades?',
    '/api/crypto/trades#fragment',
    '/api/crypto/trades#',
    '/api/https://evil.example/trades',
    '/api/crypto/\\trades',
    '/api/%2e%2e/crypto/trades',
    '/api/%252e%252e/crypto/trades',
    '/api/crypto/trades%3ftoken=untrusted-key',
    '/api/crypto/trades\n',
    '/api/crypto/\ttrades',
    '/api/crypto/trades\x00',
    '/api/crypto/trades ',
])
def test_unusual_whales_unsafe_paths_fail_before_transport(path, offline_transport) -> None:
    with pytest.raises(ValueError, match='unsafe path'):
        t.request('unusual_whales', path, {}, 'fixture-key')
    assert offline_transport == []


def test_unusual_whales_redirects_remain_blocked(monkeypatch) -> None:
    def inspect_handler(handler):
        with pytest.raises(t.core.ProviderFailure) as exc:
            handler().redirect_request(None, None, None, None, None, None)
        assert exc.value.code == 'REDIRECT_BLOCKED'
        raise RuntimeError('offline sentinel')

    monkeypatch.setitem(t.core.PROVIDERS, 'unusual_whales', t.base.EXTENDED_PROVIDERS['unusual_whales'])
    monkeypatch.setattr(t.urllib.request, 'build_opener', inspect_handler)
    with pytest.raises(RuntimeError, match='offline sentinel'):
        t.request('unusual_whales', '/api/crypto/trades', {}, 'fixture-key')
