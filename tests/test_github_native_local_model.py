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
    normalize_terminal_text,
    safe_generation_preview,
    wrap_terminal_command,
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
    assert "--jinja" in cmd
    assert "--reasoning" in cmd
    assert cmd[cmd.index("--reasoning") + 1] == "off"
    assert "--reasoning-budget" not in cmd
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
    assert cmd[cmd.index("-n") + 1] == "768"


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


def test_run_local_model_reads_cli_output_file_when_stdio_is_empty(tmp_path: Path) -> None:
    binary = tmp_path / "llama-cli"
    model = tmp_path / "model.gguf"
    binary.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    output = json.dumps(
        {
            "lane": "aion",
            "summary": "Local file-channel canary succeeded.",
            "net_new_delta": "CANARY_OK",
            "data_gaps": [],
            "conflicts": [],
            "execution_authorized": False,
        }
    )

    def executor(cmd, timeout):
        assert "-o" in cmd
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(output, encoding="utf-8")
        return 0, "", ""

    response = run_local_model(
        _request(),
        binary=binary,
        model=model,
        executor=executor,
        timeout_seconds=5,
    )

    assert response.status == "completed"
    assert response.payload["net_new_delta"] == "CANARY_OK"


def test_safe_generation_preview_strips_thinking() -> None:
    preview = safe_generation_preview(
        "<think>private local reasoning that must not leak</think> "
        "prefix {not-json yet}"
    )
    assert "private local reasoning" not in preview
    assert "prefix" in preview


def test_unstructured_error_contains_only_sanitized_preview(tmp_path: Path) -> None:
    binary = tmp_path / "llama-cli"
    model = tmp_path / "model.gguf"
    binary.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")

    def executor(cmd, timeout):
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(
            "<think>secret reasoning</think> definitely-not-json",
            encoding="utf-8",
        )
        return 0, "", ""

    with pytest.raises(TransportError) as exc:
        run_local_model(
            _request(),
            binary=binary,
            model=model,
            executor=executor,
            timeout_seconds=5,
        )
    message = str(exc.value)
    assert "secret reasoning" not in message
    assert "definitely-not-json" in message
    assert "generated_len=" in message


def test_terminal_wrapper_allocates_script_pty() -> None:
    original = ["llama-cli", "-p", "hello world", "--reasoning", "off"]
    wrapped = wrap_terminal_command(original, script_binary="/usr/bin/script")
    assert wrapped[:4] == ["/usr/bin/script", "-q", "-e", "-c"]
    assert wrapped[-1] == "/dev/null"
    assert "llama-cli" in wrapped[4]
    assert "'hello world'" in wrapped[4]
    assert "--reasoning off" in wrapped[4]


def test_terminal_wrapper_falls_back_when_script_is_unavailable() -> None:
    original = ["llama-cli", "-p", "hello"]
    assert wrap_terminal_command(original, script_binary="") == original


def test_terminal_normalization_recovers_ansi_interleaved_json() -> None:
    noisy = (
        "\x1b[32m{\x1b[0m"
        "\"lane\":\"aion\","
        "\"summary\":\"ok\","
        "\"net_new_delta\":\"CANARY_OK\","
        "\"data_gaps\":[],"
        "\"conflicts\":[],"
        "\"execution_authorized\":false"
        "\x1b[32m}\x1b[0m\r\n"
    )
    normalized = normalize_terminal_text(noisy)
    payload = extract_json_object(normalized)
    assert payload["lane"] == "aion"
    assert payload["execution_authorized"] is False


def test_run_local_model_parses_pty_ansi_stdout(tmp_path: Path) -> None:
    binary = tmp_path / "llama-cli"
    model = tmp_path / "model.gguf"
    binary.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    noisy = (
        "prompt echo\r\n"
        "\x1b[36m{\x1b[0m"
        "\"lane\":\"aion\","
        "\"summary\":\"pty ok\","
        "\"net_new_delta\":\"CANARY_OK\","
        "\"data_gaps\":[],"
        "\"conflicts\":[],"
        "\"execution_authorized\":false"
        "\x1b[36m}\x1b[0m\r\n"
    )

    def executor(cmd, timeout):
        return 0, noisy, ""

    response = run_local_model(
        _request(),
        binary=binary,
        model=model,
        executor=executor,
        timeout_seconds=5,
    )
    assert response.status == "completed"
    assert response.payload["net_new_delta"] == "CANARY_OK"


def test_terminal_wrapper_bypasses_pty_for_llama_completion() -> None:
    original = ["llama-completion", "-p", "hello", "-st"]
    assert wrap_terminal_command(original, script_binary="/usr/bin/script") == original


def test_nonzero_runtime_error_uses_sanitized_stderr(tmp_path: Path) -> None:
    binary = tmp_path / "llama-completion"
    model = tmp_path / "model.gguf"
    binary.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")

    def executor(cmd, timeout):
        return 1, "", "<think>private reasoning</think> error: invalid argument --bad-flag"

    with pytest.raises(TransportError) as exc:
        run_local_model(
            _request(),
            binary=binary,
            model=model,
            executor=executor,
            timeout_seconds=5,
        )
    message = str(exc.value)
    assert "private reasoning" not in message
    assert "invalid argument --bad-flag" in message


def test_completion_command_excludes_cli_only_flags(tmp_path: Path) -> None:
    binary = tmp_path / "llama-completion"
    model = tmp_path / "model.gguf"
    output = tmp_path / "generation.txt"
    cmd = build_local_model_command(
        binary,
        model,
        _request(),
        output_file=output,
    )
    assert "-st" in cmd
    assert "--jinja" in cmd
    assert "--reasoning" in cmd
    assert "--json-schema" in cmd
    assert "--simple-io" not in cmd
    assert "--no-show-timings" not in cmd
    assert "-o" not in cmd


def test_grammar_pins_requested_lane_and_false_execution_authority(tmp_path):
    command=build_local_model_command(tmp_path/'llama-completion',tmp_path/'model.gguf',_request())
    schema=json.loads(command[command.index('--json-schema')+1])
    assert schema['properties']['lane'].get('enum') == ['aion']
    assert schema['properties']['execution_authorized'].get('enum') == [False]
