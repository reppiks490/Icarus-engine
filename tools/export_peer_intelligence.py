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


def verify_packet_source_identity(
    packet: dict,
    *,
    expected_head: str,
) -> None:
    """Fail closed unless the packet is bound to the exact source HEAD and zero authority."""
    head = str(expected_head or "").strip().lower()
    if len(head) != 40 or any(ch not in "0123456789abcdef" for ch in head):
        raise ValueError("expected_head must be an exact 40-character Git SHA")
    if str(packet.get("source_commit") or "").lower() != head:
        raise ValueError("peer packet source_commit does not match export HEAD")
    for key in ("execution_authorized", "production_decision_authorized", "peer_write_authorized"):
        if packet.get(key) is not False:
            raise ValueError(f"peer packet authority invariant failed: {key}")
    claimed = str(packet.get("packet_id") or "").lower()
    unsigned = dict(packet)
    unsigned.pop("packet_id", None)
    computed = __import__("hashlib").sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    if claimed != computed:
        raise ValueError("peer packet_id does not match canonical packet content")


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
    parser.add_argument(
        "--require-head-match",
        action="store_true",
        help="Require packet source_commit to equal the repository HEAD used for export.",
    )
    args = parser.parse_args()

    root = Path(args.root)
    path, packet = export_packet(
        root,
        source_commit=args.source_commit,
        observed_at=args.observed_at,
        output=Path(args.output),
    )
    if args.require_head_match:
        verify_packet_source_identity(packet, expected_head=_git_head(root.resolve()))
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
