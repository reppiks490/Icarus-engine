from pathlib import Path


WORKFLOW = Path(".github/workflows/github-native-local-model-canary.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_local_model_canary_is_manual_or_change_triggered_not_scheduled() -> None:
    text = _text()
    assert "workflow_dispatch:" in text
    assert "push:" in text
    assert "schedule:" not in text
    assert "tools/github_native_local_model.py" in text
    assert "tools/github_native_local_model_canary.py" in text


def test_canary_uses_free_standard_runner_and_cache() -> None:
    text = _text()
    assert "runs-on: ubuntu-latest" in text
    assert "uses: actions/cache@v4" in text
    assert "~/.cache/icarus-local-model" in text
    assert "Qwen3-1.7B" in text


def test_canary_verifies_pinned_runtime_and_model_checksums() -> None:
    text = _text()
    assert "b10978/llama-b10978-bin-ubuntu-x64.tar.gz" in text
    assert "98020bb5a2a9e0284110e5c110158e18dca984a547d5afde1631fef0f03dd826" in text
    assert "90862c4b9d2787eaed51d12237eafdfe7c5f6077/Qwen3-1.7B-Q8_0.gguf" in text
    assert "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a" in text
    assert "sha256sum -c -" in text


def test_canary_has_no_paid_api_secret_or_oidc_dependency() -> None:
    text = _text()
    assert "secrets." not in text
    assert "OPENAI_API_KEY" not in text
    assert "id-token: write" not in text


def test_canary_persists_only_local_canary_namespace_without_force_push() -> None:
    text = _text()
    assert "git add automation_intelligence/omega_stack_native_v3/local_model_canary" in text
    assert "^automation_intelligence/omega_stack_native_v3/local_model_canary/" in text
    assert "git push origin HEAD:main" in text
    assert "git push --force" not in text
