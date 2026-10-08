"""Synthetic CLI regressions for private provider restore output."""

import json
import os
import stat
import sys

import pytest

from tools import provider_archive


def _restore(monkeypatch, tmp_path, output):
    archive = tmp_path / "synthetic.enc"
    archive.write_bytes(b"synthetic encrypted fixture")
    monkeypatch.setattr(provider_archive, "decrypt", lambda *args: {"synthetic": True})
    monkeypatch.setattr(sys, "argv", [
        "provider_archive", "--provider", "fred", "--run-id", "synthetic-run",
        "--archive", str(archive), "--output", str(output),
    ])
    provider_archive.main()


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode cannot certify Windows ACLs")
def test_restored_file_is_private_before_plaintext_serialization(monkeypatch, tmp_path):
    output = tmp_path / "private.json"
    original_dump = json.dump
    observed = []

    def inspect_then_write(data, stream, **kwargs):
        observed.append(stat.S_IMODE(os.fstat(stream.fileno()).st_mode))
        assert observed[-1] == 0o600, "plaintext output was created with public permissions"
        return original_dump(data, stream, **kwargs)

    monkeypatch.setattr(provider_archive.json, "dump", inspect_then_write)
    previous_umask = os.umask(0)
    try:
        _restore(monkeypatch, tmp_path, output)
    finally:
        os.umask(previous_umask)
    assert observed == [0o600]
    assert json.loads(output.read_text()) == {"synthetic": True}


def test_existing_output_is_never_overwritten(monkeypatch, tmp_path):
    output = tmp_path / "existing.json"
    output.write_bytes(b"original evidence")
    with pytest.raises(FileExistsError):
        _restore(monkeypatch, tmp_path, output)
    assert output.read_bytes() == b"original evidence"


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink fixture")
def test_output_symlink_cannot_redirect_plaintext(monkeypatch, tmp_path):
    original = tmp_path / "original.json"
    original.write_bytes(b"original evidence")
    output = tmp_path / "redirect.json"
    output.symlink_to(original)
    with pytest.raises(FileExistsError):
        _restore(monkeypatch, tmp_path, output)
    assert original.read_bytes() == b"original evidence"
    assert output.is_symlink()


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode cannot certify Windows ACLs")
def test_serialization_failure_leaves_no_public_plaintext(monkeypatch, tmp_path):
    output = tmp_path / "partial.json"

    def fail_after_partial_write(data, stream, **kwargs):
        stream.write("synthetic partial plaintext")
        raise ValueError("synthetic serialization failure")

    monkeypatch.setattr(provider_archive.json, "dump", fail_after_partial_write)
    previous_umask = os.umask(0)
    try:
        with pytest.raises(ValueError, match="synthetic serialization failure"):
            _restore(monkeypatch, tmp_path, output)
    finally:
        os.umask(previous_umask)
    assert output.read_text() == "synthetic partial plaintext"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
