from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


WORKFLOW = Path('.github/workflows/provider-supplemental-collection.yml')
PROMOTER = Path('.github/workflows/provider-supplemental-promote.yml')
SUPPLEMENT = Path('config/provider_endpoint_catalog_supplemental.json')
MANIFEST = Path('config/data_ingestion_manifest.json')
DIRECTIVE = Path('docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md')


def test_credentialed_missing_providers_are_admitted_to_additive_runtime_collector() -> None:
    from tools import provider_supplemental_collection as s

    for provider in ('unusual_whales', 'alphavantage', 'finnhub'):
        assert provider in s.EXTENDED_PROVIDERS

    assert s.EXTENDED_PROVIDERS['unusual_whales']['auth'] == 'bearer'
    assert s.EXTENDED_PROVIDERS['alphavantage']['auth'] == 'alphavantage'
    assert s.EXTENDED_PROVIDERS['finnhub']['auth'] == 'finnhub'


def test_supplemental_pagination_accepts_only_relative_uw_next_url_without_secret_query() -> None:
    from tools import provider_supplemental_collection as s

    page = s.next_page(
        'unusual_whales',
        {'data': {'next_url': '/api/crypto/list_tokens?next_token=abc&limit=1000'}},
        {'limit': 1000},
    )
    assert page == {
        'path': '/api/crypto/list_tokens',
        'params': {'next_token': 'abc', 'limit': '1000'},
    }
    page = s.next_page(
        'unusual_whales',
        {'data': {'next_token': 'xyz'}},
        {'limit': 1000},
    )
    assert page == {'params': {'limit': 1000, 'next_token': 'xyz'}}


def test_alpha_provider_messages_fail_closed_for_rate_and_entitlement() -> None:
    from tools import provider_exhaustive_collection as core
    from tools import provider_supplemental_collection as s

    with pytest.raises(core.ProviderFailure, match='429'):
        s.check_response({'Information': 'API call frequency limit reached'})
    with pytest.raises(core.ProviderFailure, match='403'):
        s.check_response({'Information': 'This is a premium endpoint; upgrade required'})


def test_finnhub_credential_never_needs_to_be_serialized_in_catalog() -> None:
    data = json.loads(SUPPLEMENT.read_text())
    encoded = json.dumps(data).lower()
    assert 'x-finnhub-token' not in encoded
    assert 'apikey' not in encoded
    assert 'authorization' not in encoded


def test_provider_workflow_runs_missing_github_native_providers_and_injects_canonical_credentials() -> None:
    text = WORKFLOW.read_text()
    matrix = re.search(r'provider:\s*\[([^\]]+)\]', text)
    assert matrix
    providers = {item.strip() for item in matrix.group(1).split(',')}
    assert providers == {'unusual_whales', 'alphavantage', 'finnhub'}
    for canonical in ('UNUSUAL_WHALES_API_KEY', 'ALPHAVANTAGE_API_KEY', 'FINNHUB_API_KEY'):
        assert f'          {canonical}:' in text
        assert f'secrets.{canonical}' in text
    assert 'automation_intelligence/mcp_interface/events/' not in text.split('path: |', 1)[1].split('include-hidden-files:', 1)[0].replace(
        'automation_intelligence/mcp_interface/events/provider-coverage-supplemental-${{ github.run_id }}-${{ matrix.provider }}.json',
        '',
    )


def test_promoter_only_accepts_trusted_main_runs_and_never_commits_raw_archives() -> None:
    text = PROMOTER.read_text()
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert 'github.event.workflow_run.head_repository.full_name == github.repository' in text
    for event in ("'schedule'", "'workflow_dispatch'", "'push'"):
        assert event in text
    assert 'actions: read' in text
    assert 'contents: write' in text
    assert 'python -m tools.provider_research_context --repo-root .' in text
    assert '.provider_collection_archives' not in text.split('git add', 1)[1]
    assert 'provider_collection_v1/research_context.json' in text


