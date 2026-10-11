"""Read the coordination folder of the AIs working in this repo: who owes whom a reply, and what each is doing.

The protocol is in ``coordination/README.md``. In short:

- ``coordination/board/<ai>.md``: each AI's task table, edited only by that AI;
- ``coordination/inbox/to-<ai>/``: messages, one file each, never edited after they land. A reply is a new
  file in the other inbox whose ``Re:`` header names the file it answers.

This module never writes. It reports what is open so the daily briefing, the data-health sentinel and
either AI can see it without reading every file.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("coordination")
AIS = ("claude", "chatgpt", "atlas")   # Atlas: third worker, owner-verified 2026-10-11
STATUSES = ("planned", "in progress", "blocked", "waiting", "done")
NAME = re.compile(r"^\d{8}T\d{4}Z-[a-z0-9]+-[a-z0-9-]+\.md$")
REQUIRED = ("from", "to", "date", "subject", "reply-needed")
STALE_DAYS = 7


def _headers(text: str) -> dict[str, str]:
    """``Key: value`` lines up to the first blank line, keys lower-cased."""
    out = {}
    for line in text.splitlines():
        if not line.strip():
            break
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip().lower()] = value.strip()
    return out


def messages(root: Path) -> list[dict]:
    out = []
    for ai in AIS:
        folder = root / ROOT / "inbox" / f"to-{ai}"
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            if path.name.lower() == "readme.md":
                continue
            try:
                h = _headers(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                h = {}
            problems = [k for k in REQUIRED if not h.get(k)]
            if not NAME.match(path.name):
                problems.append("file name")
            out.append(dict(file=path.name, to=ai, sender=h.get("from", ""), subject=h.get("subject", ""),
                            date=h.get("date", ""), re=h.get("re", "").strip() or None,
                            reply_needed=h.get("reply-needed", "").lower().startswith("y"), problems=problems))
    return out


def _stem(name: str | None) -> str | None:
    return name[:-3] if name and name.endswith(".md") else name


def open_messages(msgs: list[dict]) -> list[dict]:
    """Messages that ask for a reply and have none yet."""
    answered = {_stem(m["re"]) for m in msgs if m["re"] and m["re"] != "-"}
    return [m for m in msgs if m["reply_needed"] and _stem(m["file"]) not in answered]


def _age_days(stamp: str, now: datetime) -> float | None:
    try:
        t = datetime.fromisoformat(stamp.strip()[:10])
    except ValueError:
        return None
    return (now.replace(tzinfo=None) - t).total_seconds() / 86400


def board(root: Path, ai: str, now: datetime) -> dict:
    """Parse the task table in ``coordination/board/<ai>.md``: counts per status and stale rows."""
    path = root / ROOT / "board" / f"{ai}.md"
    if not path.is_file():
        return dict(present=False, counts={}, stale=[], tasks=[])
    header, tasks = None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            header = None  # any non-table line ends the table; the next one starts with its own header
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        row = dict(zip(header, cells))
        if "status" in row:
            tasks.append(row)
    counts: dict[str, int] = {}
    stale = []
    for t in tasks:
        status = t["status"].lower()
        status = status if status in STATUSES else "other"
        counts[status] = counts.get(status, 0) + 1
        age = _age_days(t.get("updated", ""), now)
        if status == "in progress" and (age is None or age > STALE_DAYS):
            stale.append(t.get("id") or t.get("task", "?"))
    return dict(present=True, counts=counts, stale=stale, tasks=tasks)


def summary(root: Path = Path("."), now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    msgs = messages(root)
    pending = open_messages(msgs)
    return dict(
        awaiting_reply={ai: [m["file"] for m in pending if m["to"] == ai] for ai in AIS},
        malformed=[f"to-{m['to']}/{m['file']}: {', '.join(m['problems'])}" for m in msgs if m["problems"]],
        messages=len(msgs),
        boards={ai: {k: v for k, v in board(root, ai, now).items() if k != "tasks"} for ai in AIS},
    )


def markdown(s: dict) -> str:
    lines = []
    for ai in AIS:
        b = s["boards"][ai]
        counts = ", ".join(f"{k} {v}" for k, v in sorted(b["counts"].items())) if b["present"] else "no board"
        lines.append(f"- {ai}: {counts}; awaiting its reply: {len(s['awaiting_reply'][ai])}"
                     + (f"; stale in-progress: {', '.join(b['stale'])}" if b["stale"] else ""))
    if s["malformed"]:
        lines.append(f"- malformed messages: {'; '.join(s['malformed'])}")
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--json", action="store_true", help="print the full summary as JSON")
    a = ap.parse_args(argv)
    s = summary(a.root)
    if a.json:
        print(json.dumps(s, indent=1))
        return
    print(markdown(s))
    for ai in AIS:
        for name in s["awaiting_reply"][ai]:
            print(f"  open, to {ai}: {name}")


if __name__ == "__main__":
    main()
