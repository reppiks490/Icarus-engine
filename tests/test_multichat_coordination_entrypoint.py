from pathlib import Path


AGENTS = Path('AGENTS.md')
CRED_ENTRY = Path('AGENT_CREDENTIALS.md')
COORD = Path('coordination/README.md')
MIRROR = Path('.github/workflows/coordination-mirror.yml')


def test_agent_entrypoint_uses_central_many_chat_bus_and_no_model_task_gate():
    text = AGENTS.read_text(encoding='utf-8').lower()
    assert 'reppiks490/icarus-owner-actions' in text
    assert 'coordination/start_here.md' in text
    assert 'coordination/active.md' in text
    assert 'coordination/collisions.json' in text
    assert 'plan' in text and 'claim' in text and 'waiting' in text
    assert 'live broker arming' in text and 'disabled' in text
    assert 'do not work on any task listed in `coordination/board/claude.md`' not in text
    assert "never start a task that is on the other ai's board" not in text


def test_agent_entrypoint_routes_provider_work_to_github_native_data_access():
    text = AGENTS.read_text(encoding='utf-8').lower()
    assert 'agent_credentials.md' in text
    assert 'github_native_credentials.md' in text
    assert 'config/credential_contract.json' in text
    assert 'config/data_ingestion_manifest.json' in text
    assert 'github_native_data_access.md' in text
    assert 'do not search' in text and '.env' in text
    assert 'github actions' in text
    assert 'plaintext' in text


def test_credential_entrypoint_explains_access_without_secret_possession():
    text = CRED_ENTRY.read_text(encoding='utf-8').lower()
    plain = text.replace('**', '')
    assert 'github_native_data_access.md' in text
    assert 'config/data_ingestion_manifest.json' in text
    assert 'not expected to read or possess secret strings' in text
    assert '$icarus_home/.env' in text
    assert 'dav task comments' in text
    assert 'github-native-credential-health' in text
    assert 'evidence_paths' in text
    assert 'fresh collection' in text and 'github actions' in text
    assert 'admin_token' in text and 'icarus_admin_token' in text
    assert 'local plant / bridge runtime controls' in text
    assert 'not the shared provider credential plane' in plain
    assert 'live broker arming' in text and 'disabled' in text


def test_legacy_engine_coordination_is_historical_not_authoritative():
    text = COORD.read_text(encoding='utf-8').lower()
    assert 'historical evidence' in text
    assert 'not current task' in text
    assert 'ownership' in text and 'write locks' in text
    assert 'reppiks490/icarus-owner-actions' in text
    assert 'no model family owns a task' in text
    assert 'waiting/dependency' in text
    assert 'cooperate' in text
    assert 'config/data_ingestion_manifest.json' in text
    assert 'never start a task that is on the other ai' not in text
    assert 'send a message and wait for the answer' not in text


def test_coordination_mirror_has_redundant_trusted_refresh_triggers():
    text = MIRROR.read_text(encoding='utf-8').lower()
    # Cron remains a fast refresh path, but is shifted away from the busiest minute boundary.
    assert '3-58/5 * * * *' in text
    # The already-running local shadow is a trusted 10-minute fallback if GitHub drops a cron event.
    assert 'workflow_run:' in text
    assert 'restored-five-local-shadow' in text
    assert 'types: [completed]' in text
    # Manual recovery must remain available and the mirror must stay a read-only fetch of the central bus.
    assert 'workflow_dispatch:' in text
    assert 'icarus-owner-actions/main/coordination/index.json' in text
    assert 'permissions:' in text and 'contents: write' in text