def test_supplemental_catalog_covers_missing_provider_families() -> None:
    data = json.loads(SUPPLEMENT.read_text())
    operations = data['operations']
    by_provider: dict[str, list[dict]] = {}
    for op in operations:
        by_provider.setdefault(op['provider'], []).append(op)

    assert {'unusual_whales', 'alphavantage', 'finnhub'} <= set(by_provider)

    uw = by_provider['unusual_whales']
    uw_paths = {op['path'] for op in uw}
    required_uw_paths = {
        '/api/market/daily-report',
        '/api/market/market-tide',
        '/api/net-flow/expiry',
        '/api/darkpool/recent',
        '/api/screener/stocks',
        '/api/stock/{ticker}/gex-levels',
        '/api/stock/{ticker}/greek-exposure',
        '/api/stock/{ticker}/spot-exposures',
        '/api/stock/{ticker}/spot-exposures/strike',
        '/api/stock/{ticker}/greek-flow',
        '/api/stock/{ticker}/net-prem-ticks',
        '/api/stock/{ticker}/nope',
        '/api/darkpool/{ticker}',
        '/api/darkpool/{ticker}/price-levels',
        '/api/earnings/premarket',
        '/api/earnings/{ticker}',
        '/api/insider/{ticker}/ticker-flow',
        '/api/congress/unusual-trades',
        '/api/crypto/list_tokens',
    }
    assert required_uw_paths <= uw_paths

    alpha_functions = {
        p['example']
        for op in by_provider['alphavantage']
        for p in op.get('parameters', [])
        if p['name'] == 'function'
    }
    assert {
        'MARKET_STATUS', 'GLOBAL_QUOTE', 'TIME_SERIES_INTRADAY', 'NEWS_SENTIMENT',
        'INSIDER_TRANSACTIONS', 'CONGRESS_TRADES', 'INSTITUTIONAL_HOLDINGS',
        'TREASURY_YIELD', 'FEDERAL_FUNDS_RATE', 'CPI', 'INFLATION', 'UNEMPLOYMENT',
        'BRENT', 'WTI',
    } <= alpha_functions

    finnhub_paths = {op['path'] for op in by_provider['finnhub']}
    assert {
        '/stock/symbol', '/quote', '/company-news', '/news', '/calendar/earnings',
        '/calendar/economic', '/stock/insider-transactions', '/stock/ownership',
        '/stock/recommendation', '/stock/price-target', '/stock/metric', '/country',
    } <= finnhub_paths


def test_manifest_forces_three_stage_truth_and_federated_access() -> None:
    data = json.loads(MANIFEST.read_text())
    sources = {item['id']: item for item in data['sources']}
    required = {
        'massive', 'twelve_data', 'fmp', 'eodhd', 'tiingo', 'fred', 'bybit',
        'intrinio', 'quiver', 'alpaca', 'tickstream', 'unusual_whales',
        'alpha_vantage', 'finnhub', 'databento_depth', 'sec_edgar',
        'official_economic_events', 'external_data_fabric',
    }
    assert required <= set(sources)
    for source in sources.values():
        assert source['required_for_all_ai_units'] is True
        assert source['access_mode']
        assert source['credential_state'] in {'PRESENT', 'MISSING', 'PUBLIC', 'NOT_APPLICABLE', 'EXTERNAL_CONNECTOR'}
        assert source['ingestion_state'] in {'LIVE', 'PARTIAL', 'BLOCKED', 'STAGED', 'STAGED_CONTENT_UNVERIFIED', 'INTERACTIVE_ONLY', 'DEDICATED_LANE'}
        assert source['consumption_state'] in {'LIVE', 'PARTIAL', 'BLOCKED', 'EVIDENCE_ONLY', 'DEDICATED_LANE', 'UNVERIFIED', 'VERIFIED_IN_THIS_WORKSPACE; OTHER_AGENT_ACCESS_UNVERIFIED'}
        assert source['evidence_paths']

    assert sources['unusual_whales']['credential_state'] == 'PRESENT'
    assert sources['unusual_whales']['access_mode'] == 'github_actions+connector'
    assert sources['unusual_whales']['workflow'] == '.github/workflows/provider-supplemental-collection.yml'

    for source_id in ('alpha_vantage', 'finnhub'):
        source = sources[source_id]
        assert source['credential_state'] == 'PRESENT'
        assert source['access_mode'] == 'github_actions'
        assert source['workflow'] == '.github/workflows/provider-supplemental-collection.yml'

    assert sources['finnhub']['ingestion_state'] == 'BLOCKED'
    assert sources['finnhub']['consumption_state'] == 'BLOCKED'
    assert sources['finnhub']['runtime_status'] == 'BLOCKED_AUTHENTICATION'


def test_all_ai_units_receive_persistent_data_plane_directive() -> None:
    text = DIRECTIVE.read_text().lower()
    for phrase in (
        'every ai unit',
        'config/data_ingestion_manifest.json',
        'provider-exhaustive-collection.yml',
        'provider-supplemental-collection.yml',
        'unusual whales',
        'databento',
        'sec/edgar',
        'official bls/bea/census/fomc economic-event',
        'provider_collection_v1/research_context.json',
        'do not claim',
        'runtime evidence',
    ):
        assert phrase in text
