# CL (Claude, Anthropic) — 2026-10-11 — cl_lab.trial_ledger: the global trial ledger (FR-1 §8, R01 duty)
"""One record per research trial ever run, so multiple-testing corrections count every attempt.

``automation_intelligence/research/trial_ledger.jsonl`` is append-only. Each record is
``{"trial_id", "source", "source_path", "row_sha256"}``; nothing time-dependent, so importing the same
sources twice adds nothing. Historical sources (``docs/FRONTIER_PREREG_FR1.md`` §8):

- ``cl-lab``: every (run, asset, rule) evaluation in ``candidates_latest.jsonl`` and retained
  ``history/<run_id>.candidates.jsonl`` archives, validated against each run's declarations;
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
import tempfile
from contextlib import contextmanager
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
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise SourceError(f"trial source must be a JSON object: {path}")
        return value
    except (OSError, ValueError) as ex:
        raise SourceError(f"unreadable trial source {path}: {type(ex).__name__}: {ex}") from ex


def _read_jsonl(path: Path) -> list:
    try:
        with path.open(encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        if not all(isinstance(row, dict) for row in rows):
            raise SourceError(f"trial rows must be JSON objects: {path}")
        return rows
    except (OSError, ValueError) as ex:
        raise SourceError(f"unreadable trial source {path}: {type(ex).__name__}: {ex}") from ex


def _rec(source: str, key: str, path: str, row) -> dict:
    return dict(trial_id=f"{source}:{key}", source=source, source_path=path, row_sha256=row_sha256(row))


def _diagnostic_count(value) -> int:
    """Count actual evaluation declarations, without inventing missing per-trial rows."""
    if not isinstance(value, dict):
        return 0
    total = 0
    for key, child in value.items():
        if key == "diagnostics" and isinstance(child, dict) and "candidates" in child:
            n = child["candidates"]
            if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                raise SourceError("invalid historical candidates declaration")
            total += n
        elif isinstance(child, dict):
            total += _diagnostic_count(child)
    return total


def _cl_trials(root: Path, cands: list, latest: dict, history: list[Path], explore: list) -> list[dict]:
    summaries = {}
    for path, summary in [(root / CL / "latest.json", latest)] + [(p, _read_json(p)) for p in history]:
        run = summary.get("run_id")
        if not isinstance(run, str) or not run or Path(run).name != run:
            raise SourceError(f"missing/invalid historical run_id in {path}")
        if run in summaries and summaries[run] != summary:
            raise SourceError(f"conflicting historical summary for {run}")
        summaries[run] = summary
    grouped = {}
    for row in cands:
        grouped.setdefault(row["run_id"], []).append(row)
    if set(grouped) != {latest["run_id"]}:
        raise SourceError("candidates_latest must contain exactly the declared latest run")
    explorer_keys = {(x["asset"], x["id"], x.get("run_id", x.get("run"))) for x in explore}
    records = []
    for run, summary in sorted(summaries.items()):
        rel = f"{CL}/candidates_latest.jsonl"
        rows = grouped.get(run)
        if rows is None:
            rel = f"{CL}/history/{run}.candidates.jsonl"
            if not (root / rel).is_file():
                raise SourceError(f"unrecoverable historical evaluations for {run}: missing {rel}")
            rows = _read_jsonl(root / rel)
        assets = summary.get("assets")
        if not isinstance(assets, dict):
            raise SourceError(f"missing historical asset declarations for {run}")
        expected = {}
        for asset, evidence in assets.items():
            if evidence.get("status") == "EVALUATED":
                declared = summary.get("candidates")
                base = evidence.get("diagnostics", {}).get("candidates")
                if (isinstance(declared, bool) or not isinstance(declared, int) or declared < 0
                        or base != declared):
                    raise SourceError(f"conflicting rule count declaration for {run}/{asset}")
                expected[asset] = _diagnostic_count(evidence)
                if not expected[asset]:
                    raise SourceError(f"missing historical evaluation counts for {run}/{asset}")
        calendar = summary.get("calendar_flows", {})
        if calendar.get("status") == "EVALUATED":
            declared = calendar.get("records")
            if not isinstance(declared, list):
                raise SourceError(f"missing calendar trial records for {run}")
            expected["NDX"] = len(declared)
        actual, seen = {}, set()
        for row in rows:
            if row.get("run_id") != run:
                raise SourceError(f"wrong run identity in {rel}: expected {run}")
            key = (row["asset"], row["id"])
            if key in seen:
                raise SourceError(f"duplicate historical evaluation {run}/{key}")
            seen.add(key)
            actual[key[0]] = actual.get(key[0], 0) + 1
            # Explorer rows are already represented by the append-only explorer source.
            if (*key, None) in explorer_keys:
                raise SourceError(f"ambiguous unversioned explorer overlap for {run}/{key}")
            if (*key, run) not in explorer_keys:
                records.append(_rec("cl-lab", f"{run}:{key[0]}:{key[1]}", rel, row))
        if actual != expected:
            raise SourceError(f"incomplete historical evaluations for {run}: rows {actual} != declared {expected}")
    return records


def _input_version(source: dict, label: str) -> str:
    value = source.get("fingerprint") or source.get("input_fingerprint")
    if not isinstance(value, str) or not value or Path(value).name != value or value in (".", ".."):
        raise SourceError(f"unversioned {label}: recover the original input fingerprint/archive")
    return value


def _auxiliary_trials(root: Path, summaries: list[tuple[str, dict]], boos: list, boos_latest: dict,
                      pulse: dict, d1: dict) -> list[dict]:
    """Import retained source versions; summaries without reconstructable provenance block."""
    boos_path, pulse_path, d1_path = (f"{CL}/{name}" for name in
                                    ("boos_records.jsonl", "pulse_latest.json", "depth_d1_latest.json"))
    bv = _input_version(boos_latest, "cl-boos1") if boos else None
    boos_versions = {bv: (boos_path, boos, boos_latest.get("records"))} if boos else {}
    variants = pulse.get("variants") or {}
    pv = _input_version(pulse, "pulse") if variants else None
    pulse_versions = {pv: (pulse_path, variants)} if variants else {}
    for path, summary in summaries:
        old = summary.get("backward_oos", {})
        if old.get("status") == "EVALUATED":
            version = _input_version(old, f"historical cl-boos1 in {path}")
            if version not in boos_versions:
                rel = f"{CL}/history/boos/{version}.json"
                if not (root / rel).is_file():
                    raise SourceError(f"missing historical cl-boos1 archive {version}: {rel}")
                archive = _read_json(root / rel)
                if _input_version(archive, rel) != version:
                    raise SourceError(f"wrong historical cl-boos1 fingerprint in {rel}")
                rows = archive.get("candidate_rows")
                if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                    raise SourceError(f"missing actual cl-boos1 candidate rows in {rel}")
                boos_versions[version] = (rel, rows, old.get("records"))
            if boos_versions[version][2] != old.get("records"):
                raise SourceError(f"conflicting historical cl-boos1 counts for {version}")
        for asset in summary.get("assets", {}).values():
            old = asset.get("pulse", {})
            vs = old.get("variants") or {}
            if vs:
                version = _input_version(old, f"historical pulse in {path}")
                if version in pulse_versions and pulse_versions[version][1] != vs:
                    raise SourceError(f"conflicting historical pulse variants for {version}")
                pulse_versions.setdefault(version, (path, vs))
    recs = []
    for version, (path, rows, declared) in sorted(boos_versions.items()):
        if declared != len(rows):
            raise SourceError(f"incomplete cl-boos1 candidate archive for {version}")
        seen = set()
        for row in rows:
            key = f"{version}:{row['family']}:{row['id']}"
            if key in seen:
                raise SourceError(f"duplicate cl-boos1 trial {key}")
            seen.add(key)
            recs.append(_rec("cl-boos1", key, path, row))
    for version, (path, vs) in sorted(pulse_versions.items()):
        if not isinstance(vs, dict):
            raise SourceError(f"invalid pulse variants in {path}")
        for name, row in sorted(vs.items()):
            recs.append(_rec("pulse", f"{version}:{name}", path, row))
    depth_sources = [(d1_path, d1)] + [(str(p.relative_to(root)), _read_json(p))
                                     for p in sorted((root / CL / "history" / "depth-d1").glob("*.json"))]
    for path, source in depth_sources:
        for name in sorted(k for k in source if k.startswith("D1-")):
            row = source[name]
            if isinstance(row, dict) and row.get("status") not in D1_NOT_RUN:
                version = _input_version(source, f"depth-d1 in {path}")
                recs.append(_rec("depth-d1", f"{version}:{name}", path, row))
    return recs


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
        if not history_dir.is_dir():
            raise SourceError(f"missing historical trial source {history_dir}")
        history = sorted(history_dir.glob("*.json"))
        if not history:
            raise SourceError(f"empty historical trial source {history_dir}")
    except OSError as ex:
        raise SourceError(f"unreadable trial source {history_dir}: {ex}") from ex
    rule_ids = {r["id"] for r in cands}

    exp_path = f"{CL}/explore_ledger.jsonl"
    explore = _read_jsonl(root / exp_path)
    recs.extend(_cl_trials(root, cands, latest, history, explore))
    explorer_ids = set()
    for r in explore:
        run = r.get("run_id", r.get("run", "unversioned"))
        key = f"{run}:{r['asset']}:{r['id']}"
        if key in explorer_ids:
            raise SourceError(f"duplicate explorer trial {key}")
        explorer_ids.add(key)
        recs.append(_rec("cl-explore", key, exp_path, r))

    boos_path = f"{CL}/boos_records.jsonl"
    boos = _read_jsonl(root / boos_path)
    boos_latest = _read_json(cl / "boos_latest.json")

    pulse_path = f"{CL}/pulse_latest.json"
    pulse = _read_json(root / pulse_path)

    d1_path = f"{CL}/depth_d1_latest.json"
    d1 = _read_json(root / d1_path)
    summaries = [(f"{CL}/latest.json", latest)] + [(str(p.relative_to(root)), _read_json(p)) for p in history]
    recs.extend(_auxiliary_trials(root, summaries, boos, boos_latest, pulse, d1))

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


@contextmanager
def _locked(path: Path):
    """Serialize same-filesystem writers and snapshots. Unsupported lock platforms fail closed."""
    try:
        import fcntl
    except ImportError as ex:
        raise SourceError("global trial ledger requires POSIX advisory file locking") from ex
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(str(path) + ".lock").open("a+b") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


@contextmanager
def run_lock(ledger_path: str | os.PathLike):
    """Hold one process-wide lock across a complete FR-1 run keyed by its ledger."""
    ledger = Path(ledger_path).expanduser().resolve()
    lock_target = ledger.with_name(ledger.name + ".run")
    with _locked(lock_target):
        yield


def _identities(rows: list[dict]) -> dict:
    have = {}
    for row in rows:
        key = row["trial_id"]
        if key in have:
            raise SourceError(f"duplicate/conflicting ledger trial_id {key}")
        have[key] = row
    return have


def _snapshot_records(rows: list[dict], exclude_sources=()) -> dict:
    excluded = set(exclude_sources)
    included = [r for r in rows if r.get("source") not in excluded]
    by = {}
    for row in included:
        by[row["source"]] = by.get(row["source"], 0) + 1
    return dict(total=len(included), by_source=dict(sorted(by.items())),
                included_records_sha256=row_sha256(sorted(included, key=lambda r: r["trial_id"])),
                excluded_sources=sorted(excluded))


def append(path: str | os.PathLike, records: list[dict], *, frozen_snapshot: dict | None = None) -> int:
    """Idempotent, locked append; conflicting identities fail before any record is written."""
    p = Path(path)
    with _locked(p):
        have = _identities(load(p))
        new = {}
        for row in records:
            key = row["trial_id"]
            prior = have.get(key, new.get(key))
            # Archiving a formerly current source changes its location, not its trial identity.
            if prior is not None and ({k: v for k, v in prior.items() if k != "source_path"}
                                      != {k: v for k, v in row.items() if k != "source_path"}):
                raise SourceError(f"conflicting ledger trial_id {key}")
            if prior is None:
                new[key] = row
        if frozen_snapshot is not None:
            # The full-file hash changes when FR-1 records are appended. Compare the frozen
            # historical records themselves; never silently re-freeze changed global history.
            projected = _snapshot_records(list(have.values()) + list(new.values()), ("fr-1",))
            if any(frozen_snapshot.get(k) != v for k, v in projected.items()):
                raise SourceError("frozen snapshot mismatch: historical trial evidence changed or is unbound")
        if new:
            original = p.read_bytes() if p.exists() else b""
            if original and not original.endswith(b"\n"):
                raise SourceError("ledger must end with a complete newline-terminated record")
            suffix = "".join(json.dumps(new[k], sort_keys=True, separators=(",", ":")) + "\n" for k in sorted(new))
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(dir=p.parent, prefix=p.name + ".", delete=False) as fh:
                    tmp = fh.name
                    fh.write(original + suffix.encode())
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, p)
            finally:
                if tmp is not None and os.path.exists(tmp):
                    os.unlink(tmp)
        return len(new)


def snapshot(path: str | os.PathLike, exclude_sources=()) -> dict:
    """Total, count per source and SHA-256 of the ledger bytes (FR-1 §8 frozen snapshot)."""
    p = Path(path)
    with _locked(p):
        all_rows = load(p)
        _identities(all_rows)
        result = _snapshot_records(all_rows, exclude_sources)
        digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    return dict(result, ledger_sha256=digest)


def import_historical(root: str | os.PathLike = ".", ledger: str | os.PathLike | None = None,
                      *, frozen_snapshot: dict | None = None) -> dict:
    """Import every historical trial. Returns ``{status, added, checks, blockers}``; never raises."""
    ledger = ledger or Path(root) / LEDGER
    try:
        recs, checks = historical_trials(root)
        bad = blockers(checks)
        if bad:
            return dict(status="BLOCKED", added=0, checks=checks, blockers=bad)
        return dict(status="OK", added=append(ledger, recs, frozen_snapshot=frozen_snapshot), checks=checks, blockers=[])
    except (SourceError, KeyError, TypeError, ValueError, OSError, AttributeError) as ex:
        return dict(status="BLOCKED", added=0, checks=None, blockers=[str(ex)])
