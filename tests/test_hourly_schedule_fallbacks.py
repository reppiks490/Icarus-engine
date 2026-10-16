from pathlib import Path


ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _assert_redundant_hourly_trigger(name: str, cron: str, marker: str) -> None:
    text = _workflow(name)
    assert f"cron: {cron}" in text or f"cron: '{cron}'" in text or f'cron: "{cron}"' in text
    assert "workflow_run:" in text
    assert 'workflows: ["restored-five-local-shadow"]' in text or "workflows: ['restored-five-local-shadow']" in text
    assert "types: [completed]" in text
    assert "UPSTREAM_EVENT: ${{ github.event.workflow_run.event }}" in text
    assert "UPSTREAM_CONCLUSION: ${{ github.event.workflow_run.conclusion }}" in text
    assert '"$UPSTREAM_EVENT" != \'schedule\'' in text
    assert '"$UPSTREAM_CONCLUSION" != \'success\'' in text
    assert marker in text
    assert "FALLBACK_MAX_AGE_SECONDS: '4500'" in text or 'FALLBACK_MAX_AGE_SECONDS: "4500"' in text
    assert "git log -1 --format=%ct --" in text
    assert "run_needed" in text
    assert "needs.freshness.outputs.run_needed == 'true'" in text or 'needs.freshness.outputs.run_needed == "true"' in text
    assert 'workflows: ["data-sentinel"]' not in text
    assert 'workflows: ["provider-exhaustive-collection"]' not in text


def test_native_five_has_staleness_gated_schedule_fallback_without_replacing_hourly_cron():
    _assert_redundant_hourly_trigger(
        "native-five-research.yml",
        "41 * * * *",
        "automation_intelligence/native_research_v1/latest.json",
    )


def test_sec_edgar_has_staleness_gated_schedule_fallback_without_replacing_hourly_cron():
    _assert_redundant_hourly_trigger(
        "sec-edgar-data.yml",
        "7 * * * *",
        "automation_intelligence/cl_lab/sec_edgar_manifest.json",
    )
