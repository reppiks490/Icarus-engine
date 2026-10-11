import base64

import pytest

pytest.importorskip("cryptography")

from tools import asset_panel, depth_vault  # noqa: E402

ENV = {"ICARUS_DATA_ARCHIVE_KEY": base64.b64encode(bytes(range(32))).decode()}
CSV = "ts,open,high,low,close,volume\n2026-06-01T08:05:00+00:00,1,2,0.5,1.5,10\n"


def _vaulted(tmp_path, names=("SPY_5m.csv",)):
    src, vault = tmp_path / "src", tmp_path / "vault"
    src.mkdir()
    for name in names:
        (src / name).write_text(CSV.replace("1.5", str(len(name))))
    depth_vault.seal({"panel": src}, vault, ENV, suffixes=(".csv",))
    return vault, src


def test_missing_panel_is_restored_from_the_vault(tmp_path):
    (vault, src), root = _vaulted(tmp_path), tmp_path / "panel"
    assert asset_panel.ensure_panel(root, vault, ENV) == root
    assert (root / "SPY_5m.csv").read_bytes() == (src / "SPY_5m.csv").read_bytes()


def test_partial_panel_is_completed_not_accepted(tmp_path):
    (vault, src), root = _vaulted(tmp_path, ("SPY_5m.csv", "QQQ_5m.csv")), tmp_path / "panel"
    root.mkdir()
    (root / "SPY_5m.csv").write_bytes((src / "SPY_5m.csv").read_bytes())
    asset_panel.ensure_panel(root, vault, ENV)
    assert (root / "QQQ_5m.csv").read_bytes() == (src / "QQQ_5m.csv").read_bytes()


def test_partial_panel_without_a_key_fails_with_instructions(tmp_path):
    (vault, src), root = _vaulted(tmp_path, ("SPY_5m.csv", "QQQ_5m.csv")), tmp_path / "panel"
    root.mkdir()
    (root / "SPY_5m.csv").write_bytes((src / "SPY_5m.csv").read_bytes())
    with pytest.raises(FileNotFoundError, match="tools.depth_vault restore --cache panel=data/panel"):
        asset_panel.ensure_panel(root, vault, {})


def test_corrupted_panel_file_is_an_error(tmp_path):
    (vault, src), root = _vaulted(tmp_path), tmp_path / "panel"
    root.mkdir()
    (root / "SPY_5m.csv").write_text(CSV + "2026-06-01T08:10:00+00:00,1,1,1,1,1\n")
    with pytest.raises(ValueError, match="differ from the vault manifest"):
        asset_panel.ensure_panel(root, vault, ENV)


def test_complete_panel_needs_no_key(tmp_path):
    (vault, src), root = _vaulted(tmp_path), tmp_path / "panel"
    root.mkdir()
    (root / "SPY_5m.csv").write_bytes((src / "SPY_5m.csv").read_bytes())
    assert asset_panel.ensure_panel(root, vault, {}) == root


def test_no_vaulted_inventory_is_an_error_not_an_empty_panel(tmp_path):
    root = tmp_path / "panel"
    root.mkdir()
    (root / "SPY_5m.csv").write_text(CSV)
    with pytest.raises(FileNotFoundError, match="no panel inventory"):
        asset_panel.ensure_panel(root, tmp_path / "vault", ENV)
