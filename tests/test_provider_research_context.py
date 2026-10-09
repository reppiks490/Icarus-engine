import json
from pathlib import Path

from tools import provider_research_context as prc


def _write_latest(root: Path, provider: str, payload: dict) -> None:
    latest = root / "automation_intelligence" / "provider_collection_v1" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / f"{provider}.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_build_context_surfaces_substantive_provider_features_without_raw_payloads(tmp_path):
    _write_latest(
        tmp_path,
        "fred",
        {
            "run_id": "providers-1-fred",
            "completed_at_utc": "2026-10-09T00:00:00+00:00",
            "providers": {
                "fred": {
                    "status": "COLLECTED_PARTIAL",
                    "credential_present": True,
                    "requests": 20,
                    "collected_pages": 20,
                    "collected_rows": 2735,
                    "substantive_work_performed": True,
                    "research_features": [
                        {
                            "operation": "fred:get:/series/observations",
                            "features": {"value": {"samples": 9, "mean": 81.2}},
                        }
                    ],
                }
            },
            "catalog": {"operations": 31, "collected_operations": 23, "pending_pages": 1},
            "raw_payloads_public": False,
            "execution_authorized": False,
        },
    )
    _write_latest(
        tmp_path,
        "massive",
        {
            "run_id": "providers-1-massive",
            "completed_at_utc": "2026-10-09T00:00:00+00:00",
            "providers": {
                "massive": {
                    "status": "BLOCKED_MISSING_CREDENTIAL",
                    "credential_present": False,
                    "requests": 0,
                    "collected_pages": 0,
                    "collected_rows": 0,
                    "substantive_work_performed": False,
                    "research_features": [],
                }
            },
            "catalog": {"operations": 148, "collected_operations": 0, "pending_pages": 71},
            "raw_payloads_public": False,
            "execution_authorized": False,
        },
    )

    context = prc.build_context(tmp_path)

    assert context["schema_version"] == "icarus-provider-research-context-v1"
    assert context["authority"] == "RESEARCH_CONTEXT_ONLY"
    assert context["execution_authorized"] is False
    assert context["production_decision_authorized"] is False
    assert context["raw_payloads_included"] is False
    assert context["summary"]["providers_total"] == 2
    assert context["summary"]["providers_substantive"] == 1
    assert context["summary"]["providers_blocked"] == 1
    assert context["summary"]["collected_rows"] == 2735
    assert context["providers"]["fred"]["research_features"][0]["operation"] == "fred:get:/series/observations"
    assert context["providers"]["massive"]["status"] == "BLOCKED_MISSING_CREDENTIAL"
    encoded = json.dumps(context)
    assert "licensed_price" not in encoded
    assert "api_key" not in encoded.lower()


def test_build_context_accepts_owner_standby_receipt_without_inventing_collection(tmp_path):
    _write_latest(
        tmp_path,
        "intrinio",
        {
            "schema_version": "icarus-provider-owner-standby-v1",
            "run_id": "providers-2-intrinio",
            "provider": "intrinio",
            "preferred_repository": "reppiks490/Icarus",
            "credential_present": False,
            "status": "STANDBY_PREFERRED_OWNER",
            "execution_authorized": False,
        },
    )

    context = prc.build_context(tmp_path)
    row = context["providers"]["intrinio"]
    assert row["status"] == "STANDBY_PREFERRED_OWNER"
    assert row["substantive_work_performed"] is False
    assert row["collected_rows"] == 0
    assert row["research_features"] == []


def test_write_context_is_deterministic_for_same_latest_receipts(tmp_path):
    _write_latest(
        tmp_path,
        "fred",
        {
            "run_id": "providers-3-fred",
            "completed_at_utc": "2026-10-09T00:00:00+00:00",
            "providers": {"fred": {"status": "NO_READY_JOBS", "collected_rows": 0}},
            "catalog": {},
            "execution_authorized": False,
        },
    )
    first = prc.write_context(tmp_path)
    raw1 = first.read_bytes()
    second = prc.write_context(tmp_path)
    assert second.read_bytes() == raw1
