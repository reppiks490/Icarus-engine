# CL (Claude, Anthropic) — 2026-10-11 — cl_lab.trial_ledger: the global trial ledger (FR-1 §8, R01 duty)
"""One record per research trial ever run, so multiple-testing corrections count every attempt.

``automation_intelligence/research/trial_ledger.jsonl`` is append-only. Each record is
``{"trial_id", "source", "source_path", "row_sha256"}``; nothing time-dependent, so importing the same
sources twice adds nothing. Historical sources (``docs/FRONTIER_PREREG_FR1.md`` §8):

- ``cl-lab``: every (asset, rule) evaluation in ``automation_intelligence/cl_lab/candidates_latest.jsonl``;
  ``latest.json`` and the run history are read to check the declared rule count;
- ``cl-explore``: every row of ``explore_ledger.jsonl``;
- ``cl-boos1``: every cl-boos1 candidate (``boos_records.jsonl``, checked against ``boos_latest.json``);
- ``pulse``: each THE PULSE variant in ``pulse_latest.json``;
- ``depth-d1``: each pre-registered D1 test that has run (status other than ``INSUFFICIENT_DATA``).

An unreadable source, or counts below the totals in ``ICARUS_STATE.md`` §2, makes the import ``BLOCKED``.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

LEDGER = "automation_intelligence/research/trial_ledger.jsonl"
CL = "automation_intelligence/cl_lab"
MIN_RULES = 492          # ICARUS_STATE.md §2: 492 pre-registered CL rules
MIN_EXPLORE = 2160       # ICARUS_STATE.md §2: 2,160 explorer attempts
D1_NOT_RUN = {None, "INSUFFICIENT_DATA", "NOT_RUN", "UNAVAILABLE"}


class SourceError(RuntimeError):
    """A trial source could not be read; FR-1 must not compute anything."""


def row_sha256(row) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise SourceError(f"unreadable trial source {path}: {type(ex).__name__}: {ex}") from ex


def _read_jsonl(path: Path) -> list:
    try:
        with path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError) as ex:
        raise SourceError(f"unreadable trial source {path}: {type(ex).__name__}: {ex}") from ex


def _rec(source: str, key: str, path: str, row) -> dict:
    return dict(trial_id=f"{source}:{key}", source=source, source_path=path, row_sha256=row_sha256(row))


def historical_trials(root: str | os.PathLike = ".") -> tuple[list[dict], dict]:
    """(records, checks) from every historical source. Raises :class:`SourceError` if any is unreadable."""
    root = Path(root)
    cl = root / CL
    recs: list[dict] = []

    cand_path = f"{CL}/candidates_latest.jsonl"
    cands = _read_jsonl(root / cand_path)
    latest = _read_json(cl / "latest.json")
    history_dir = cl / "history"
    try:
        history = sorted(history_dir.glob("*.json"))
    except OSError as ex:
        raise SourceError(f"unreadable trial source {history_dir}: {ex}") from ex
    for h in history:
        _read_json(h)                                     # readable, or the import is blocked
    for r in cands:
        recs.append(_rec("cl-lab", f"{r['asset']}:{r['id']}", cand_path, r))
    rule_ids = {r["id"] for r in cands}

    exp_path = f"{CL}/explore_ledger.jsonl"
    explore = _read_jsonl(root / exp_path)
    for r in explore:
        recs.append(_rec("cl-explore", f"{r['asset']}:{r['id']}", exp_path, r))

    boos_path = f"{CL}/boos_records.jsonl"
    boos = _read_jsonl(root / boos_path)
    boos_latest = _read_json(cl / "boos_latest.json")
    for r in boos:
        recs.append(_rec("cl-boos1", f"{r['family']}:{r['id']}", boos_path, r))

    pulse_path = f"{CL}/pulse_latest.json"
    pulse = _read_json(root / pulse_path)
    for name, v in sorted((pulse.get("variants") or {}).items()):
        recs.append(_rec("pulse", str(name), pulse_path, v))

    d1_path = f"{CL}/depth_d1_latest.json"
    d1 = _read_json(root / d1_path)
    for name in sorted(k for k in d1 if k.startswith("D1-")):
        v = d1[name]
        if isinstance(v, dict) and v.get("status") not in D1_NOT_RUN:
            recs.append(_rec("depth-d1", name, d1_path, v))

    checks = dict(
        cl_rules_unique=len(rule_ids), cl_rules_declared=latest.get("candidates"), cl_history_runs=len(history),
        explore_rows=len(explore), boos_records=len(boos), boos_declared=boos_latest.get("records"),
        pulse_variants=len(pulse.get("variants") or {}),
    )
    return recs, checks


def blockers(checks: dict) -> list[str]:
    out = []
    if checks["cl_rules_unique"] < MIN_RULES:
        out.append(f"cl-lab rules {checks['cl_rules_unique']} < {MIN_RULES} (ICARUS_STATE.md §2)")
    if checks["explore_rows"] < MIN_EXPLORE:
        out.append(f"explorer rows {checks['explore_rows']} < {MIN_EXPLORE} (ICARUS_STATE.md §2)")
    if checks.get("boos_declared") is not None and checks["boos_records"] != checks["boos_declared"]:
        out.append(f"boos records {checks['boos_records']} != declared {checks['boos_declared']}")
    return out


def load(path: str | os.PathLike) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return _read_jsonl(p)


def append(path: str | os.PathLike, records: list[dict]) -> int:
    """Append records whose ``trial_id`` is new; returns how many were added. Idempotent."""
    p = Path(path)
    have = {r["trial_id"] for r in load(p)}
    new, seen = [], set()
    for r in records:
        if r["trial_id"] not in have and r["trial_id"] not in seen:
            new.append(r)
            seen.add(r["trial_id"])
    if new:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            for r in sorted(new, key=lambda x: x["trial_id"]):
                fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
    return len(new)


def snapshot(path: str | os.PathLike, exclude_sources=()) -> dict:
    """Total, count per source and SHA-256 of the ledger bytes (FR-1 §8 frozen snapshot)."""
    p = Path(path)
    rows = [r for r in load(p) if r.get("source") not in set(exclude_sources)]
    by: dict[str, int] = {}
    for r in rows:
        by[r["source"]] = by.get(r["source"], 0) + 1
    digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    return dict(total=len(rows), by_source=dict(sorted(by.items())), ledger_sha256=digest,
                excluded_sources=sorted(exclude_sources))


def import_historical(root: str | os.PathLike = ".", ledger: str | os.PathLike | None = None) -> dict:
    """Import every historical trial. Returns ``{status, added, checks, blockers}``; never raises."""
    ledger = ledger or Path(root) / LEDGER
    try:
        recs, checks = historical_trials(root)
    except (SourceError, KeyError, TypeError) as ex:
        return dict(status="BLOCKED", added=0, checks=None, blockers=[str(ex)])
    bad = blockers(checks)
    if bad:
        return dict(status="BLOCKED", added=0, checks=checks, blockers=bad)
    return dict(status="OK", added=append(ledger, recs), checks=checks, blockers=[])
