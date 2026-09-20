"""Explicit research commands; no command applies a candidate to the engine."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from .advisory import AdvisoryError, AdvisoryLedger, MAX_BODY_BYTES, strict_json


def _read(path):
    with Path(path).open("rb") as stream:
        return strict_json(stream.read(MAX_BODY_BYTES + 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="research.sqlite3", help="separate advisory SQLite ledger")
    parser.add_argument("--sources", help="JSON object mapping source IDs to allowed HTTPS hostnames")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("status")
    for name in ("ingest", "propose"):
        command = commands.add_parser(name)
        command.add_argument("file", help="strict JSON input file")
    show = commands.add_parser("show")
    show.add_argument("proposal_id")
    review = commands.add_parser("review", help="explicit opt-in: sends proposal evidence to the selected paid provider API")
    review.add_argument("proposal_id")
    review.add_argument("--provider", choices=("openai", "anthropic"), required=True)
    export = commands.add_parser("export", help="prints a candidate artifact; never applies configuration")
    export.add_argument("proposal_id")
    export.add_argument("--baseline-hash", required=True, help="independently computed current baseline SHA-256")
    export.add_argument("--dataset-hash", required=True, help="independently computed current data SHA-256")
    args = parser.parse_args(argv)
    try:
        ledger = AdvisoryLedger(args.db, allowed_sources=_read(args.sources) if args.sources else {})
        if args.command in ("init", "status"):
            result = ledger.status()
        elif args.command == "ingest":
            result = ledger.ingest_event(_read(args.file))
        elif args.command == "propose":
            result = ledger.propose(_read(args.file))
        elif args.command == "show":
            result = ledger.get_proposal(args.proposal_id)
        elif args.command == "review":
            result = ledger.review(args.proposal_id, args.provider)
        else:
            result = ledger.export_candidate(args.proposal_id, args.baseline_hash, args.dataset_hash)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False))
        return 0
    except AdvisoryError as error:
        parser.exit(2, f"advisory: {error}\n")
    except (OSError, sqlite3.Error):
        parser.exit(2, "advisory: local file or database operation failed\n")


if __name__ == "__main__":
    raise SystemExit(main())
