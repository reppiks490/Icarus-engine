from pathlib import Path


WORKFLOW = Path(".github/workflows/restored-five-durability-watchdog.yml")


def test_restored_five_workflow_refreshes_before_decision_and_fails_closed_after() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert text.count("- name: Commit verified recovery state") == 1
    assert text.count("- name: Refresh main after grace") == 1
    assert text.count("git pull --rebase origin main") == 1
    assert text.count("git push origin HEAD:main") == 1
    assert "\n || true)\"" not in text

    commit_block = text.split("- name: Commit verified recovery state", 1)[1]
    assert "git pull --rebase origin main" not in commit_block
    assert "Never rebase a recovery" in commit_block


def test_restored_five_scope_guard_closes_regex_before_shell_fallback() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    guard_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("invalid=")]
    assert len(guard_lines) == 1
    guard = guard_lines[0]
    assert "grep -Ev" in guard
    assert "$' || true)" in guard
