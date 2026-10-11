import base64

import pytest

pytest.importorskip("cryptography")

from tools import asset_panel, depth_vault  # noqa: E402

ENV = {"ICARUS_DATA_ARCHIVE_KEY": base64.b64encode(bytes(range(32))).decode()}
CSV = "ts,open,high,low,close,volume\n2026-06-01T08:05:00+00:00,1,2,0.5,1.5,10\n"


def _vaulted(tmp_path):
    src, vault = tmp_path / "src", tmp_path / "vault"
    src.mkdir()
    (src / "SPY_5m.csv").write_text(CSV)
    depth_vault.seal({"panel": src}, vault, ENV, suffixes=(".csv",))
    return vault


def test_missing_panel_is_restored_from_the_vault(tmp_path):
    vault, root = _vaulted(tmp_path), tmp_path / "panel"
    assert asset_panel.ensure_panel(root, vault, ENV) == root
    assert (root / "SPY_5m.csv").read_text() == CSV


def test_missing_panel_without_a_key_fails_with_instructions(tmp_path):
    vault = _vaulted(tmp_path)
    with pytest.raises(FileNotFoundError, match="tools.depth_vault restore --cache panel=data/panel"):
        asset_panel.ensure_panel(tmp_path / "panel", vault, {})


def test_present_panel_is_used_without_touching_the_vault(tmp_path):
    root = tmp_path / "panel"
    root.mkdir()
    (root / "SPY_5m.csv").write_text(CSV)
    assert asset_panel.ensure_panel(root, tmp_path / "no-vault", {}) == root


def test_no_panel_anywhere_is_an_error_not_an_empty_panel(tmp_path):
    with pytest.raises(FileNotFoundError, match="none in the vault"):
        asset_panel.ensure_panel(tmp_path / "panel", tmp_path / "vault", ENV)
