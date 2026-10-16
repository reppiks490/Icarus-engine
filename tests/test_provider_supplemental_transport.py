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
