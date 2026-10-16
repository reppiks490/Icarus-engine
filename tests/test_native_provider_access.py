from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest


WORKFLOW = Path('.github/workflows/native-provider-access.yml')


def test_native_registry_admits_stored_unwired_credentials() -> None:
    from tools.native_provider_access import PROVIDERS

    assert PROVIDERS['alphavantage']['base'] == 'https://www.alphavantage.co'
    assert PROVIDERS['alphavantage']['canonical'] == 'ALPHAVANTAGE_API_KEY'
    assert PROVIDERS['finnhub']['base'] == 'https://finnhub.io'
    assert PROVIDERS['finnhub']['canonical'] == 'FINNHUB_API_KEY'
    assert PROVIDERS['unusual_whales']['base'] == 'https://api.unusualwhales.com'
    assert PROVIDERS['unusual_whales']['canonical'] == 'UNUSUAL_WHALES_API_KEY'


def test_adapter_resolves_each_new_provider_from_canonical_contract() -> None:
    from tools.provider_credentials import provider_credential

    assert provider_credential('alphavantage', {'ALPHA_VANTAGE_API_KEY': 'alpha'}) == 'alpha'
    assert provider_credential('finnhub', {'FINNHUB_API_KEY': 'finn'}) == 'finn'
    assert provider_credential('unusual_whales', {'UW_API_KEY': 'uw'}) == 'uw'


def test_native_client_injects_auth_without_accepting_auth_from_caller() -> None:
    from tools.native_provider_access import build_request

    alpha = build_request('alphavantage', '/query', {'function': 'MARKET_STATUS'}, {'ALPHAVANTAGE_API_KEY': 'a'})
    assert alpha.full_url.startswith('https://www.alphavantage.co/query?')
    assert 'apikey=a' in alpha.full_url
    assert alpha.get_header('Authorization') is None

    finnhub = build_request('finnhub', '/api/v1/quote', {'symbol': 'SPY'}, {'FINNHUB_API_KEY': 'f'})
    assert 'token=f' in finnhub.full_url
    assert finnhub.get_header('Authorization') is None

    whales = build_request('unusual_whales', '/api/market/market-tide', {'interval_5m': 'true'}, {'UNUSUAL_WHALES_API_KEY': 'u'})
    assert 'u' not in whales.full_url
    assert whales.get_header('Authorization') == 'Bearer u'

    with pytest.raises(ValueError, match='caller may not supply authentication'):
        build_request('finnhub', '/api/v1/quote', {'symbol': 'SPY', 'token': 'override'}, {'FINNHUB_API_KEY': 'f'})


def test_native_client_locks_authority_and_read_only_paths() -> None:
    from tools.native_provider_access import build_request

    env = {'FINNHUB_API_KEY': 'f'}
    for unsafe in ('https://attacker.example/x', '//attacker.example/x', '/../x', '/x?token=bad'):
        with pytest.raises(ValueError):
            build_request('finnhub', unsafe, {}, env)


def test_safe_receipt_never_contains_credential_or_raw_vendor_payload(tmp_path: Path) -> None:
    from tools.native_provider_access import collect_snapshot

    secret = 'sensitive-alpha-key'
    payload = {'markets': [{'market_type': 'Equity', 'region': 'United States', 'current_status': 'open'}]}

    def fake_fetch(provider, path, params, env):
        assert provider == 'alphavantage'
        return payload

    receipt = collect_snapshot(
        'alphavantage',
        tmp_path,
        {'ALPHAVANTAGE_API_KEY': secret},
        run_id='test-run',
        fetch=fake_fetch,
    )
    encoded = json.dumps(receipt, sort_keys=True)
    assert secret not in encoded
    assert 'United States' not in encoded
    assert receipt['status'] == 'COLLECTED'
    assert receipt['credential_present'] is True
    assert receipt['payload_sha256']
    assert receipt['top_level_keys'] == ['markets']
    assert receipt['raw_payload_public'] is False


def test_http_failures_are_classified_without_leaking_exception_url(tmp_path: Path) -> None:
    from tools.native_provider_access import collect_snapshot

    def fail(provider, path, params, env):
        raise HTTPError('https://finnhub.io/api/v1/quote?token=SUPERSECRET', 403, 'denied', {}, None)

    receipt = collect_snapshot(
        'finnhub',
        tmp_path,
        {'FINNHUB_API_KEY': 'SUPERSECRET'},
        run_id='test-run',
        fetch=fail,
    )
    encoded = json.dumps(receipt)
    assert 'SUPERSECRET' not in encoded
    assert receipt['status'] == 'BLOCKED_ENTITLEMENT_OR_PERMISSION'


def test_missing_credential_fails_closed_without_network(tmp_path: Path) -> None:
    from tools.native_provider_access import collect_snapshot

    called = False

    def should_not_call(*args):
        nonlocal called
        called = True
        raise AssertionError('network must not run')

    receipt = collect_snapshot('unusual_whales', tmp_path, {}, run_id='test-run', fetch=should_not_call)
    assert called is False
    assert receipt['status'] == 'BLOCKED_MISSING_CREDENTIAL'


def test_workflow_runs_all_new_providers_with_full_alias_fallback() -> None:
    text = WORKFLOW.read_text()
    assert "matrix:\n        provider: [alphavantage, finnhub, unusual_whales]" in text
    assert 'python -m tools.native_provider_access' in text
    assert 'ALPHAVANTAGE_API_KEY:' in text
    assert 'secrets.ALPHAVANTAGE_API_KEY' in text
    assert 'secrets.ALPHA_VANTAGE_API_KEY' in text
    assert 'FINNHUB_API_KEY:' in text
    assert 'secrets.FINNHUB_API_KEY' in text
    assert 'secrets.FINNHUB_KEY' in text
    assert 'UNUSUAL_WHALES_API_KEY:' in text
    assert 'secrets.UNUSUAL_WHALES_API_KEY' in text
    assert 'secrets.UNUSUAL_WHALES_TOKEN' in text
    assert 'secrets.UW_API_KEY' in text
    assert 'raw/' not in text
