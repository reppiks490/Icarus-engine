from pathlib import Path


WORKFLOW = Path(".github/workflows/github-native-ai-plane.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_has_dark_safe_schedule_and_manual_dispatch() -> None:
    text = _text()
    assert 'cron: "4-59/5 * * * *"' in text
    assert "workflow_dispatch:" in text
    assert "execute_model:" in text
    assert "requested_lane:" in text
    assert "requested_slot_utc:" in text


def test_workflow_has_least_required_write_permission_and_serial_concurrency() -> None:
    text = _text()
    assert "contents: write" in text
    assert "cancel-in-progress: false" in text
    assert "group: github-native-ai-plane" in text


def test_workflow_uses_python_311_without_paid_model_credentials() -> None:
    text = _text()
    assert 'python-version: "3.11"' in text
    assert "OPENAI_API_KEY" not in text
    assert "OPENAI_IDENTITY_PROVIDER_ID" not in text
    assert "OPENAI_SERVICE_ACCOUNT_ID" not in text
    assert "OPENAI_WIF_AUDIENCE" not in text
    assert "printenv" not in text


def test_workflow_persists_failure_artifacts_before_failing_job() -> None:
    text = _text()
    assert "continue-on-error: true" in text
    assert "if: always()" in text
    assert "tools.github_native_ai_job" in text
    assert "Fail if lane execution failed" in text


def test_workflow_stages_only_v3_namespace_and_never_force_pushes() -> None:
    text = _text()
    assert "git add automation_intelligence/omega_stack_native_v3" in text
    assert "^automation_intelligence/omega_stack_native_v3/" in text
    assert "git fetch origin main" in text
    assert "git rebase origin/main" in text
    assert "git push origin HEAD:main" in text
    assert "git push --force" not in text
    assert "automation_intelligence/omega_stack_native_v2" not in text


def test_workflow_has_watchdog_driven_push_wakeup_paths() -> None:
    text = _text()
    assert "push:" in text
    assert "branches: [main]" in text
    assert ".github/workflows/github-native-ai-plane.yml" in text
    assert "automation_intelligence/omega_stack_native_v3/control_plane.json" in text
    assert "automation_intelligence/omega_stack_native_v3/reconciliation/**" in text


def test_workflow_invokes_job_as_package_module() -> None:
    text = _text()
    assert "python -m tools.github_native_ai_job" in text
    assert "python tools/github_native_ai_job.py" not in text


def test_workflow_uses_watchdog_workflow_run_wakeup() -> None:
    text = _text()
    assert "workflow_run:" in text
    assert 'workflows: ["automation-durability-watchdog"]' in text
    assert "types: [completed]" in text
    assert "branches: [main]" in text


def test_zero_cost_workflow_does_not_grant_oidc_permission() -> None:
    text = _text()
    assert "id-token: write" not in text
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in text


def test_workflow_evaluates_zero_cost_cutover_before_persisting() -> None:
    text = _text()
    assert "Evaluate zero-cost cutover" in text
    assert "python -m tools.github_native_liveness_cutover --root ." in text
    assert text.index("Evaluate zero-cost cutover") < text.index("Persist v3 artifacts")


def test_workflow_retries_main_push_races_without_force() -> None:
    text = _text()
    assert "for attempt in 1 2 3 4 5" in text
    assert "git fetch origin main" in text
    assert "git rebase origin/main" in text
    assert "git push origin HEAD:main" in text
    assert "sleep $((attempt * 2))" in text
    assert "git push --force" not in text
    assert "force-with-lease" not in text


def test_workflow_runs_bounded_batch_catchup() -> None:
    text = _text()
    assert "--max-pending-slots 5" in text
