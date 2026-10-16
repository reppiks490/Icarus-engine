from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools import provider_exhaustive_collection as core
from tools import provider_supplemental_collection as base
from tools import provider_supplemental_transport as transport


WORKFLOW = Path('.github/workflows/provider-supplemental-collection.yml')
PROMOTER = Path('.github/workflows/provider-supplemental-promote.yml')


def test_workflow_accepts_secret_and_variable_aliases_and_restores_cache() -> None:
    text = WORKFLOW.read_text()
    required = {
        'UNUSUAL_WHALES_API_KEY': ('UNUSUAL_WHALES_API_KEY', 'UNUSUAL_WHALES_TOKEN', 'UW_API_KEY'),
        'ALPHAVANTAGE_API_KEY': ('ALPHAVANTAGE_API_KEY', 'ALPHA_VANTAGE_API_KEY', 'ALPHA_VANTAGE_KEY'),
        'FINNHUB_API_KEY': ('FINNHUB_API_KEY', 'FINNHUB_KEY'),
    }
    for canonical, aliases in required.items():
        line = next(line for line in text.splitlines() if line.strip().startswith(canonical + ':'))
        for alias in aliases:
            assert f'secrets.{alias}' in line
            assert f'vars.{alias}' in line

    assert 'actions/cache/restore@v4' in text
    assert 'actions/cache/save@v4' in text
    assert 'provider-supplemental-v1-${{ matrix.provider }}-' in text


def test_finnhub_uses_header_auth_and_never_places_key_in_url(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return b'{"c":1}'

    class Opener:
        def open(self, request, timeout):
            captured['url'] = request.full_url
            captured['headers'] = dict(request.header_items())
            captured['timeout'] = timeout
            return Response()

    monkeypatch.setattr(transport.urllib.request, 'build_opener', lambda *args: Opener())
    secret = 'fixture-finnhub-secret'
    assert transport.request('finnhub', '/quote', {'symbol': 'AAPL'}, secret) == {'c': 1}
    assert secret not in captured['url']
    assert 'token=' not in captured['url'].lower()
    headers = {key.lower(): value for key, value in captured['headers'].items()}
    assert headers['x-finnhub-token'] == secret


def test_supplemental_checkpoint_recovers_after_cold_checkout(tmp_path: Path) -> None:
    pytest.importorskip('cryptography')
    base.install_extensions()
    core.next_page = transport.next_page

    operation = {
        'id': 'unusual_whales:get:/api/crypto/trades',
        'provider': 'unusual_whales',
        'path': '/api/crypto/trades',
        'method': 'GET',
        'parameters': [],
    }
    env = {'UNUSUAL_WHALES_API_KEY': 'fixture-uw-key'}

    def first_fetch(provider, path, params, key):
        assert provider == 'unusual_whales'
        assert key == env['UNUSUAL_WHALES_API_KEY']
        return {'data': {'next_token': 'cursor-2', 'data': [{'price': 1.0}]}}

    first = core.cycle(
        tmp_path,
        [operation],
        env,
        run_id='supplemental-first',
        request_budget=1,
        fetch=first_fetch,
    )
    assert first['checkpoint_status'] == 'ENCRYPTED_AES256_GCM'
    checkpoint = tmp_path / core.ROOT / 'checkpoints' / 'unusual_whales.enc'
    assert checkpoint.exists()

    shutil.rmtree(tmp_path / '.provider_collection_cache')
    seen = []

    def second_fetch(provider, path, params, key):
        seen.append(dict(params))
        return {'data': {'data': []}}

    second = core.cycle(
        tmp_path,
        [operation],
        env,
        run_id='supplemental-second',
        request_budget=1,
        fetch=second_fetch,
    )
    assert seen == [{'next_token': 'cursor-2'}]
    assert second['providers']['unusual_whales']['status'] in {'COLLECTED_PARTIAL', 'NO_READY_JOBS'}


def test_promoter_is_main_only_and_does_not_commit_raw_archives() -> None:
    text = PROMOTER.read_text()
    condition = text.split('jobs:', 1)[1].split('runs-on:', 1)[0]
    assert "github.event.workflow_run.head_branch == 'main'" in condition
    assert 'github.event.workflow_run.head_repository.full_name == github.repository' in condition
    staged = text.split("git add", 1)[1]
    assert '.provider_collection_archives' not in staged
    assert 'provider_collection_v1/research_context.json' in staged
