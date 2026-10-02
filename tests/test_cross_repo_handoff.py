from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cross_repo_handoff_is_revision_pinned_and_non_executing():
    handoff = json.loads((ROOT / "integration" / "ICARUS_MAIN_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["producer_repository"] == "reppiks490/Icarus-engine"
    assert handoff["target_repository"] == "reppiks490/Icarus"
    assert len(handoff["producer_revision"]) == 40
    assert len(handoff["target_revision"]) == 40
    assert handoff["authority_requested"] == "RESEARCH"
    assert handoff["authority_granted"] == "RESEARCH"
    assert all("execution" not in claim.lower() or "no " in claim.lower() for claim in handoff["claims"])


def test_readme_has_no_unresolved_merge_markers():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert "\n=======\n" not in text
    assert ">>>>>>>" not in text
    assert "reppiks490/Icarus" in text
