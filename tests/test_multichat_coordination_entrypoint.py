from pathlib import Path


AGENTS = Path('AGENTS.md')
COORD = Path('coordination/README.md')


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


def test_legacy_engine_coordination_is_historical_not_authoritative():
    text = COORD.read_text(encoding='utf-8').lower()
    assert 'historical evidence' in text
    assert 'not current task ownership or write locks' in text
    assert 'reppiks490/icarus-owner-actions' in text
    assert 'no model family owns a task' in text
    assert 'waiting/dependency' in text
    assert 'cooperate' in text
    assert 'config/data_ingestion_manifest.json' in text
    assert 'never start a task that is on the other ai' not in text
    assert 'send a message and wait for the answer' not in text
