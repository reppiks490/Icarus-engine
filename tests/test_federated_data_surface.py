from __future__ import annotations

import json
from pathlib import Path


MANIFEST = Path('config/data_ingestion_manifest.json')
NATIVE_WORKFLOW = Path('.github/workflows/native-five-research.yml')
CL_WORKFLOW = Path('.github/workflows/cl-lab.yml')
INTERREPO_WORKFLOW = Path('.github/workflows/interrepo-peer-intelligence.yml')
NATIVE_SOURCES = Path('tools/native_research_sources.py')
CL_REGISTRY = Path('cl_lab/feeds/registry.py')


def _sources() -> dict[str, dict]:
    data = json.loads(MANIFEST.read_text())
    return {item['id']: item for item in data['sources']}


def test_every_active_public_data_fabric_is_federated() -> None:
    sources = _sources()
    required = {
        'native_five_research',
        'cl_lab_data_fabric',
        'coinbase_public',
        'kraken_public',
        'binance_public_bulk',
        'cboe_indices',
        'cftc_positioning',
        'us_treasury_fiscal',
        'official_release_feeds',
        'interrepo_peer_intelligence',
    }
    assert required <= set(sources)

    for source_id in required:
        row = sources[source_id]
        assert row['required_for_all_ai_units'] is True
        assert row['evidence_paths']
        assert row['ingestion_state'] in {'LIVE', 'PARTIAL', 'DEDICATED_LANE'}
        assert row['consumption_state'] in {'LIVE', 'PARTIAL', 'DEDICATED_LANE', 'EVIDENCE_ONLY'}


def test_public_venue_and_agency_sources_match_live_collectors() -> None:
    native = NATIVE_SOURCES.read_text()
    cl = CL_REGISTRY.read_text()
    sources = _sources()

    expected = {
        'coinbase_public': ('api.exchange.coinbase.com', 'PUBLIC'),
        'kraken_public': ('api.kraken.com', 'PUBLIC'),
        'binance_public_bulk': ('binance', 'PUBLIC'),
        'cboe_indices': ('cboe', 'PUBLIC'),
        'cftc_positioning': ('cftc', 'PUBLIC'),
        'us_treasury_fiscal': ('treasury', 'PUBLIC'),
    }
    combined = (native + '\n' + cl).lower()
    for source_id, (needle, credential_state) in expected.items():
        assert needle.lower() in combined
        assert sources[source_id]['credential_state'] == credential_state

    release = sources['official_release_feeds']
    assert release['credential_state'] == 'PUBLIC'
    for needle in ('federalreserve.gov', 'ecb.europa.eu', 'bls.gov'):
        assert needle in native


def test_active_fabric_workflows_are_named_in_manifest() -> None:
    sources = _sources()
    assert 'schedule:' in NATIVE_WORKFLOW.read_text()
    assert 'schedule:' in CL_WORKFLOW.read_text()
    assert 'schedule:' in INTERREPO_WORKFLOW.read_text()
    assert sources['native_five_research']['workflow'] == '.github/workflows/native-five-research.yml'
    assert sources['cl_lab_data_fabric']['workflow'] == '.github/workflows/cl-lab.yml'
    assert sources['interrepo_peer_intelligence']['workflow'] == '.github/workflows/interrepo-peer-intelligence.yml'


def test_supplemental_providers_expose_both_exhaustive_and_native_canary_evidence() -> None:
    sources = _sources()
    for provider in ('unusual_whales', 'alpha_vantage', 'finnhub'):
        paths = sources[provider]['evidence_paths']
        stem = 'alphavantage' if provider == 'alpha_vantage' else provider
        assert f'automation_intelligence/provider_collection_v1/native_access/latest/{stem}.json' in paths
        assert sources[provider]['canary_workflow'] == '.github/workflows/native-provider-access.yml'


def test_internal_peer_packet_is_mandatory_federated_evidence() -> None:
    row = _sources()['interrepo_peer_intelligence']
    assert row['credential_state'] == 'NOT_APPLICABLE'
    assert row['access_mode'] == 'repository'
    assert 'automation_intelligence/interrepo/latest.json' in row['evidence_paths']


def test_data_sentinel_monitors_every_federated_collection_and_promotion_lane() -> None:
    from tools.data_sentinel import WORKFLOWS

    required = {
        'provider-exhaustive-collection.yml',
        'provider-supplemental-collection.yml',
        'provider-supplemental-promote.yml',
        'native-provider-access.yml',
        'native-five-research.yml',
        'cl-lab.yml',
        'databento-depth-corpus.yml',
        'databento-depth-research-context.yml',
        'depth-vault.yml',
        'cl-depth-sweep.yml',
        'sec-edgar-data.yml',
        'official-economic-events.yml',
        'external-data-fabric.yml',
        'interrepo-peer-intelligence.yml',
    }
    assert required <= set(WORKFLOWS)
