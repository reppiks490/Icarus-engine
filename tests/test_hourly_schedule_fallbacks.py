from pathlib import Path


ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _assert_redundant_hourly_trigger(name: str, cron: str) -> None:
    text = _workflow(name)
    assert f"cron: {cron}" in text or f"cron: '{cron}'" in text or f'cron: "{cron}"' in text
    assert "workflow_run:" in text
    assert 'workflows: ["provider-exhaustive-collection"]' in text or "workflows: ['provider-exhaustive-collection']" in text
    assert "types: [completed]" in text
    assert "github.event.workflow_run.event == 'schedule'" in text or 'github.event.workflow_run.event == "schedule"' in text
    assert "github.event.workflow_run.conclusion == 'success'" in text or 'github.event.workflow_run.conclusion == "success"' in text
    assert 'workflows: ["data-sentinel"]' not in text


def test_native_five_has_schedule_fallback_without_replacing_hourly_cron():
    _assert_redundant_hourly_trigger("native-five-research.yml", "41 * * * *")


def test_sec_edgar_has_schedule_fallback_without_replacing_hourly_cron():
    _assert_redundant_hourly_trigger("sec-edgar-data.yml", "7 * * * *")
