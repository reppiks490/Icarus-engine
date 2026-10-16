"""Every market on disk, as Bar lists, for cross-asset replication.

The durable panel source is the authenticated encrypted vault. During the
migration branch, the existing plaintext panel may still be present; once the
vault manifest contains the ``panel`` cache, every expected file is hash-bound
to that inventory and missing files are restored from ciphertext.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from icarus.data import Bar, load_csv

REPO = Path(__file__).resolve().parent.parent

# What each market actually is, so a result reads as "holds in metals but not
# in credit" rather than as a list of tickers.
ASSET_CLASS = {
    "SPY": "equity index", "QQQ": "equity index", "IWM": "equity index",
    "DIA": "equity index", "NVDA": "single stock",
    "GLD": "metals", "SLV": "metals", "USO": "energy", "UNG": "energy",
    "XLE": "energy sector", "XLK": "tech sector", "XLF": "financials",
    "TLT": "rates", "IEF": "rates", "HYG": "credit", "LQD": "credit",
    "UUP": "fx", "FXE": "fx", "VXX": "volatility",
    "EEM": "emerging", "EFA": "intl developed", "I:NDX": "index cash",
}


def ensure_panel(root: Path | None = None, vault: Path | None = None, env=None) -> Path:
    """Ensure the panel is complete and byte-identical to its vault inventory.

    Missing files are restored from ciphertext. A partial panel without a usable
    key is an error, as is any file whose SHA-256 differs from the manifest. The
    only migration exception is a still-complete plaintext tree before the first
    ``panel`` inventory has been sealed; the final merged state is required to
    include that inventory before the plaintext files are removed.
    """
    from tools import depth_vault

    root = Path(root or REPO / "data" / "panel")
    vault = Path(vault or REPO / "data" / "depth_vault")
    expected = (depth_vault._load_manifest(vault).get("caches") or {}).get("panel") or {}
    if not expected:
        existing = sorted(root.glob("*_5m.csv")) if root.is_dir() else []
        if existing:
            return root
        raise FileNotFoundError(f"the vault holds no panel inventory ({vault}); cannot recover {root}")

    missing = [rel for rel in expected if not (root / rel).exists()]
    if missing:
        try:
            depth_vault.restore({"panel": root}, vault, os.environ if env is None else env)
        except (ValueError, OSError) as ex:
            raise FileNotFoundError(
                "the panel is vaulted but incomplete locally. Set ICARUS_DATA_ARCHIVE_KEY (preferred) "
                "or DATABENTO_API_KEY and run: python -m tools.depth_vault restore "
                "--cache panel=data/panel"
            ) from ex

    still_missing = sorted(rel for rel in expected if not (root / rel).exists())
    if still_missing:
        raise FileNotFoundError(f"panel restore did not produce every manifest file: {still_missing}")

    bad = []
    for rel, meta in expected.items():
        digest = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        if digest != meta.get("sha256"):
            bad.append(rel)
    if bad:
        raise ValueError(f"panel files differ from the vault manifest: {sorted(bad)}. Delete them and restore again.")
    return root


def load_panel(min_bars: int = 2000, root: Path | None = None) -> dict[str, list[Bar]]:
    """Load every panel market, restoring the authenticated inventory when needed."""
    root = ensure_panel(root)
    panel: dict[str, list[Bar]] = {}
    for path in sorted(root.glob("*_5m.csv")):
        ticker = path.stem.rsplit("_5m", 1)[0].replace("_", ":")
        bars = load_csv(str(path))
        if len(bars) >= min_bars:
            panel[ticker] = bars
    return panel


def describe(panel: dict[str, list[Bar]]) -> str:
    lines = []
    for ticker, bars in sorted(panel.items()):
        span = (bars[-1].ts - bars[0].ts).days
        lines.append(
            f"  {ticker:<8s} {ASSET_CLASS.get(ticker,'?'):<14s} "
            f"{len(bars):6d} bars  {bars[0].ts.date()} .. {bars[-1].ts.date()} "
            f"({span}d)"
        )
    return "\n".join(lines)
