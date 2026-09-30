from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools.github_native_ai_dispatcher import NAMESPACE_ROOT, load_control_plane, resolve_due_slot
from tools.github_native_ai_openai import ConfigurationError, ModelResponse, TransportError
from tools.github_native_ai_runner import (
    build_lane_request,
    request_fingerprint,
    run_lane,
)


UTC = timezone.utc


def _seed_root(tmp_path: Path, lane: str = "aion") -> Path:
    source = Path(NAMESPACE_ROOT) / "control_plane.json"
    target = tmp_path / NAMESPACE_ROOT / "control_plane.json"
    target.parent.mkdir(parents=True)
    shutil.copy2(source, target)

    shared = tmp_path / NAMESPACE_ROOT / "lanes" / "shared" / "system.md"
    task = tmp_path / NAMESPACE_ROOT / "lanes" / lane / "prompts" / "task.md"
    shared.parent.mkdir(parents=True)
    task.parent.mkdir(parents=True)
    shared.write_text("System contract. execution_authorized=false.\n", encoding="utf-8")
    task.write_text("Produce a concise lane status delta.\n", encoding="utf-8")
    return tmp_path


def _slot(root: Path, lane_time: str = "2026-09-30T13:36:00+00:00"):
    control = load_control_plane(root)
    slot = resolve_due_slot(datetime.fromisoformat(lane_time), control, tolerance_minutes=4)
    assert slot is not None
    return slot


def _env(api_key: str = "sk-test") -> dict[str, str]:
    return {
        "OPENAI_API_KEY": api_key,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "abc123",
        "GITHUB_REPOSITORY": "reppiks490/Icarus-engine",
        "GITHUB_REF_NAME": "main",
    }


def _payload(lane: str = "aion") -> dict[str, object]:
    return {
        "lane": lane,
        "summary": "No material change.",
        "net_new_delta": "NONE",
        "data_gaps": [],
        "conflicts": [],
        "execution_authorized": False,
    }


def _success_call(request, api_key):
    return ModelResponse(response_id="resp_ok", status="completed", payload=_payload(request.lane))


