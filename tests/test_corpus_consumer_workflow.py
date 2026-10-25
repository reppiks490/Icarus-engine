"""Contracts for the credential-isolated, offline corpus-consumption workflow."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import textwrap
import ast

import pytest

from tools.corpus_receipt_sanitizer import sanitize_receipt


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/corpus-consumer-plane.yml"
ENGINE_SHA = "a" * 40
CONSUMER_SHA = "b" * 40
DATASET_ID = "d" * 64


def _text():
    return WORKFLOW.read_text(encoding="utf-8")


def _step(name):
    text = _text()
    start = text.index("      - name: " + name + "\n")
    end = text.find("\n      - ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def _receipt():
    dataset = {
        "dataset_id": DATASET_ID, "provider": "databento", "symbol": "NQ", "provider_root": "NQ",
        "identity_status": "MANIFEST_MATCH", "source_repo": "reppiks490/Icarus-engine",
        "source_commit": ENGINE_SHA, "source_sha256": "1" * 64, "bars_sha256": "2" * 64,
        "manifest_sha256": "3" * 64, "cache_name": "bars_primary", "filename": "databento_nq_5m.csv.gz",
        "retained_rows": 4, "first_ts": 1800000000, "last_ts": 1800000900,
        "available_at_ns": 1800000000000000000, "asof_ns": 1800000001000000000,
        "native_interval_seconds": 300,
    }
    read = {
        "consumer_id": "paper:cc1", "method": "candles", "dataset_id": DATASET_ID,
        "source_repo": "reppiks490/Icarus-engine", "source_commit": ENGINE_SHA,
        "symbol": "NQ", "requested_interval_seconds": 300, "row_count": 4,
        "first_ts": 1800000000, "last_ts": 1800000900,
        "available_at_ns": 1800000000000000000, "asof_ns": 1800000001000000000,
    }
    asset = {"symbol": "NQ", "dataset_id": DATASET_ID, "warm": True, "chart_bars": 4,
             "native_interval_seconds": 300, "mode": "CORPUS_WARMUP", "execution_authorized": False}
    return {
        "schema_version": "icarus-corpus-consumption-v1", "source_repo": "reppiks490/Icarus-engine",
        "source_commit": ENGINE_SHA, "asof_ns": 1800000001000000000,
        "datasets": [dataset], "blocked_datasets": [], "read_receipts": [read],
        "workspaces": [{"id": workspace, "configuration_sha256": str(index) * 64,
                        "assets": [dict(asset)], "unavailable_assets": [],
                        "paper_only": True, "execution_authorized": False}
                       for index, workspace in enumerate(("cc1", "cc2", "cc3", "cc4"), 1)],
        "corpus_used": True, "paper_warmup_used": True,
        "consumption_purposes": ["QUALITY_AND_COVERAGE", "PRIVATE_HISTORY_INPUT", "PAPER_CONFIGURATION_WARMUP"],
        "raw_payloads_included": False, "execution_authorized": False,
        "production_decision_authorized": False, "market_validation": False,
    }


def _sanitize(tmp_path, doc=None, **kwargs):
    source = tmp_path / "source.json"
    output = tmp_path / "safe.json"
    source.write_text(json.dumps(_receipt() if doc is None else doc), encoding="utf-8")
    values = {"engine_sha": ENGINE_SHA, "consumer_sha": CONSUMER_SHA,
              "cache_name": "bars_primary", "available_at_ns": 1800000000000000000,
              "consumer_exit_code": 0, **kwargs}
    safe = sanitize_receipt(source, output, **values)
    return safe, output


def test_manual_workflow_runs_only_on_main_with_a_pinned_consumer():
    text = _text()
    trigger = text.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.findall(r"^  (\w+):", trigger, re.M) == ["workflow_dispatch"]
    assert "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'" in text
    assert 'APPROVED_CONSUMER_REF: "20870219a12f065915d88aaaae58946770728e9e"' in text
    assert "consumer_ref" not in text
    assert "contents: read" in text and "contents: write" not in text
    assert "schedule:" not in text and "workflow_run:" not in text
    assert "options: [all, bars_primary, bars_secondary, bars_third]" in text
    assert "default: all" in text and "fail-fast: false" in text


def test_secrets_are_scoped_to_restore_and_consumer_is_network_isolated():
    text = _text()
    restore = _step("Restore existing encrypted bars")
    consumer = _step("Consume private corpus with isolated paper profiles")
    assert text.count("secrets.") == restore.count("secrets.")
    assert "secrets.DATABENTO_API_KEY || secrets.DATABENTO_KEY" in restore
    assert "secrets.ICARUS_DATA_ARCHIVE_KEY" in restore
    assert '> "$PROOF_ROOT/restore.log" 2>&1' in restore
    assert "secrets." not in consumer
    assert "--network=none" in consumer and "--read-only" in consumer
    assert "--cap-drop=ALL" in consumer and "--security-opt=no-new-privileges" in consumer
    assert "--mount \"type=bind,src=$PROOF_ROOT/restored,dst=/restored,readonly\"" in consumer
    assert "--env ICARUS_FEED=file" in consumer
    assert "socket.socket.connect" not in consumer
    assert "python -m tools.provider_corpus_intake" in consumer
    assert "tools/corpus_receipt_sanitizer.py" in _step("Validate safe consumption receipt")
    assert "--include-requested-futures" in consumer
    assert "Record conservative archive availability" in text
    assert "git show -s --format=%ct" not in text
    assert "consumer_status" in _step("Summarize consumption result")


def test_artifact_is_host_sanitized_metadata_and_private_files_are_removed():
    upload = _step("Upload metadata receipt only")
    cleanup = _step("Remove private restored data and logs")
    assert "${{ env.PROOF_ROOT }}/safe-receipt.json" in upload
    assert "${{ env.PROOF_ROOT }}/output/receipt.json" not in upload
    assert "if-no-files-found: error" in upload and "include-hidden-files: false" in upload
    assert "retention-days: 7" in upload
    assert "if: always()" in cleanup and 'rm -rf -- "$PROOF_ROOT"' in cleanup


def test_consumer_output_directories_are_private_to_the_runner():
    consumer = _step("Consume private corpus with isolated paper profiles")
    assert 'mkdir -m 700 "$PROOF_ROOT/runtime" "$PROOF_ROOT/output"' in consumer
    assert "mkdir -m 777" not in consumer


def test_sanitizer_publishes_only_bounded_allowlisted_metadata(tmp_path):
    doc = _receipt()
    doc["private_bars"] = [[1, 2, 3, 4, 5]]
    doc["workspaces"][0]["inputs"] = {"secret_marker": "must not leave"}
    doc["datasets"][0]["raw_ohlcv"] = [[1, 2, 3, 4, 5]]
    doc["read_receipts"][0]["provider_response"] = "must not leave"
    safe, output = _sanitize(tmp_path, doc)
    encoded = output.read_text(encoding="utf-8")
    assert "private_bars" not in safe and "raw_ohlcv" not in encoded
    assert "must not leave" not in encoded and "inputs" not in safe["workspaces"][0]
    assert safe["workflow_provenance"] == {
        "engine_commit": ENGINE_SHA, "consumer_commit": CONSUMER_SHA, "network_disabled": True,
        "acquisition_performed": False, "consumer_exit_code": 0, "consumer_status": "COMPLETE",
        "paper_warmup_status": "WARMED",
        "raw_data_artifacted": False, "execution_authorized": False,
    }
    assert safe["available_at_ns"] == 1800000000000000000
    assert safe["consumer_status"] == "COMPLETE"
    assert safe["paper_warmup_status"] == "WARMED"
    assert safe["workflow_provenance"]["paper_warmup_status"] == "WARMED"
    assert output.stat().st_mode & 0o777 == 0o600
    assert set(safe["workspaces"][0]) == {
        "id", "configuration_sha256", "assets", "unavailable_asset_symbols", "paper_only", "execution_authorized"}


@pytest.mark.parametrize("change", [
    lambda doc: doc.update(source_commit="c" * 40),
    lambda doc: doc.update(corpus_used=False),
    lambda doc: doc.update(raw_payloads_included=True),
    lambda doc: doc.update(execution_authorized=True),
    lambda doc: doc.update(paper_warmup_used=False),
    lambda doc: doc["read_receipts"].clear(),
    lambda doc: doc["workspaces"].pop(),
    lambda doc: doc["datasets"][0].update(cache_name="bars_third"),
    lambda doc: doc["workspaces"][0].update(execution_authorized=True),
    lambda doc: doc["workspaces"][0]["assets"][0].update(mode="LIVE"),
    lambda doc: doc["read_receipts"][0].update(row_count=True),
    lambda doc: doc["datasets"][0].update(available_at_ns=1800000000000000100),
    lambda doc: doc["read_receipts"][0].update(asof_ns=1800000001000000100),
    lambda doc: doc.update(consumption_purposes=["arbitrary payload"]),
])
def test_sanitizer_rejects_false_scope_unproven_and_wrong_provenance(tmp_path, change):
    doc = _receipt()
    change(doc)
    source = tmp_path / "bad.json"
    output = tmp_path / "safe.json"
    source.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        sanitize_receipt(source, output, engine_sha=ENGINE_SHA, consumer_sha=CONSUMER_SHA,
                         cache_name="bars_primary", available_at_ns=1800000000000000000,
                         consumer_exit_code=0)
    assert not output.exists()


def test_sanitizer_refuses_symlinked_receipt_and_failed_consumer(tmp_path):
    target = tmp_path / "outside.json"
    target.write_text(json.dumps(_receipt()), encoding="utf-8")
    source = tmp_path / "source.json"
    source.symlink_to(target)
    with pytest.raises(OSError):
        sanitize_receipt(source, tmp_path / "safe.json", engine_sha=ENGINE_SHA,
                         consumer_sha=CONSUMER_SHA, cache_name="bars_primary",
                         available_at_ns=1800000000000000000, consumer_exit_code=0)
    source.unlink()
    source.write_text(json.dumps(_receipt()), encoding="utf-8")
    with pytest.raises(ValueError):
        sanitize_receipt(source, tmp_path / "safe.json", engine_sha=ENGINE_SHA,
                         consumer_sha=CONSUMER_SHA, cache_name="bars_primary",
                         available_at_ns=1800000000000000000, consumer_exit_code=2)


def test_partial_consumer_exit_is_explicit_and_requires_blocked_dataset(tmp_path):
    doc = _receipt()
    doc["blocked_datasets"] = [{"input_sha256": "e" * 64, "reason": "DATASET_VALIDATION_FAILED"}]
    safe, _ = _sanitize(tmp_path, doc, consumer_exit_code=1)
    assert safe["consumer_exit_code"] == 1
    assert safe["consumer_status"] == "PARTIAL"
    assert safe["workflow_provenance"]["consumer_status"] == "PARTIAL"

    cold = _receipt()
    cold["paper_warmup_used"] = False
    cold["consumption_purposes"].remove("PAPER_CONFIGURATION_WARMUP")
    for workspace in cold["workspaces"]:
        workspace["assets"][0].update(warm=False, chart_bars=0)
    cold_dir = tmp_path / "cold"
    cold_dir.mkdir()
    cold_safe, _ = _sanitize(cold_dir, cold)
    assert cold_safe["consumer_status"] == "COMPLETE"
    assert cold_safe["paper_warmup_status"] == "NOT_WARMED"

    with pytest.raises(ValueError):
        sanitize_receipt(tmp_path / "source.json", tmp_path / "inconsistent.json",
                         engine_sha=ENGINE_SHA, consumer_sha=CONSUMER_SHA,
                         cache_name="bars_primary", available_at_ns=1800000000000000000,
                         consumer_exit_code=0)

    unblocked = tmp_path / "unblocked.json"
    unblocked.write_text(json.dumps(_receipt()), encoding="utf-8")
    with pytest.raises(ValueError):
        sanitize_receipt(unblocked, tmp_path / "no-blocks.json",
                         engine_sha=ENGINE_SHA, consumer_sha=CONSUMER_SHA,
                         cache_name="bars_primary", available_at_ns=1800000000000000000,
                         consumer_exit_code=1)

    with pytest.raises(ValueError):
        sanitize_receipt(tmp_path / "source.json", tmp_path / "boolean-exit.json",
                         engine_sha=ENGINE_SHA, consumer_sha=CONSUMER_SHA,
                         cache_name="bars_primary", available_at_ns=1800000000000000000,
                         consumer_exit_code=True)


def test_shell_steps_are_syntactically_valid():
    for name in ("Validate immutable inputs", "Build isolated offline consumer image",
                 "Verify immutable source revisions", "Restore existing encrypted bars",
                 "Record conservative archive availability",
                 "Consume private corpus with isolated paper profiles", "Validate safe consumption receipt",
                 "Summarize consumption result",
                 "Remove private restored data and logs"):
        step = _step(name)
        script = step.split("        run: |\n", 1)[1]
        lines = script.splitlines()
        shell = "\n".join(line[10:] if line.startswith("          ") else line for line in lines)
        completed = subprocess.run(["bash", "-n"], input=shell, text=True, capture_output=True)
        assert completed.returncode == 0, f"{name}: {completed.stderr}"
    for name in ("Validate immutable inputs", "Verify immutable source revisions",
                 "Record conservative archive availability", "Summarize consumption result"):
        run = _step(name).split("        run: |\n", 1)[1]
        script = textwrap.dedent(run).split("<<'PY'", 1)[1].rsplit("\nPY", 1)[0]
        ast.parse(script)
