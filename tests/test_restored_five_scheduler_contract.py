import json
from pathlib import Path


CONTROL = Path("automation_intelligence/restored_five_native/control_plane.json")

EXPECTED_SCHEDULERS = {
    "robustness_guardian": "6abaf924e0248191b8a11bd1d32bf0b7",
    "advanced_csv": "6abaef9d5c28819190d98a5af7f308b8",
    "alpha_synthesis": "6abaf8d75cf48191bc7ce06bc0006f1c",
    "flow_microstructure": "6abaef8effb48191aa5c959455451681",
    "apex_council": "6ababd570fac81918777c8f809cf67c9",
}


def test_restored_five_control_plane_binds_authoritative_scheduler_ids() -> None:
    payload = json.loads(CONTROL.read_text(encoding="utf-8"))
    lanes = payload["lanes"]
    observed = {lane["name"]: lane["scheduler_id"] for lane in lanes}

    assert observed == EXPECTED_SCHEDULERS
    assert len(set(observed.values())) == 5
    assert "6abda2dc3aa881919b80fa89f1c5122e" not in observed.values()
    assert payload["execution_authorized"] is False
