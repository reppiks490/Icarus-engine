import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "automation_intelligence" / "manifest.json"


def _load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_scheduler_topology_is_internally_consistent():
    manifest = _load_manifest()
    topology = manifest["scheduler_topology"]

    active = topology["active"]
    assert topology["active_count"] == len(active) == 5

    minutes = [item["minute"] for item in active]
    assert minutes == [5, 15, 25, 35, 45]
    assert len(set(minutes)) == 5

    titles = [item["title"] for item in active]
    assert len(set(titles)) == 5
    assert sum(item["type"] == "agent" for item in active) == 3
    assert sum(item["type"] == "data" for item in active) == 2


def test_scheduler_agent_bindings_match_agent_fabric_lanes():
    manifest = _load_manifest()
    topology = manifest["scheduler_topology"]
    lanes = manifest["agent_fabric_lanes"]["lanes"]

    by_title = {item["title"]: item for item in topology["active"]}

    for lane in lanes.values():
        scheduled = by_title[lane["schedule_title"]]
        assert scheduled["type"] == "agent"
        assert scheduled["repository"] == manifest["repository"]
        assert scheduled["root"] == lane["path"]


def test_scheduler_topology_preserves_shadow_only_authority_and_collision_guard():
    manifest = _load_manifest()

    assert manifest["execution_authorized"] is False
    assert manifest["agent_fabric_lanes"]["execution_authorized"] is False

    guard = manifest["agent_fabric_lanes"]["repository_guards"]
    assert guard["direct_main_code_writes_allowed"] is False
    assert any(
        item["pr_number"] == 2
        and item["path"] == "icarus_engine/research_service.py"
        and item["status"] == "OPEN_OVERLAP_REQUIRES_RECONCILIATION"
        for item in guard["known_open_pr_conflicts"]
    )
