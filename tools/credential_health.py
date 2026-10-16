from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from icarus_engine.security.credentials import credential_status, load_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report GitHub-native credential availability without exposing values."
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="CANONICAL_NAME",
        help="Fail if this canonical credential is unavailable; may be repeated.",
    )
    parser.add_argument(
        "--json-lines",
        action="store_true",
        help="Emit one redacted JSON object per canonical credential.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    contract = load_contract()
    required = set(args.require)
    unknown = required.difference(contract)
    if unknown:
        for name in sorted(unknown):
            print(json.dumps({"canonical_name": name, "present": False, "error": "unknown_credential"}, sort_keys=True))
        return 2

    missing_required: list[str] = []
    for canonical in sorted(contract):
        status = credential_status(canonical)
        payload = status.as_dict()
        if args.json_lines:
            print(json.dumps(payload, sort_keys=True))
        else:
            state = "present" if status.present else "missing"
            alias = status.matched_alias or "-"
            print(f"{canonical}: {state} via {alias}")
        if canonical in required and not status.present:
            missing_required.append(canonical)

    return 1 if missing_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
