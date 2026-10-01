import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path("tools").resolve()))

from restored_five_native_liveness import Control, Lane, worker_receipt_status  # noqa: E402


def test_watchdog_fallback_receipt_is_not_a_chatgpt_worker_success(tmp_path: Path) -> None:
    lane = Lane(
        name="flow_microstructure",
        title="Microstructure Sensor Grid",
        minute=35,
        scheduler_id="6abaef8effb48191aa5c959455451681",
        worker_root="automation_intelligence/flow",
        run_prefix="flow",
    )
    control = Control(
        repository="reppiks490/Icarus-engine",
        activated_at_utc=datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc),
        grace_minutes=8,
        catchup_horizon_minutes=180,
        timezone="America/Chicago",
        lanes=(lane,),
    )
    slot = datetime(2026, 10, 1, 18, 35, tzinfo=timezone.utc)
    path = tmp_path / lane.worker_root / "finalization_state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema_version": "scheduler-finalization-v5.7",
        "RUN_ID": "flow-20261001T183500Z",
        "RUN_STATUS": "RUN_PERSISTED",
        "completion_semantics": "DURABILITY_RECEIPT_ONLY",
        "history_mode": "git_commit_finalization",
        "work_status": "WATCHDOG_FALLBACK_PERSISTED",
        "receipt_origin": "github_watchdog_stabilization_fallback",
        "worker_execution_observed": False,
        "payload": {"result": "SCHEDULER_WORKER_RECEIPT_MISSED"},
        "execution_authorized": False,
    }), encoding="utf-8")

    status, observed = worker_receipt_status(tmp_path, control, lane, slot)

    assert status == "WATCHDOG_FALLBACK_RECEIPT_PRESENT"
    assert observed["worker_execution_observed"] is False
