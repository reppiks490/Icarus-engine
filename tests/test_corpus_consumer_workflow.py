"""Offline contracts for the secret-isolated, read-only corpus proof runner."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import textwrap

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/corpus-consumer-plane.yml"


def _text():
    return WORKFLOW.read_text(encoding="utf-8")


def _step(name):
    text = _text()
    start = text.index("      - name: " + name + "\n")
    end = text.find("\n      - ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def _script(name):
    block = _step(name).split("        run: |\n", 1)[1]
    return textwrap.dedent(block)


def _python(name):
    script = _script(name)
    return script.split("<<'PY'", 1)[1].split("\n", 1)[1].rsplit("\nPY", 1)[0]


def _env(tmp_path, ref="b" * 40):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return {**os.environ, "RUNNER_TEMP": str(tmp_path), "GITHUB_ENV": str(tmp_path / "env"),
            "GITHUB_WORKSPACE": str(tmp_path), "PROOF_ROOT": str(root),
            "ENGINE_SHA": "a" * 40, "CONSUMER_SHA": ref, "CACHE_NAME": "bars_primary",
            "AVAILABLE_AT_NS": "1800000000000000000", "CONSUMER_EXIT_CODE": "0"}


def test_manual_or_narrow_reviewed_branch_bootstrap_only_read_only_and_bounded():
    text = _text()
    trigger = text.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.findall(r"^  (\w+):", trigger, re.M) == ["push", "workflow_dispatch"]
    push = trigger.split("  workflow_dispatch:", 1)[0]
    assert 'branches: ["codex/corpus-native-workflow-20261018"]' in push
    assert 'paths: [".github/workflows/corpus-consumer-plane.yml"]' in push
    assert "contents: read" in text and "contents: write" not in text
    assert "timeout-minutes: 20" in text
    assert "schedule:" not in text and "workflow_run:" not in text
    assert "git push" not in text and "git commit" not in text


def test_exact_ref_validation_precedes_both_checkouts():
    text = _text()
    assert text.index("Validate immutable inputs") < text.index("actions/checkout@")
    assert "ref: ${{ github.sha }}" in text
    assert "ref: ${{ env.CONSUMER_SHA }}" in text
    assert "inputs.consumer_ref || env.DEFAULT_CONSUMER_REF" in text
    assert "repository: reppiks490/Icarus" in text
    assert text.count("persist-credentials: false") == 2


def test_each_retained_account_cache_gets_isolated_proof_and_artifact():
    text = _text()
    assert "options: [all, bars_primary, bars_secondary, bars_third]" in text
    assert "default: all" in text
    assert "fail-fast: false" in text
    assert "'[\"bars_primary\",\"bars_secondary\",\"bars_third\"]'" in text
    assert "CACHE_NAME: ${{ matrix.cache_name }}" in text
    assert "name: corpus-consumption-${{ matrix.cache_name }}-" in text


@pytest.mark.parametrize("ref", ["main", "b" * 39, "B" * 40, "b" * 40 + "\n", "$(touch unsafe)"])
def test_input_validation_refuses_mutable_or_interpretable_refs(tmp_path, monkeypatch, ref):
    env = _env(tmp_path, ref)
    monkeypatch.setattr(os, "environ", env)
    with pytest.raises(SystemExit):
        exec(compile(_python("Validate immutable inputs"), "validate", "exec"), {})
    assert not (tmp_path / "env").exists()
    assert not (tmp_path / "unsafe").exists()


def test_validation_creates_private_storage_without_echoing_inputs(tmp_path, monkeypatch, capsys):
    env = _env(tmp_path)
    monkeypatch.setattr(os, "environ", env)
    exec(compile(_python("Validate immutable inputs"), "validate", "exec"), {})
    assignments = dict(row.split("=", 1) for row in (tmp_path / "env").read_text().splitlines())
    assert Path(assignments["PROOF_ROOT"]).stat().st_mode & 0o777 == 0o700
    assert assignments["CACHE_NAME"] == "bars_primary"
    assert capsys.readouterr().out == ""


def test_secrets_exist_only_in_vault_restore_step_and_logs_stay_private():
    text = _text()
    restore = _step("Restore existing encrypted bars")
    assert text.count("secrets.") == restore.count("secrets.")
    assert "secrets.DATABENTO_API_KEY || secrets.DATABENTO_KEY" in restore
    assert "secrets.ICARUS_DATA_ARCHIVE_KEY" in restore
    assert "python -m tools.depth_vault restore" in restore
    assert '> "$PROOF_ROOT/restore.log" 2>&1' in restore
    consumer = _step("Consume private corpus with existing paper profiles")
    assert "secrets." not in consumer and "umask 077" in consumer
    assert '> "$PROOF_ROOT/consumer.log" 2>&1' in consumer
    assert "ICARUS_FEED: file" in consumer
    assert "pip install" not in consumer
    assert "databento_bar_baseline" not in text and "cl_lab" not in text


def test_consumer_blocks_socket_io_and_supplies_pinned_provenance(tmp_path, monkeypatch):
    import runpy
    import socket

    env = _env(tmp_path)
    (tmp_path / "consumer").mkdir()
    monkeypatch.setattr(os, "environ", env)
    # All mutations are scoped by monkeypatch, including the injected guard.
    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, getattr(socket.socket, name))
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, getattr(socket, name))
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    import sys
    monkeypatch.setattr(sys, "argv", [])
    seen = {}

    def consume(name, run_name):
        assert name == "tools.provider_corpus_intake" and run_name == "__main__"
        with pytest.raises(PermissionError):
            socket.create_connection(("provider.invalid", 443))
        with socket.socket() as client:
            with pytest.raises(PermissionError):
                client.connect(("127.0.0.1", 80))
        seen["args"] = list(sys.argv)
        return {}

    monkeypatch.setattr(runpy, "run_module", consume)
    exec(compile(_python("Consume private corpus with existing paper profiles"), "consume", "exec"), {})
    args = seen["args"]
    assert args[args.index("--source-commit") + 1] == "a" * 40
    assert args[args.index("--cache-name") + 1] == "bars_primary"
    assert args[args.index("--max-bars") + 1] == "6000"
    assert "--asof-ns" in args and "--available-at-ns" in args
    assert args.count("--include-requested-futures") == 1


def _receipt():
    return {"schema_version": "icarus-corpus-consumption-v1", "source_repo": "reppiks490/Icarus-engine",
            "source_commit": "a" * 40, "corpus_used": True, "paper_warmup_used": True,
            "raw_payloads_included": False,
            "execution_authorized": False, "production_decision_authorized": False,
            "market_validation": False, "datasets": [{"dataset_id": "d" * 64}],
            "read_receipts": [{"dataset_id": "d" * 64, "row_count": 4}],
            "workspaces": [{"id": name, "assets": [{"warm": True, "chart_bars": 4}]}
                           for name in ("cc1", "cc2", "cc3", "cc4")]}


def test_receipt_finalization_requires_actual_consumption_and_binds_both_revisions(tmp_path, monkeypatch):
    env = _env(tmp_path)
    receipt = Path(env["PROOF_ROOT"]) / "receipt.json"
    receipt.write_text(json.dumps(_receipt()))
    monkeypatch.setattr(os, "environ", env)
    exec(compile(_python("Validate safe consumption receipt"), "receipt", "exec"), {})
    doc = json.loads(receipt.read_text())
    assert doc["workflow_provenance"]["consumer_commit"] == "b" * 40
    assert doc["workflow_provenance"]["source_commit"] == "a" * 40
    assert doc["workflow_provenance"]["network_disabled"] is True
    assert receipt.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("patch", [{"corpus_used": False}, {"source_commit": "c" * 40},
                                  {"raw_payloads_included": True}, {"execution_authorized": True},
                                  {"read_receipts": []}, {"workspaces": []},
                                  {"read_receipts": [{"row_count": 0}]},
                                  {"read_receipts": [{"row_count": True}]},
                                  {"paper_warmup_used": False},
                                  {"datasets": [{"dataset_id": "e" * 64}]},
                                  {"workspaces": [{"id": "cc1", "assets": [{"warm": True, "chart_bars": 4}]}]}])
def test_validation_does_not_publish_validation_only_or_authorized_receipts(tmp_path, monkeypatch, patch):
    env = _env(tmp_path)
    receipt = Path(env["PROOF_ROOT"]) / "receipt.json"
    receipt.write_text(json.dumps({**_receipt(), **patch}))
    original = receipt.read_bytes()
    monkeypatch.setattr(os, "environ", env)
    with pytest.raises((SystemExit, ValueError)):
        exec(compile(_python("Validate safe consumption receipt"), "receipt", "exec"), {})
    assert receipt.read_bytes() == original


def test_real_quality_reads_can_prove_consumption_without_claiming_paper_warmup(tmp_path, monkeypatch):
    env = _env(tmp_path)
    env["CACHE_NAME"] = "bars_secondary"
    receipt = Path(env["PROOF_ROOT"]) / "receipt.json"
    doc = _receipt()
    doc["paper_warmup_used"] = False
    for row in doc["workspaces"]:
        row["assets"] = []
        row["unavailable_assets"] = ["MNQ"]
    receipt.write_text(json.dumps(doc))
    monkeypatch.setattr(os, "environ", env)
    exec(compile(_python("Validate safe consumption receipt"), "receipt", "exec"), {})
    actual = json.loads(receipt.read_text())
    assert actual["corpus_used"] is True and actual["paper_warmup_used"] is False
    assert all(not row["assets"] for row in actual["workspaces"])


@pytest.mark.parametrize("code", ["", "2", "127"])
def test_failed_consumer_exit_cannot_be_published_even_with_an_existing_receipt(tmp_path, monkeypatch, code):
    env = _env(tmp_path)
    env["CONSUMER_EXIT_CODE"] = code
    receipt = Path(env["PROOF_ROOT"]) / "receipt.json"
    receipt.write_text(json.dumps(_receipt()))
    monkeypatch.setattr(os, "environ", env)
    with pytest.raises(SystemExit):
        exec(compile(_python("Validate safe consumption receipt"), "receipt", "exec"), {})
    assert "workflow_provenance" not in json.loads(receipt.read_text())


def test_receipt_symlink_is_rejected_without_touching_target(tmp_path, monkeypatch):
    env = _env(tmp_path)
    target = tmp_path / "outside.json"
    target.write_text(json.dumps(_receipt()))
    receipt = Path(env["PROOF_ROOT"]) / "receipt.json"
    receipt.symlink_to(target)
    original = target.read_bytes()
    monkeypatch.setattr(os, "environ", env)
    with pytest.raises(OSError):
        exec(compile(_python("Validate safe consumption receipt"), "receipt", "exec"), {})
    assert target.read_bytes() == original


def test_only_validated_receipt_is_uploaded_and_private_storage_is_cleaned():
    upload = _step("Upload metadata receipt only")
    assert "steps.receipt.outcome == 'success'" in upload
    assert "path: ${{ env.PROOF_ROOT }}/receipt.json" in upload
    assert "if-no-files-found: error" in upload
    assert "include-hidden-files: false" in upload
    assert "if: always()" in _step("Remove private restored data and logs")
    assert "cat " not in _text() and "tee " not in _text()


def test_all_embedded_python_and_shell_are_syntactically_valid():
    for name in ("Validate immutable inputs", "Record source availability", 
                 "Consume private corpus with existing paper profiles", "Validate safe consumption receipt"):
        ast.parse(_python(name))
    for name in ("Validate immutable inputs", "Record source availability", "Restore existing encrypted bars",
                 "Consume private corpus with existing paper profiles", "Validate safe consumption receipt",
                 "Remove private restored data and logs"):
        completed = subprocess.run(["bash", "-n"], input=_script(name), text=True, capture_output=True)
        assert completed.returncode == 0, completed.stderr