def test_request_fingerprint_is_deterministic_for_same_slot_and_prompts(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    control = load_control_plane(root)
    slot = _slot(root)

    first = build_lane_request(root, control, slot)
    second = build_lane_request(root, control, slot)

    assert request_fingerprint(first) == request_fingerprint(second)
    assert len(request_fingerprint(first)) == 64


def test_success_writes_immutable_output_and_receipt_with_provenance(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    slot = _slot(root)
    fixed_now = datetime(2026, 9, 30, 13, 36, 30, tzinfo=UTC)

    result = run_lane(root, slot, _env(), api_call=_success_call, now_fn=lambda: fixed_now)

    assert result.status == "RUN_PERSISTED"
    assert result.receipt_path is not None and result.receipt_path.exists()
    assert result.output_path is not None and result.output_path.exists()
    assert result.failure_path is None

    receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    output = json.loads(result.output_path.read_text(encoding="utf-8"))

    assert receipt["lane"] == "aion"
    assert receipt["SLOT_ID"] == "20260930T133600Z"
    assert receipt["run_origin"] == "GITHUB_NATIVE_AI"
    assert receipt["workflow_run_id"] == "12345"
    assert receipt["workflow_run_attempt"] == "1"
    assert receipt["workflow_sha"] == "abc123"
    assert receipt["repository"] == "reppiks490/Icarus-engine"
    assert receipt["branch"] == "main"
    assert receipt["response_id"] == "resp_ok"
    assert receipt["response_status"] == "completed"
    assert receipt["output_validation_status"] == "VALID"
    assert receipt["RUN_STATUS"] == "RUN_PERSISTED"
    assert receipt["FINALIZATION_STATUS"] == "VERIFIED"
    assert receipt["execution_authorized"] is False
    assert len(receipt["request_fingerprint"]) == 64
    assert output["payload"] == _payload()


def test_missing_key_writes_failure_and_never_calls_api(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    slot = _slot(root)
    called = False

    def api_call(request, api_key):
        nonlocal called
        called = True
        raise AssertionError("must not call API")

    result = run_lane(root, slot, _env(api_key=""), api_call=api_call)

    assert result.status == "CONFIGURATION_BLOCKED"
    assert called is False
    assert result.failure_path is not None
    failure = json.loads(result.failure_path.read_text(encoding="utf-8"))
    assert failure["failure_code"] == "CONFIGURATION_BLOCKED_OPENAI_AUTH_MISSING"
    assert failure["execution_authorized"] is False
    assert result.receipt_path is None
    assert result.output_path is None


def test_transport_failure_is_sanitized_and_terminal(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    slot = _slot(root)

    def api_call(request, api_key):
        raise TransportError("bad network sk-secret-must-not-appear")

    result = run_lane(root, slot, _env(api_key="sk-secret-must-not-appear"), api_call=api_call)

    assert result.status == "MODEL_FAILED"
    assert result.failure_path is not None
    text = result.failure_path.read_text(encoding="utf-8")
    assert "sk-secret-must-not-appear" not in text
    failure = json.loads(text)
    assert failure["failure_code"] == "MODEL_TRANSPORT_FAILED"


def test_invalid_model_payload_writes_validation_failure(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    slot = _slot(root)

    def api_call(request, api_key):
        return ModelResponse(
            response_id="resp_bad",
            status="completed",
            payload={**_payload("wrong"), "execution_authorized": False},
        )

    result = run_lane(root, slot, _env(), api_call=api_call)

    assert result.status == "OUTPUT_VALIDATION_FAILED"
    assert result.failure_path is not None
    assert result.receipt_path is None


def test_existing_terminal_artifact_suppresses_duplicate_without_api_call(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    slot = _slot(root)
    existing_dir = root / NAMESPACE_ROOT / "lanes" / "aion" / "failures" / slot.slot_id
    existing_dir.mkdir(parents=True)
    existing = existing_dir / "prior.json"
    existing.write_text('{"status":"prior"}\n', encoding="utf-8")
    before = existing.read_text(encoding="utf-8")
    called = False

    def api_call(request, api_key):
        nonlocal called
        called = True
        return ModelResponse(response_id="unexpected", status="completed", payload=_payload())

    result = run_lane(root, slot, _env(), api_call=api_call)

    assert result.status == "DUPLICATE_SUPPRESSED"
    assert called is False
    assert existing.read_text(encoding="utf-8") == before


def test_artifacts_never_escape_lane_namespace(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, lane="flow")
    slot = _slot(root, "2026-09-30T13:24:00+00:00")

    result = run_lane(
        root,
        slot,
        _env(),
        api_call=lambda request, api_key: ModelResponse(
            response_id="resp_flow",
            status="completed",
            payload=_payload("flow"),
        ),
    )

    assert result.status == "RUN_PERSISTED"
    for path in (result.receipt_path, result.output_path):
        assert path is not None
        relative = path.relative_to(root).as_posix()
        assert relative.startswith(f"{NAMESPACE_ROOT}/lanes/flow/")
        assert ".." not in relative


def test_wif_token_resolver_can_supply_auth_without_api_key(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    slot = _slot(root)
    seen = {}

    def resolver(env):
        seen["env"] = dict(env)
        return "short-lived-wif-token"

    def api_call(request, token):
        assert token == "short-lived-wif-token"
        return ModelResponse(response_id="resp_wif", status="completed", payload=_payload(request.lane))

    result = run_lane(
        root,
        slot,
        _env(api_key=""),
        api_call=api_call,
        token_resolver=resolver,
    )

    assert result.status == "RUN_PERSISTED"
    assert seen["env"]["GITHUB_RUN_ID"] == "12345"
