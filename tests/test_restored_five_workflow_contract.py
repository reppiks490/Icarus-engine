import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone


WORKFLOW = Path(".github/workflows/restored-five-durability-watchdog.yml")


def test_restored_five_workflow_refreshes_before_decision_and_recomputes_after_contention() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert text.count("- name: Commit verified recovery state") == 1
    assert text.count("- name: Refresh main after grace") == 1
    assert text.count("git pull --rebase origin main") == 1
    assert text.count("git push origin HEAD:main") == 4
    assert "\n || true)\"" not in text

    commit_block = text.split("- name: Commit verified recovery state", 1)[1]
    assert "git pull --rebase origin main" not in commit_block
    assert "Never rebase a recovery" in commit_block
    recovery_commit_block = commit_block.split("- name: Bind committed finalizations into heartbeats", 1)[0]
    assert recovery_commit_block.count("git push origin HEAD:main") == 2
    assert "for attempt in 1 2 3 4 5; do" in recovery_commit_block
    assert "git fetch origin main" in recovery_commit_block
    assert "git reset --hard origin/main" in recovery_commit_block
    assert "python tools/restored_five_durability_watchdog.py" in recovery_commit_block
    assert "--stabilization-fallback" in recovery_commit_block
    assert text.index("- name: Bind committed finalizations into heartbeats") > text.index(
        "- name: Commit verified recovery state"
    )
    mirror_block = text.split("- name: Bind committed finalizations into heartbeats", 1)[1]
    assert mirror_block.count("git push origin HEAD:main") == 2
    assert "--stabilization-fallback" not in mirror_block
    assert "finalization_state.json" not in mirror_block
    assert "git pull" not in mirror_block
    assert "for attempt in 1 2 3 4 5; do" in mirror_block
    assert "git fetch origin main" in mirror_block
    assert "git reset --hard origin/main" in mirror_block
    assert "python tools/restored_five_durability_watchdog.py" in mirror_block
    assert "if: env.WATCHDOG_NO_CHANGE != '1'" in mirror_block


def test_restored_five_scope_guard_closes_regex_before_shell_fallback() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    guard_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("invalid=")]
    assert len(guard_lines) >= 2
    for guard in guard_lines:
        assert "grep -Ev" in guard
        assert "$' || true)" in guard


def test_workflow_closes_recovered_receipts_with_real_git_commit_readback(tmp_path) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    recovery_block = text.split("- name: Reconcile restored ICARUS lanes", 1)[1].split(
        "- name: Stage only restored-lane runtime state", 1
    )[0]
    mirror_block = text.split("- name: Bind committed finalizations into heartbeats", 1)[1]
    recovery_specs = [spec.split("|") for spec in re.findall(r'--lane "([^"]+)"', recovery_block)]
    mirror_specs = re.findall(r'--lane "([^"]+)"', mirror_block)
    # Retry blocks intentionally repeat the same four lane specifications.  The
    # contract is set equality rather than exact occurrence count.
    assert len(recovery_specs) == 4
    assert set(mirror_specs) == {"|".join(spec[:3]) for spec in recovery_specs}

    source = Path("tools/restored_five_durability_watchdog.py").resolve()
    spec = importlib.util.spec_from_file_location("lifecycle_watchdog", source)
    assert spec and spec.loader
    watchdog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watchdog)
    repo = tmp_path / "repo"
    repo.mkdir()
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Offline watchdog test")
    git("config", "user.email", "test@example.com")
    git("config", "core.autocrlf", "false")
    git("remote", "add", "origin", remote.as_uri())
    for lane, lane_root, scheduler_id, minute, prefix in recovery_specs:
        root = repo / lane_root
        root.mkdir(parents=True)
        for name, payload in {
            "startup_state.json": {"RUN_ID": None, "RUN_STATUS": "EMPTY_READY", "execution_authorized": False},
            "heartbeat.json": {},
            "finalization_state.json": {
                "schema_version": "scheduler-finalization-v5.7",
                "RUN_ID": f"{prefix}-20260930T200000Z",
                "RUN_STATUS": "RUN_PERSISTED",
                "completion_semantics": "DURABILITY_RECEIPT_ONLY",
                "execution_authorized": False,
            },
        }.items():
            (root / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "synthetic old receipts")
    now = datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc)
    for lane, lane_root, scheduler_id, minute, prefix in recovery_specs:
        watchdog.reconcile_lane(repo, lane, lane_root, scheduler_id, 30, 12, now)
        watchdog.recover_stabilization_receipt(repo, lane, lane_root, scheduler_id, int(minute), prefix, 12, None, now)
        root = repo / lane_root
        assert json.loads((root / "heartbeat.json").read_text())["RUN_ID"] != json.loads(
            (root / "finalization_state.json").read_text()
        )["RUN_ID"]
    git("add", ".")
    git("commit", "-m", "synthetic recovered finalizations")
    git("push", "origin", "HEAD:main")
    receipt_commit = git("rev-parse", "HEAD")
    receipt_blobs = {spec[1]: git("rev-parse", f"HEAD:{spec[1]}/finalization_state.json") for spec in recovery_specs}
    command = [sys.executable, str(source), "--repo-root", str(repo)]
    for mirror_spec in sorted(set(mirror_specs)):
        command.extend(["--lane", mirror_spec])
    subprocess.run(command, check=True, capture_output=True, text=True)
    expected_paths = sorted(f"{spec[1]}/heartbeat.json" for spec in recovery_specs)
    assert git("diff", "--name-only").splitlines() == expected_paths
    git("add", "--", *expected_paths)
    git("commit", "-m", "synthetic committed heartbeat mirrors")
    git("push", "origin", "HEAD:main")
    for lane, lane_root, scheduler_id, minute, prefix in recovery_specs:
        heartbeat = json.loads(git("show", f"HEAD:{lane_root}/heartbeat.json"))
        finalization = json.loads(git("show", f"HEAD:{lane_root}/finalization_state.json"))
        assert heartbeat["RUN_ID"] == finalization["RUN_ID"]
        assert heartbeat["RUN_STATUS"] == "RUN_PERSISTED"
        assert heartbeat["finalization_commit_sha"] == receipt_commit
        assert heartbeat["finalization_state_blob_sha"] == receipt_blobs[lane_root]
        assert git("rev-parse", f"HEAD:{lane_root}/finalization_state.json") == receipt_blobs[lane_root]
        assert heartbeat["execution_authorized"] is finalization["execution_authorized"] is False
    head = git("rev-parse", "HEAD")
    assert git("ls-remote", "origin", "refs/heads/main").split()[0] == head
    repeated = subprocess.run(command, check=True, capture_output=True, text=True)
    assert json.loads(repeated.stdout)["changed"] == []
    assert git("status", "--porcelain") == ""
    assert git("rev-parse", "HEAD") == head
