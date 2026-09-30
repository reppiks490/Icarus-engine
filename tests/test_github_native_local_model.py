from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.github_native_ai_openai import ModelRequest, TransportError
from tools.github_native_local_model import (
    LLAMA_CPP_SHA256,
    LLAMA_CPP_URL,
    LOCAL_MODEL_ID,
    MODEL_SHA256,
    MODEL_URL,
    build_local_model_command,
    extract_json_object,
    run_local_model,
)


def _request() -> ModelRequest:
    return ModelRequest(
        lane="aion",
        model=LOCAL_MODEL_ID,
        reasoning_effort="local",
        instructions="Return only a valid structured status object.",
        input_text="Report the local model canary status.",
    )


def test_pins_runtime_and_model_immutably() -> None:
    assert LLAMA_CPP_URL == (
        "https://github.com/ggml-org/llama.cpp/releases/download/"
        "b10978/llama-b10978-bin-ubuntu-x64.tar.gz"
    )
    assert LLAMA_CPP_SHA256 == "98020bb5a2a9e0284110e5c110158e18dca984a547d5afde1631fef0f03dd826"
    assert MODEL_URL == (
        "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/"
        "90862c4b9d2787eaed51d12237eafdfe7c5f6077/Qwen3-1.7B-Q8_0.gguf"
    )
    assert MODEL_SHA256 == "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a"
    assert LOCAL_MODEL_ID == "Qwen/Qwen3-1.7B-GGUF@90862c4:Q8_0"


def test_build_command_is_single_turn_cpu_and_schema_constrained(tmp_path: Path) -> None:
    binary = tmp_path / "llama-cli"
    model = tmp_path / "model.gguf"
    cmd = build_local_model_command(binary, model, _request())

    assert cmd[0] == str(binary)
    assert cmd[cmd.index("-m") + 1] == str(model)
    assert "-st" in cmd
    assert "--simple-io" in cmd
    assert "--no-display-prompt" in cmd
    assert "--no-show-timings" in cmd
    assert "--reasoning-budget" in cmd
    assert cmd[cmd.index("--reasoning-budget") + 1] == "0"
    assert "--json-schema" in cmd
    schema = json.loads(cmd[cmd.index("--json-schema") + 1])
    assert schema["type"] == "object"
    assert set(schema["required"]) == {
        "lane",
        "summary",
        "net_new_delta",
        "data_gaps",
        "conflicts",
        "execution_authorized",
    }
    assert cmd[cmd.index("-t") + 1] == "4"
    assert cmd[cmd.index("-c") + 1] == "4096"
    assert cmd[cmd.index("-n") + 1] == "384"


def test_extract_json_object_ignores_thinking_and_noise() -> None:
    text = """loader noise
<think>private local reasoning</think>
{"lane":"aion","summary":"ok","net_new_delta":"CANARY_OK","data_gaps":[],"conflicts":[],"execution_authorized":false}
timing noise
"""
    payload = extract_json_object(text)
    assert payload["lane"] == "aion"
    assert payload["execution_authorized"] is False


def test_run_local_model_returns_validated_model_response(tmp_path: Path) -> None:
    binary = tmp_path / "llama-cli"
    model = tmp_path / "model.gguf"
    binary.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    output = json.dumps(
        {
            "lane": "aion",
            "summary": "Local canary succeeded.",
            "net_new_delta": "CANARY_OK",
            "data_gaps": [],
            "conflicts": [],
            "execution_authorized": False,
        }
    )

    def executor(cmd, timeout):
        return 0, output, ""

    response = run_local_model(
        _request(),
        binary=binary,
        model=model,
        executor=executor,
        timeout_seconds=5,
    )

    assert response.status == "completed"
    assert response.payload["lane"] == "aion"
    assert response.payload["net_new_delta"] == "CANARY_OK"
    assert response.response_id.startswith("local-")


def test_run_local_model_rejects_nonzero_runtime_exit(tmp_path: Path) -> None:
    binary = tmp_path / "llama-cli"
    model = tmp_path / "model.gguf"
    binary.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")

    def executor(cmd, timeout):
        return 2, "", "runtime failed"

    with pytest.raises(TransportError, match="local model runtime failed"):
        run_local_model(
            _request(),
            binary=binary,
            model=model,
            executor=executor,
            timeout_seconds=5,
        )


def test_run_local_model_rejects_unstructured_output(tmp_path: Path) -> None:
    binary = tmp_path / "llama-cli"
    model = tmp_path / "model.gguf"
    binary.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")

    def executor(cmd, timeout):
        return 0, "not json", ""

    with pytest.raises(TransportError, match="structured JSON"):
        run_local_model(
            _request(),
            binary=binary,
            model=model,
            executor=executor,
            timeout_seconds=5,
        )
