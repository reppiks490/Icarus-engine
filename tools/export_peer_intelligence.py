from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from icarus_engine.interrepo_bridge import build_peer_packet


DEFAULT_OUTPUT = Path("automation_intelligence/interrepo/latest.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def export_packet(
    root: Path,
    *,
    source_commit: str | None = None,
    observed_at: str | None = None,
    output: Path = DEFAULT_OUTPUT,
) -> tuple[Path, dict]:
    root = root.resolve()
    commit = source_commit or _git_head(root)
    observed = observed_at or _utc_now()
    packet = build_peer_packet(
        root,
        source_commit=commit,
        observed_at=observed,
        source_repository="reppiks490/Icarus-engine",
    )

    target = root / output
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(packet, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        prefix=".peer-packet-",
        delete=False,
    ) as handle:
        temp = Path(handle.name)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, target)
    return target, packet


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the revision-bound research-only ICARUS peer intelligence packet."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--source-commit")
    parser.add_argument("--observed-at")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    path, packet = export_packet(
        Path(args.root),
        source_commit=args.source_commit,
        observed_at=args.observed_at,
        output=Path(args.output),
    )
    print(
        json.dumps(
            {
                "path": str(path),
                "packet_id": packet["packet_id"],
                "source_commit": packet["source_commit"],
                "execution_authorized": packet["execution_authorized"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
