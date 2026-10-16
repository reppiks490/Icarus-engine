from __future__ import annotations

import json
from pathlib import Path

import pytest


CONTRACT = Path("config/credential_contract.json")
HANDOFF = Path("docs/agent-handoffs/GITHUB_NATIVE_CREDENTIALS.md")
WORKFLOW = Path(".github/workflows/github-native-credential-health.yml")


def test_contract_exists_and_uses_unique_canonical_names() -> None:
    data = json.loads(CONTRACT.read_text())
    credentials = data["credentials"]
    assert credentials
    canonical = [item["canonical"] for item in credentials]
    assert len(canonical) == len(set(canonical))
    assert "MASSIVE_API_KEY" in canonical
    assert "TWELVEDATA_API_KEY" in canonical
    assert "INTRINIO_API_KEY" in canonical
    for item in credentials:
        assert item["canonical"]
        assert item["aliases"]
        assert item["canonical"] in item["aliases"]
        assert len(item["aliases"]) == len(set(item["aliases"]))


def test_canonical_precedence_alias_fallback_and_empty_values() -> None:
    from icarus_engine.security.credentials import credential_status, resolve_credential

    env = {"MASSIVE_API_KEY": "canonical", "MASSIVE_KEY": "legacy"}
    assert resolve_credential("MASSIVE_API_KEY", env) == "canonical"
    status = credential_status("MASSIVE_API_KEY", env)
    assert status.present is True
    assert status.matched_alias == "MASSIVE_API_KEY"

    env = {"MASSIVE_API_KEY": "", "MASSIVE_KEY": "legacy"}
    assert resolve_credential("MASSIVE_API_KEY", env) == "legacy"
    status = credential_status("MASSIVE_API_KEY", env)
    assert status.matched_alias == "MASSIVE_KEY"


def test_unknown_credential_fails_without_environment_dump() -> None:
    from icarus_engine.security.credentials import credential_status, resolve_credential

    env = {"TOP_SECRET_VALUE": "do-not-leak"}
    with pytest.raises(KeyError, match="UNKNOWN_CREDENTIAL") as exc:
        resolve_credential("UNKNOWN_CREDENTIAL", env)
    assert "do-not-leak" not in str(exc.value)
    with pytest.raises(KeyError, match="UNKNOWN_CREDENTIAL") as exc:
        credential_status("UNKNOWN_CREDENTIAL", env)
    assert "do-not-leak" not in str(exc.value)


def test_status_repr_and_dict_never_include_secret_value() -> None:
    from icarus_engine.security.credentials import credential_status

    secret = "super-sensitive-value"
    status = credential_status("MASSIVE_API_KEY", {"MASSIVE_KEY": secret})
    assert secret not in repr(status)
    payload = status.as_dict()
    assert secret not in json.dumps(payload)
    assert payload == {
        "canonical_name": "MASSIVE_API_KEY",
        "present": True,
        "matched_alias": "MASSIVE_KEY",
    }


def test_health_workflow_is_explicit_and_never_enumerates_secrets() -> None:
    data = json.loads(CONTRACT.read_text())
    text = WORKFLOW.read_text()
    assert "toJSON(secrets)" not in text
    assert "credential_health.py" in text
    for item in data["credentials"]:
        for alias in item["aliases"]:
            assert f"secrets.{alias}" in text


def test_handoff_tells_agents_to_use_github_native_contract_without_plaintext() -> None:
    text = HANDOFF.read_text().lower()
    assert "config/credential_contract.json" in text
    assert "github-native-credential-health.yml" in text
    assert "do not" in text and "plaintext" in text
    assert "start using" in text
    assert "github actions" in text
