"""Replay completion events against the shipped peer-export workflow contract."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from tests_engine.test_interrepo_bridge import _commit_fixture, _fixture_root


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/interrepo-peer-intelligence.yml"
PRODUCERS = ("provider-exhaustive-collection", "native-five-research")


def _workflow_run_publishes(name, conclusion="success", event="schedule", branch="main"):
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger = text.split("  workflow_run:\n", 1)[1].split("  push:\n", 1)[0]
    names_block = trigger.split("    workflows:\n", 1)[1].split("    types:", 1)[0]
    names = [
        ast.literal_eval(line.strip()[2:]) for line in names_block.splitlines()
        if line.strip().startswith("- ")
    ]
    branch_filter = trigger.split("    branches: ", 1)[1].splitlines()[0]
    branches = re.findall(r"[\w/-]+", branch_filter)
    if name not in names or branch not in branches or "types: [completed]" not in trigger:
        return False

    condition = text.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0].strip()
    values = {
        "github.event_name": "workflow_run",
        "github.event.workflow_run.conclusion": conclusion,
        "github.event.workflow_run.event": event,
    }
    for field, value in sorted(values.items(), key=lambda item: -len(item[0])):
        condition = condition.replace(field, repr(value))
    condition = condition.replace("&&", " and ").replace("||", " or ")
    expression = ast.parse(" ".join(condition.split()), mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.Compare, ast.Eq, ast.NotEq, ast.Constant)
    assert all(isinstance(node, allowed) for node in ast.walk(expression)), "Unrecognized dispatch expression"
    return eval(compile(expression, str(WORKFLOW), "eval"), {"__builtins__": {}}, {})


@pytest.mark.parametrize("producer", PRODUCERS)
def test_scheduled_successful_research_completion_publishes_real_revision_bound_packet(tmp_path, producer):
    source = (ROOT / f".github/workflows/{producer}.yml").read_text(encoding="utf-8")
    # Use the name emitted by the actual producer, including its MCP persistence.
    name = source.splitlines()[0].removeprefix("name: ")
    assert name == producer
    assert "git add automation_intelligence/mcp_interface/events/" in source or (
        'git add "automation_intelligence/mcp_interface/events/' in source
    )
    assert "git push origin HEAD:main" in source
    assert "[skip ci]" in source
    assert _workflow_run_publishes(name), "GITHUB_TOKEN receipt pushes need a completion dependency"

    root = _fixture_root(tmp_path)
    head = _commit_fixture(root)
    text = WORKFLOW.read_text(encoding="utf-8")
    export_step = text.split("      - name: Export revision-bound peer packet\n", 1)[1]
    command = shlex.split(export_step.split("run: >-\n", 1)[1].split("\n\n", 1)[0])
    assert command[:3] == ["PYTHONPATH=.", "python", "tools/export_peer_intelligence.py"]
    command[1:3] = [sys.executable, str(ROOT / command[2])]
    before = datetime.now(timezone.utc).replace(microsecond=0)
    subprocess.run(
        command[1:], cwd=root, check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    after = datetime.now(timezone.utc)
    packet = json.loads((root / "automation_intelligence/interrepo/latest.json").read_text())
    assert packet["source_commit"] == head
    assert before <= datetime.fromisoformat(packet["observed_at"].replace("Z", "+00:00")) <= after
    assert packet["execution_authorized"] is False
    assert packet["production_decision_authorized"] is False


@pytest.mark.parametrize("producer", PRODUCERS)
@pytest.mark.parametrize("overrides", [
    {"conclusion": "failure"}, {"conclusion": "cancelled"}, {"conclusion": "skipped"},
    {"event": "push"}, {"event": "workflow_dispatch"}, {"branch": "research-branch"},
])
def test_unsuccessful_unscheduled_or_nonmain_research_completion_cannot_publish(producer, overrides):
    assert not _workflow_run_publishes(producer, **overrides)


def test_unrelated_successful_schedule_cannot_refresh_packet():
    assert not _workflow_run_publishes("cl-federation-watch")

