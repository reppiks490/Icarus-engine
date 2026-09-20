"""Fold an oversized query result into the packed MNQ tape.

The market-data workspace is remote, so a large result never comes back
through the conversation -- it spills to a JSON file on disk. That is the
cheap path for bulk history, and this script is the other half of it: read a
spill file, pull out the packed session rows, and merge them into the tape
keyed by date so re-running a range is idempotent.
"""

from __future__ import annotations

import csv
import io
import json
import sys

TAPE = "/home/user/Icarus-engine/data/mnq_20m_packed.txt"


def _read_tape() -> dict[str, str]:
    sessions: dict[str, str] = {}
    try:
        with open(TAPE, encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if raw and not raw.startswith("#"):
                    sessions[raw.split(",", 1)[0]] = raw
    except FileNotFoundError:
        pass
    return sessions


def main(spill_paths: list[str]) -> None:
    sessions = _read_tape()
    before = len(sessions)

    for path in spill_paths:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)["result"]
        reader = csv.reader(io.StringIO(payload))
        header = next(reader)
        if header != ["d", "base", "n", "pack"]:
            raise ValueError(f"{path}: unexpected header {header}")
        for day, base, count, pack in reader:
            # A holiday half-session is real data, but a stub is not worth a bar.
            if int(count) < 6:
                continue
            sessions[day] = f"{day},{base},{count},{pack}"

    with open(TAPE, "w", encoding="utf-8") as handle:
        for day in sorted(sessions):
            handle.write(sessions[day] + "\n")

    print(f"tape: {before} -> {len(sessions)} sessions ({len(sessions) - before:+d})")
    print(f"span: {min(sessions)} .. {max(sessions)}")


if __name__ == "__main__":
    main(sys.argv[1:])
