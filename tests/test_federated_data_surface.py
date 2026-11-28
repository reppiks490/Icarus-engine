from __future__ import annotations

import json
from pathlib import Path


MANIFEST = Path('config/data_ingestion_manifest.json')
DIRECTIVE = Path('docs/agent-handoffs/FEDERATED_DATA_COLLECTION.md')
NATIVE_WORKFLOW = Path('.github/workflows/native-five-research.yml')
CL_WORKFLOW = Path('.github/workflows/cl-lab.yml')
INTERREPO_WORKFLOW = Path('.github/workflows/interrepo-peer-intelligence.yml')
NATIVE_SOURCES = Path('tools/native_research_sources.py')
CL_REGISTRY = Path('cl_lab/feeds/registry.py')
MARKET_SOURCES = Path('icarus_engine/market_sources.py')
SOURCE_WATCH = Path('icarus_engine/source_watch.py')
ENGINE_FEEDS = Path('icarus_engine/feeds/__init__.py')
YAHOO_FEED = Path('icarus_engine/feeds/yahoo.py')


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
        'runtime_market_sources',
        'engine_market_feeds',
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


def test_runtime_public_collectors_are_explicit_but_not_misreported_as_always_on() -> None:
    sources = _sources()
    market = MARKET_SOURCES.read_text()
    watch = SOURCE_WATCH.read_text()
    feeds = ENGINE_FEEDS.read_text() + '\n' + YAHOO_FEED.read_text()

    runtime = sources['runtime_market_sources']
    assert runtime['credential_state'] == 'PUBLIC'
    assert runtime['ingestion_state'] == 'DEDICATED_LANE'
    assert runtime['consumption_state'] == 'EVIDENCE_ONLY'
    assert runtime['runtime_status'] == 'OPT_IN_DISABLED_DEFAULT'
    assert runtime['default_enabled'] is False
    for needle in ('cftc', 'bls', 'federal-reserve', 'bea', 'sec', 'coinbase', 'yahoo-dxy'):
        assert needle in market.lower()
    assert '"enabled": False' in watch

    engine = sources['engine_market_feeds']
    assert engine['credential_state'] == 'PUBLIC'
    assert engine['ingestion_state'] == 'DEDICATED_LANE'
    assert engine['consumption_state'] == 'EVIDENCE_ONLY'
    assert engine['runtime_status'] == 'RUNTIME_SELECTED_FEEDS'
    for needle in ('api.exchange.coinbase.com', 'api.kraken.com', 'query1.finance.yahoo.com'):
        assert needle in feeds


def test_eia_spot_snapshots_are_federated_as_staged_research_only_context() -> None:
    source = _sources()["eia_spot_context"]
    assert source["required_for_all_ai_units"] is True
    assert source["credential_state"] == "PUBLIC"
    assert source["ingestion_state"] == "STAGED_CONTENT_UNVERIFIED"
    assert source["consumption_state"] == "EVIDENCE_ONLY"
    assert source["workflow"] is None
    assert source["runtime_status"] == "STATIC_SNAPSHOT_RESEARCH_PANEL_ONLY"
    assert "reppiks490/Icarus:icarus_engine/data/research_context/manifest.json" in source["evidence_paths"]
    assert "reppiks490/Icarus:icarus_engine/server.py" in source["evidence_paths"]
    assert source["series_ids"] == ["eia-brent-daily", "eia-wti-daily", "eia-natural-gas-daily"]
    assert source["data_role"] == "SPOT_CONTEXT_ONLY"
    assert source["automatically_refreshed"] is False
    assert source["execution_authorized"] is False


def test_federation_directive_names_runtime_and_internal_evidence_surfaces() -> None:
    text = DIRECTIVE.read_text().lower()
    for phrase in (
        'automation_intelligence/manifest.json',
        'native-five-research',
        'yahoo-dxy',
        'icarus_engine/market_sources.py',
        'robustness guardian',
        'advanced csv',
        'alpha synthesis',
        'flow microstructure',
        'apex council',
        'automation_intelligence/interrepo/latest.json',
        'automation_intelligence/sentinel/data_health.json',
    ):
        assert phrase in text


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


def test_active_specialist_evidence_is_not_siloed_from_other_ai_units() -> None:
    sources = _sources()
    required = {
        'robustness_guardian_evidence',
        'advanced_csv_evidence',
        'alpha_synthesis_evidence',
        'flow_microstructure_evidence',
        'apex_council_evidence',
        'mcp_interface_evidence',
        'coordination_fabric',
    }
    assert required <= set(sources)
    for source_id in required:
        row = sources[source_id]
        assert row['required_for_all_ai_units'] is True
        assert row['credential_state'] == 'NOT_APPLICABLE'
        assert row['consumption_state'] == 'EVIDENCE_ONLY'
        assert row['evidence_paths']

    assert any(path.startswith('reppiks490/icarus-csv-evidence-lab:') for path in sources['advanced_csv_evidence']['evidence_paths'])


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
