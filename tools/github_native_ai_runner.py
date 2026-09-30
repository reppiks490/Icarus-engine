from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from tools.github_native_ai_dispatcher import (
    NAMESPACE_ROOT,
    ControlPlane,
    Slot,
    load_control_plane,
    terminal_artifact_exists,
)
from tools.github_native_ai_openai import (
    AuthenticationError,
    ConfigurationError,
    ModelRequest,
    ModelResponse,
    OutputValidationError,
    TransportError,
    call_responses_api,
    validate_lane_output,
)


@dataclass(frozen=True)
class RunResult:
    status: str
    receipt_path: Path | None = None
    output_path: Path | None = None
    failure_path: Path | None = None


ApiCall = Callable[[ModelRequest, str], ModelResponse]
NowFn = Callable[[], datetime]


def _utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _workflow_identity(env: Mapping[str, str]) -> dict[str, str]:
    required = {
        "workflow_run_id": env.get("GITHUB_RUN_ID", ""),
        "workflow_run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
        "workflow_sha": env.get("GITHUB_SHA", ""),
        "repository": env.get("GITHUB_REPOSITORY", ""),
        "branch": env.get("GITHUB_REF_NAME", ""),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ConfigurationError("GitHub workflow metadata missing")
    return required


def build_lane_request(root: Path, control: ControlPlane, slot: Slot) -> ModelRequest:
    shared_path = root / NAMESPACE_ROOT / "lanes" / "shared" / "system.md"
    task_path = root / NAMESPACE_ROOT / "lanes" / slot.lane.name / "prompts" / "task.md"
    try:
        instructions = shared_path.read_text(encoding="utf-8").strip()
        task = task_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ConfigurationError("lane prompt configuration missing") from exc

    context = {
        "control_plane_id": control.control_plane_id,
        "execution_authorized": False,
        "lane": slot.lane.name,
        "slot_id": slot.slot_id,
        "slot_local": slot.scheduled_local.isoformat(),
        "slot_utc": _utc_z(slot.scheduled_utc),
    }
    return ModelRequest(
        lane=slot.lane.name,
        model=control.model,
        reasoning_effort=control.reasoning_effort,
        instructions=instructions,
        input_text=task + "\n\nExecution context (JSON):\n" + json.dumps(context, sort_keys=True, separators=(",", ":")),
    )


def request_fingerprint(request: ModelRequest) -> str:
    canonical = json.dumps(
        {
            "lane": request.lane,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "instructions": request.instructions,
            "input_text": request.input_text,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _artifact_path(root: Path, lane: str, kind: str, slot_id: str, run_id: str) -> Path:
    if lane not in {"omega", "macro", "flow", "aion", "daedalus"}:
        raise ValueError("invalid lane")
    if kind not in {"runs", "outputs", "failures"}:
        raise ValueError("invalid artifact kind")
    return root / NAMESPACE_ROOT / "lanes" / lane / kind / slot_id / f"{run_id}.json"


def _write_json_exclusive(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")


def _failure_result(
    root: Path,
    slot: Slot,
    workflow: dict[str, str],
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    failure_code: str,
) -> RunResult:
    path = _artifact_path(root, slot.lane.name, "failures", slot.slot_id, run_id)
    payload: dict[str, object] = {
        "schema_version": "omega-stack-github-native-failure-v1",
        "engine": slot.lane.name,
        "lane": slot.lane.name,
        "RUN_ID": run_id,
        "SLOT_ID": slot.slot_id,
        "slot_local": slot.scheduled_local.isoformat(),
        "slot_utc": _utc_z(slot.scheduled_utc),
        "started_at_utc": _utc_z(started_at),
        "completed_at_utc": _utc_z(completed_at),
        "run_origin": "GITHUB_NATIVE_AI",
        **workflow,
        "RUN_STATUS": "FAILED",
        "FINALIZATION_STATUS": "FAILED",
        "failure_code": failure_code,
        "execution_authorized": False,
    }
    _write_json_exclusive(path, payload)
    if failure_code.startswith("CONFIGURATION_BLOCKED"):
        status = "CONFIGURATION_BLOCKED"
    elif failure_code == "OUTPUT_VALIDATION_FAILED":
        status = "OUTPUT_VALIDATION_FAILED"
    else:
        status = "MODEL_FAILED"
    return RunResult(status=status, failure_path=path)


def run_lane(
    root: Path,
    slot: Slot,
    env: Mapping[str, str],
    *,
    api_call: ApiCall = call_responses_api,
    now_fn: NowFn | None = None,
) -> RunResult:
    if terminal_artifact_exists(root, slot):
        return RunResult(status="DUPLICATE_SUPPRESSED")

    clock = now_fn or (lambda: datetime.now(timezone.utc))
    started_at = clock()
    try:
        workflow = _workflow_identity(env)
    except ConfigurationError:
        fallback_workflow = {
            "workflow_run_id": env.get("GITHUB_RUN_ID", "UNKNOWN"),
            "workflow_run_attempt": env.get("GITHUB_RUN_ATTEMPT", "UNKNOWN"),
            "workflow_sha": env.get("GITHUB_SHA", "UNKNOWN"),
            "repository": env.get("GITHUB_REPOSITORY", "UNKNOWN"),
            "branch": env.get("GITHUB_REF_NAME", "UNKNOWN"),
        }
        run_id = f"{slot.lane.name}-{slot.slot_id}-{fallback_workflow['workflow_run_id']}-{fallback_workflow['workflow_run_attempt']}"
        return _failure_result(
            root, slot, fallback_workflow, run_id, started_at, clock(),
            "CONFIGURATION_BLOCKED_GITHUB_METADATA_MISSING",
        )

    run_id = f"{slot.lane.name}-{slot.slot_id}-{workflow['workflow_run_id']}-{workflow['workflow_run_attempt']}"

    api_key = env.get("OPENAI_API_KEY", "")
    if not api_key:
        return _failure_result(
            root, slot, workflow, run_id, started_at, clock(),
            "CONFIGURATION_BLOCKED_OPENAI_API_KEY_MISSING",
        )

    try:
        control = load_control_plane(root)
        request = build_lane_request(root, control, slot)
    except ConfigurationError:
        return _failure_result(
            root, slot, workflow, run_id, started_at, clock(),
            "CONFIGURATION_BLOCKED_PROMPT_OR_CONTROL_PLANE",
        )

    fingerprint = request_fingerprint(request)
    try:
        response = api_call(request, api_key)
    except AuthenticationError:
        return _failure_result(
            root, slot, workflow, run_id, started_at, clock(),
            "MODEL_AUTHENTICATION_FAILED",
        )
    except TransportError:
        return _failure_result(
            root, slot, workflow, run_id, started_at, clock(),
            "MODEL_TRANSPORT_FAILED",
        )
    except ConfigurationError:
        return _failure_result(
            root, slot, workflow, run_id, started_at, clock(),
            "CONFIGURATION_BLOCKED_OPENAI_CLIENT",
        )
    except OutputValidationError:
        return _failure_result(
            root, slot, workflow, run_id, started_at, clock(),
            "OUTPUT_VALIDATION_FAILED",
        )

    try:
        validated = validate_lane_output(response.payload, slot.lane.name)
    except OutputValidationError:
        return _failure_result(
            root, slot, workflow, run_id, started_at, clock(),
            "OUTPUT_VALIDATION_FAILED",
        )

    completed_at = clock()
    output_path = _artifact_path(root, slot.lane.name, "outputs", slot.slot_id, run_id)
    receipt_path = _artifact_path(root, slot.lane.name, "runs", slot.slot_id, run_id)
    output_payload: dict[str, object] = {
        "schema_version": "omega-stack-github-native-output-v1",
        "lane": slot.lane.name,
        "RUN_ID": run_id,
        "SLOT_ID": slot.slot_id,
        "response_id": response.response_id,
        "payload": validated,
        "execution_authorized": False,
    }
    receipt: dict[str, object] = {
        "schema_version": "omega-stack-github-native-run-v1",
        "engine": slot.lane.name,
        "lane": slot.lane.name,
        "RUN_ID": run_id,
        "SLOT_ID": slot.slot_id,
        "slot_local": slot.scheduled_local.isoformat(),
        "slot_utc": _utc_z(slot.scheduled_utc),
        "started_at_utc": _utc_z(started_at),
        "completed_at_utc": _utc_z(completed_at),
        "run_origin": "GITHUB_NATIVE_AI",
        **workflow,
        "model": request.model,
        "reasoning_effort": request.reasoning_effort,
        "request_fingerprint": fingerprint,
        "response_id": response.response_id,
        "response_status": response.status,
        "output_validation_status": "VALID",
        "RUN_STATUS": "RUN_PERSISTED",
        "FINALIZATION_STATUS": "VERIFIED",
        "DATA_GAPS": list(validated["data_gaps"]),
        "CONFLICTS": list(validated["conflicts"]),
        "execution_authorized": False,
    }
    _write_json_exclusive(output_path, output_payload)
    _write_json_exclusive(receipt_path, receipt)
    return RunResult(
        status="RUN_PERSISTED",
        receipt_path=receipt_path,
        output_path=output_path,
    )
