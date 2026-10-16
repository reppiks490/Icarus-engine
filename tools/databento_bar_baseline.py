"""Stage one immutable, account-labelled baseline of cached Databento bars.

Only encrypted output from tools.depth_vault may enter Git. This module stages
gzip files in runner temp; it never prints or commits market rows. Existing
vault entries are deliberately not replaced when the rolling feed cache grows.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
from pathlib import Path


ACCOUNTS = ("primary", "secondary", "third")
MAX_FILE_BYTES = 90_000_000  # Leave room under GitHub's per-blob limit.
FEED_NAME = re.compile(r"databento_[a-z0-9]+_5m\Z")
HISTORY_ROOT = re.compile(r"[A-Z0-9]+\Z")


def _candidates(feeds: dict, history: dict) -> dict[tuple[str, str], None]:
    found = {}
    for name, row in feeds.get("feeds", {}).items():
        if row.get("kind") != "databento" or row.get("status") != "ok":
            continue
        if not FEED_NAME.fullmatch(name):
            raise ValueError("Databento feed name is unsafe")
        accounts = [note.removeprefix("account=") for note in row.get("notes", [])
                    if isinstance(note, str) and note.startswith("account=")]
        if len(accounts) != 1 or accounts[0] not in ACCOUNTS:
            raise ValueError(f"Databento feed has no unique supported account: {name}")
        found[(accounts[0], f"{name}.csv.gz")] = None
    for root, row in history.get("roots", {}).items():
        if not row.get("finished"):
            continue
        if not HISTORY_ROOT.fullmatch(root) or row.get("account") not in ACCOUNTS:
            raise ValueError("finished Databento history has an unsafe root or account")
        found[(row["account"], f"databento_hist_{root.lower()}_5m.csv.gz")] = None
    return found


def prepare(cache: Path, stage: Path, feeds: Path, history: Path, vault: Path) -> dict:
    feed_doc = json.loads(feeds.read_text(encoding="utf-8"))
    history_doc = json.loads(history.read_text(encoding="utf-8"))
    manifest_file = vault / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
    existing = manifest.get("caches", {})
    stage.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(stage, 0o700)
    staged = retained = 0
    by_account = {account: 0 for account in ACCOUNTS}
    for account, filename in sorted(_candidates(feed_doc, history_doc)):
        group = f"bars_{account}"
        if filename in existing.get(group, {}):
            retained += 1
            continue
        source = cache / filename
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"Databento baseline source missing: {account}/{filename}")
        if source.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"Databento baseline file exceeds Git blob limit: {account}/{filename}")
        # Read through EOF so gzip checks its CRC before the file is vaulted.
        with gzip.open(source, "rb") as stream:
            for _ in iter(lambda: stream.read(1 << 20), b""):
                pass
        target = stage / group / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        staged += 1
        by_account[account] += 1
    return {"candidates": staged + retained, "staged": staged,
            "already_vaulted": retained, "staged_by_account": by_account}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=Path(".cl_cache"))
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--feeds", type=Path, default=Path("automation_intelligence/cl_lab/feeds_manifest.json"))
    parser.add_argument("--history", type=Path, default=Path("automation_intelligence/cl_lab/history_status.json"))
    parser.add_argument("--vault", type=Path, default=Path("data/depth_vault"))
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.cache, args.stage, args.feeds, args.history, args.vault), sort_keys=True))


if __name__ == "__main__":
    main()
