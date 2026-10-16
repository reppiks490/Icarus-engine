from __future__ import annotations

import json
from pathlib import Path


MANIFEST = Path('config/federated_repo_evidence.json')
HANDOFF = Path('docs/agent-handoffs/CROSS_REPO_EVIDENCE.md')


def test_repository_family_is_complete_and_role_qualified() -> None:
    data = json.loads(MANIFEST.read_text())
    assert data['required_for_every_ai_unit'] is True
    assert data['authority'] == 'RESEARCH_EVIDENCE_ONLY'
    rows = {item['repository']: item for item in data['repositories']}
    required = {
        'reppiks490/Icarus',
        'reppiks490/Icarus-engine',
        'reppiks490/divine-providence',
        'reppiks490/icarus-csv-evidence-lab',
        'reppiks490/icarus-causal-router',
        'reppiks490/icarus-owner-actions',
    }
    assert required == set(rows)
    for row in rows.values():
        assert row['state'] == 'ACTIVE'
        assert row['role']
        assert row['data_authority']
        assert row['evidence_paths']


def test_evidence_classes_cannot_be_confused_with_market_data() -> None:
    rows = {item['repository']: item for item in json.loads(MANIFEST.read_text())['repositories']}
    assert rows['reppiks490/Icarus-engine']['data_authority'] == 'CANONICAL_LEDGER_AND_COLLECTION'
    assert rows['reppiks490/divine-providence']['data_authority'] == 'EVIDENCE_PRODUCER'
    assert rows['reppiks490/icarus-csv-evidence-lab']['data_authority'] == 'EVIDENCE_PRODUCER'
    assert rows['reppiks490/icarus-causal-router']['data_authority'] == 'SYNTHETIC_ASSURANCE_ONLY'
    assert rows['reppiks490/icarus-owner-actions']['data_authority'] == 'GOVERNANCE_EVIDENCE_ONLY'
    assert 'not live market validation' in rows['reppiks490/icarus-causal-router']['limitations']


def test_divine_providence_independent_official_feed_surface_is_explicit() -> None:
    rows = {item['repository']: item for item in json.loads(MANIFEST.read_text())['repositories']}
    public = set(rows['reppiks490/divine-providence']['public_sources'])
    assert public == {'Federal Reserve press feed', 'ECB press feed', 'SEC press-release feed'}
    assert 'scripts/institution/sources.py' in rows['reppiks490/divine-providence']['evidence_paths']


def test_crossrepo_handoff_requires_shared_ledger_and_zero_internal_gaps() -> None:
    text = HANDOFF.read_text().lower()
    for phrase in (
        'every ai unit',
        'config/federated_repo_evidence.json',
        'config/data_ingestion_manifest.json',
        'reppiks490/divine-providence',
        'reppiks490/icarus-csv-evidence-lab',
        'reppiks490/icarus-causal-router',
        'reppiks490/icarus-owner-actions',
        'do not copy plaintext credentials',
        'zero known icarus-owned gaps',
    ):
        assert phrase in text
