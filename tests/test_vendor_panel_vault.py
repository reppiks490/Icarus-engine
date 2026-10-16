import base64
import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from tools import asset_panel, data_sentinel, depth_vault  # noqa: E402

ENV = {"ICARUS_DATA_ARCHIVE_KEY": base64.b64encode(bytes(range(32))).decode()}
CSV = "ts,open,high,low,close,volume\n2026-06-01T08:05:00+00:00,1,2,0.5,1.5,10\n"


def _panel(tmp_path: Path, names=("SPY_5m.csv",)):
    root = tmp_path / "panel-src"
    root.mkdir()
    for i, name in enumerate(names, 1):
        (root / name).write_text(CSV.replace("1.5", str(i + 0.5)), encoding="utf-8")
    return root


def _write_sources(vault: Path, **caches):
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "sources.json").write_text(
        json.dumps({"schema": "icarus.vault_sources/1", "caches": caches}), encoding="utf-8"
    )


def _seal_panel(tmp_path: Path, names=("SPY_5m.csv",)):
    src, vault = _panel(tmp_path, names), tmp_path / "vault"
    depth_vault.seal({"panel": src}, vault, ENV, suffixes=(".csv",))
    _write_sources(vault, panel={"origin": "preserved_original", "provider": "Polygon/Massive"})
    depth_vault.label(vault, tmp_path / "no-ledgers")
    return src, vault


def test_plain_csv_is_sealed_only_when_explicitly_selected(tmp_path):
    src, vault = _panel(tmp_path), tmp_path / "vault"
    assert depth_vault.seal({"panel": src}, vault, ENV)["files"] == 0
    assert depth_vault.seal({"panel": src}, vault, ENV, suffixes=(".csv",))["added_objects"] == 1
    restored = tmp_path / "restored"
    assert depth_vault.restore({"panel": restored}, vault, ENV)["restored"] == 1
    assert (restored / "SPY_5m.csv").read_bytes() == (src / "SPY_5m.csv").read_bytes()


def test_restore_refuses_parent_traversal_and_malformed_hash(tmp_path):
    src, vault = _seal_panel(tmp_path)
    manifest_path = vault / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    meta = next(iter(manifest["caches"]["panel"].values()))
    manifest["caches"]["panel"]["../escape.csv"] = dict(meta)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes its cache"):
        depth_vault.restore({"panel": tmp_path / "restore"}, vault, ENV)
    assert not (tmp_path / "escape.csv").exists()

    manifest["caches"]["panel"] = {"bad.csv": {"sha256": "../../manifest", "bytes": 1}}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="hash is malformed"):
        depth_vault.restore({"panel": tmp_path / "restore-2"}, vault, ENV)


def test_restore_refuses_symlink_escape(tmp_path):
    src, vault = _seal_panel(tmp_path)
    manifest_path = vault / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    meta = next(iter(manifest["caches"]["panel"].values()))
    manifest["caches"]["panel"] = {"sub/SPY_5m.csv": meta}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target, outside = tmp_path / "restore", tmp_path / "outside"
    target.mkdir()
    outside.mkdir()
    (target / "sub").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes its cache"):
        depth_vault.restore({"panel": target}, vault, ENV)
    assert not list(outside.iterdir())


def test_preserved_original_label_and_verify_write_no_plaintext(tmp_path):
    src, vault = _seal_panel(tmp_path, ("SPY_5m.csv", "QQQ_5m.csv"))
    origins = json.loads((vault / "origins.json").read_text(encoding="utf-8"))
    assert origins["unlabelled_caches"] == []
    assert {row["origin"] for row in origins["objects"].values()} == {"preserved_original"}
    assert all(row["purchased_at"] is None for row in origins["objects"].values())

    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    receipt = depth_vault.verify(vault, ENV, ledger_dir=tmp_path / "no-ledgers")
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert receipt["verdict"] == "OK"
    assert receipt["caches"]["panel"]["authenticated"] == 2
    assert receipt["failure_count"] == 0 and receipt["label_mismatch_count"] == 0
    assert receipt["plaintext_written"] is False
    assert after == before


def test_verify_detects_ciphertext_tampering(tmp_path):
    src, vault = _seal_panel(tmp_path)
    obj = next((vault / "objects").glob("*.bin"))
    blob = bytearray(obj.read_bytes())
    blob[-1] ^= 1
    obj.write_bytes(bytes(blob))
    receipt = depth_vault.verify(vault, ENV, ledger_dir=tmp_path / "no-ledgers")
    assert receipt["verdict"] == "FAILED"
    assert receipt["failure_count"] == 1


def test_missing_or_partial_panel_is_restored_from_authenticated_vault(tmp_path):
    src, vault = _seal_panel(tmp_path, ("SPY_5m.csv", "QQQ_5m.csv"))
    root = tmp_path / "panel"
    root.mkdir()
    (root / "SPY_5m.csv").write_bytes((src / "SPY_5m.csv").read_bytes())
    assert asset_panel.ensure_panel(root, vault, ENV) == root
    assert (root / "QQQ_5m.csv").read_bytes() == (src / "QQQ_5m.csv").read_bytes()


def test_panel_restore_fails_closed_without_key_or_on_corruption(tmp_path):
    src, vault = _seal_panel(tmp_path, ("SPY_5m.csv", "QQQ_5m.csv"))
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "SPY_5m.csv").write_bytes((src / "SPY_5m.csv").read_bytes())
    with pytest.raises(FileNotFoundError, match="tools.depth_vault restore"):
        asset_panel.ensure_panel(partial, vault, {})

    complete = tmp_path / "complete"
    complete.mkdir()
    for p in src.glob("*.csv"):
        (complete / p.name).write_bytes(p.read_bytes())
    assert asset_panel.ensure_panel(complete, vault, {}) == complete
    (complete / "SPY_5m.csv").write_text("corrupt\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differ from the vault manifest"):
        asset_panel.ensure_panel(complete, vault, {})


def test_sentinel_reports_vault_verification_receipt(tmp_path):
    vault = tmp_path / "data" / "depth_vault"
    vault.mkdir(parents=True)
    (vault / "manifest.json").write_text(
        json.dumps({"caches": {"panel": {"SPY_5m.csv": {"sha256": "0" * 64, "bytes": 1}}}, "key_source": "ICARUS_DATA_ARCHIVE_KEY"}),
        encoding="utf-8",
    )
    receipt = tmp_path / "automation_intelligence" / "sentinel" / "vault_verify.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"verdict": "OK", "verified_at": "2026-10-16T03:45:00+00:00", "failure_count": 0}), encoding="utf-8")
    report = data_sentinel.depth(tmp_path)
    assert report["vault_verify"] == {
        "verdict": "OK",
        "verified_at": "2026-10-16T03:45:00+00:00",
        "failures": 0,
    }
