"""S1 data-health sentinel: one verdict per data source, read from the files the collectors already write.

Nothing here calls a vendor. It reads the receipts, manifests and spend ledgers in the repository, plus
(when a GitHub token is available) the latest run of every workflow, and writes:

- ``automation_intelligence/sentinel/data_health.json``: machine-readable, one entry per source;
- ``automation_intelligence/sentinel/DATA_HEALTH.md``: the phone-readable version.

Verdicts: ``OK`` (delivering), ``DEGRADED`` (delivering with denials or partial coverage), ``BLOCKED``
(missing key or every request refused), ``STALE`` (last success older than its expected cadence),
``FAILING`` (its workflow's latest run failed). Each entry says why, so a reader never has to open the
receipt to learn what is wrong.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from tools import coordination

AI = Path("automation_intelligence")
OUT = AI / "sentinel"

# Workflows whose latest conclusion is part of the verdict, and how stale (hours) a success may get.
WORKFLOWS = {
    "provider-exhaustive-collection.yml": 3,
    "provider-supplemental-collection.yml": 3,
    "provider-supplemental-promote.yml": 3,
    "native-provider-access.yml": 8,
    "external-data-fabric.yml": 80,          # weekdays only
    "cl-lab.yml": 14,
    "databento-depth-corpus.yml": 26,
    "cl-depth-sweep.yml": 26,
    "databento-depth-research-context.yml": 26,
    "depth-vault.yml": 26,
    "sec-edgar-data.yml": 3,
    "official-economic-events.yml": 8,
    "native-five-research.yml": 3,
    "interrepo-peer-intelligence.yml": 1,
    "tests.yml": 9999,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_h(stamp: str | None, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return round((now - t).total_seconds() / 3600, 1)


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _receipt_age_h(stamp, now: datetime) -> float | None:
    """Unrounded age of a timezone-bound receipt; unknown time is not delivery proof."""
    if not isinstance(stamp, str):
        return None
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None:
        return None
    return (now - at).total_seconds() / 3600


def _fabric_rows(provider: dict) -> int:
    """Count known rows in successful dedicated-fabric datasets without double counting."""
    total = 0
    for dataset in (provider.get("datasets") or {}).values():
        if not isinstance(dataset, dict) or dataset.get("status") not in {"ok", "partial"}:
            continue
        count = dataset.get("rows")
        if isinstance(count, int) and not isinstance(count, bool):
            total += max(0, count)
            if count > 0:
                continue
        symbols = dataset.get("symbols")
        if isinstance(symbols, dict):
            for item in symbols.values():
                if not isinstance(item, dict):
                    continue
                rows = item.get("rows", item.get("bars", 0))
                if isinstance(rows, int) and not isinstance(rows, bool):
                    total += max(0, rows)
    return total


def providers(root: Path, now: datetime) -> list[dict]:
    out = []
    fabric = _load(root / AI / "cl_lab" / "external_data_fabric.json") or {}
    dedicated = fabric.get("providers") or {}
    dedicated_age = _receipt_age_h(fabric.get("generated_at"), now)
    dedicated_fresh = dedicated_age is not None and 0 <= dedicated_age <= WORKFLOWS["external-data-fabric.yml"]
    for path in sorted((root / AI / "provider_collection_v1" / "latest").glob("*.json")):
        d = _load(path) or {}
        name = path.stem
        p = (d.get("providers") or {}).get(name, {})
        cat = d.get("catalog") or {}
        rows, denied = p.get("collected_rows") or 0, cat.get("denied_operations") or 0
        dedicated_provider = dedicated.get(name) or {}
        dedicated_live = (dedicated_fresh and dedicated_provider.get("status") in {"ok", "partial"}
                          and (dedicated_provider.get("calls") or 0) > 0)
        dedicated_rows = _fabric_rows(dedicated_provider) if dedicated_live else 0
        dedicated_support = bool(p.get("credential_present")) and dedicated_live and (
            p.get("status", "").startswith("BLOCKED") or dedicated_rows > rows)
        # Generic and dedicated collectors can overlap, so expose the larger known
        # lane count rather than summing unlike/possibly duplicated observations.
        if p.get("credential_present"):
            rows = max(rows, dedicated_rows)
        if not p.get("credential_present") and p.get("status") == "NO_READY_JOBS":
            verdict, why = "DEGRADED", "no key; keyless endpoints only, none ready"
        elif not p.get("credential_present"):
            verdict, why = "BLOCKED", "no key reaches the runner"
        elif p.get("status", "").startswith("BLOCKED") and dedicated_live:
            verdict = "DEGRADED"
            why = f"dedicated fabric live ({dedicated_provider.get('calls')} calls, {dedicated_rows} known rows); generic sampler blocked"
            if denied:
                why += f"; {denied} endpoints denied by plan"
        elif p.get("status", "").startswith("BLOCKED"):
            verdict, why = "BLOCKED", p.get("status")
        elif rows == 0:
            verdict, why = "DEGRADED", f"key present but 0 rows ({p.get('status')})"
        elif denied:
            verdict, why = "DEGRADED", f"{rows} rows; {denied} endpoints denied by plan"
        else:
            verdict, why = "OK", f"{rows} rows"
        out.append(dict(source=f"provider:{name}", verdict=verdict, why=why, rows=rows,
                        age_h=round(dedicated_age, 1) if dedicated_support else _age_h(d.get("completed_at_utc"), now),
                        path=str(AI / "cl_lab" / "external_data_fabric.json") if dedicated_support else str(path.relative_to(root))))
    return out


def cl_feeds(root: Path, now: datetime) -> list[dict]:
    d = _load(root / AI / "cl_lab" / "feeds_manifest.json") or {}
    out = []
    for name, f in sorted((d.get("feeds") or {}).items()):
        integ = f.get("integrity") or {}
        ok = f.get("status") == "ok"
        out.append(dict(source=f"feed:{name}", verdict="OK" if ok else "FAILING",
                        why=f"{integ.get('rows', 0)} rows to {str(integ.get('last'))[:16]}" if ok
                        else str(f.get("error") or f.get("status"))[:160],
                        rows=integ.get("rows", 0), age_h=_age_h(integ.get("last"), now)))
    return out


def manifests(root: Path, now: datetime) -> list[dict]:
    out = []
    sec = _load(root / AI / "cl_lab" / "sec_edgar_manifest.json") or {}
    out.append(dict(source="sec_edgar", verdict="BLOCKED" if sec.get("error") else "OK",
                    why=(sec.get("error") or f"{sec.get('filing_rows', 0)} filings")[:200],
                    rows=sec.get("filing_rows", 0), age_h=_age_h(sec.get("generated_at"), now)))
    ev = _load(root / AI / "cl_lab" / "economic_events_manifest.json") or {}
    out.append(dict(source="economic_events", verdict="OK" if ev.get("current_events") else "DEGRADED",
                    why=f"{ev.get('current_events', 0)} events, {ev.get('high_impact_current', 0)} high impact",
                    rows=ev.get("current_events", 0), age_h=_age_h(ev.get("generated_at"), now)))
    fred = _load(root / AI / "cl_lab" / "fred_alfred_manifest.json") or {}
    series = fred.get("series") or {}
    bad = [k for k, v in series.items() if v.get("status") != "ok"]
    out.append(dict(source="fred_alfred", verdict="DEGRADED" if bad else ("OK" if series else "BLOCKED"),
                    why=f"{len(series) - len(bad)}/{len(series)} series ok" + (f"; failing {bad[:5]}" if bad else ""),
                    rows=sum(v.get("rows", 0) for v in series.values()), age_h=_age_h(fred.get("generated_at"), now)))
    return out


def depth(root: Path) -> dict:
    vault = _load(root / "data" / "depth_vault" / "manifest.json") or {"caches": {}}
    files = {k: len(v) for k, v in vault.get("caches", {}).items()}
    budgets = {}
    for path in sorted((root / AI / "cl_lab" / "spend").glob("*.json")):
        d = _load(path) or {}
        cap, spent = float(d.get("cap_usd") or 0), float(d.get("spent_usd") or 0)
        budgets[path.stem] = dict(cap_usd=round(cap, 2), spent_usd=round(spent, 2), left_usd=round(cap - spent, 2))
    d1 = _load(root / AI / "cl_lab" / "depth_d1_latest.json") or {}
    check = _load(root / OUT / "vault_verify.json") or {}
    vault_verify = {
        "verdict": check.get("verdict", "NOT_RUN"),
        "verified_at": check.get("verified_at"),
        "failures": check.get("failure_count", 0),
    }
    return dict(vault_files=files, vault_key_source=vault.get("key_source"), budgets=budgets,
                vault_verify=vault_verify,
                d1={k: (d1.get(k) or {}).get("status") for k in ("D1-A", "D1-B")} | {"days": d1.get("event_days")})


def research(root: Path) -> dict:
    champs = (_load(root / AI / "cl_lab" / "champions.json") or {}).get("entries") or {}
    pulse = _load(root / AI / "cl_lab" / "pulse_latest.json") or {}
    hb = _load(root / AI / "cl_lab" / "heartbeat.json") or {}
    return dict(champions=len(champs), cl_last_run=hb.get("last_completed_at"),
                pulse={k: v.get("status") for k, v in (pulse.get("variants") or {}).items()},
                pulse_forward=pulse.get("forward"))


def workflows(repo: str | None, token: str | None, now: datetime) -> list[dict]:
    if not (repo and token):
        return []
    out = []
    for wf, stale_h in WORKFLOWS.items():
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?branch=main&per_page=5"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                   "Accept": "application/vnd.github+json"})
        try:
            runs = json.load(urllib.request.urlopen(req, timeout=20)).get("workflow_runs", [])
        except Exception as ex:  # noqa: BLE001 - the sentinel reports, it never fails the job
            out.append(dict(source=f"workflow:{wf}", verdict="UNKNOWN", why=f"{type(ex).__name__}"))
            continue
        done = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") != "skipped"]
        if not done:
            out.append(dict(source=f"workflow:{wf}", verdict="UNKNOWN", why="no completed run on main"))
            continue
        last = done[0]
        ok = [r for r in done if r.get("conclusion") == "success"]
        age = _age_h(ok[0]["updated_at"], now) if ok else None
        if last.get("conclusion") != "success":
            verdict, why = "FAILING", f"latest run {last.get('conclusion')}: {last.get('html_url')}"
        elif age is not None and age > stale_h:
            verdict, why = "STALE", f"last success {age} h ago (expected within {stale_h} h)"
        else:
            verdict, why = "OK", f"last success {age} h ago"
        out.append(dict(source=f"workflow:{wf}", verdict=verdict, why=why, age_h=age))
    return out


ORDER = {"FAILING": 0, "BLOCKED": 1, "STALE": 2, "DEGRADED": 3, "UNKNOWN": 4, "OK": 5}


def build(root: Path, repo: str | None = None, token: str | None = None, now: datetime | None = None) -> dict:
    now = now or _now()
    sources = providers(root, now) + cl_feeds(root, now) + manifests(root, now) + workflows(repo, token, now)
    sources.sort(key=lambda s: (ORDER.get(s["verdict"], 9), s["source"]))
    counts: dict[str, int] = {}
    for s in sources:
        counts[s["verdict"]] = counts.get(s["verdict"], 0) + 1
    return dict(schema="icarus.data_health/1", generated_at=now.isoformat(timespec="seconds"),
                counts=counts, sources=sources, depth=depth(root), research=research(root),
                coordination=coordination.summary(root, now), execution_authorized=False)


def markdown(report: dict) -> str:
    c = report["counts"]
    lines = [f"# Data health — {report['generated_at'][:16].replace('T', ' ')} UTC", "",
             " · ".join(f"**{k}** {c[k]}" for k in sorted(c, key=lambda k: ORDER.get(k, 9))), ""]
    problems = [s for s in report["sources"] if s["verdict"] != "OK"]
    if problems:
        lines += ["## Needs attention", "", "| Source | Verdict | Why |", "|---|---|---|"]
        lines += [f"| {s['source']} | {s['verdict']} | {' '.join(str(s['why']).split()).replace('|', '/')} |"
                  for s in problems]
        lines.append("")
    ok = [s["source"] for s in report["sources"] if s["verdict"] == "OK"]
    lines += ["## Delivering", "", ", ".join(ok) or "none", ""]
    d, r = report["depth"], report["research"]
    lines += ["## Order-book data", "",
              f"Vaulted files: {d['vault_files']} (key: {d['vault_key_source']}). "
              f"Last vault decrypt/hash check: {d['vault_verify']['verdict']} at {d['vault_verify']['verified_at']} "
              f"with {d['vault_verify']['failures']} failures. D1 status: {d['d1']}.", "",
              "| Budget | Cap | Spent | Left |", "|---|---|---|---|"]
    lines += [f"| {k} | ${v['cap_usd']} | ${v['spent_usd']} | ${v['left_usd']} |" for k, v in d["budgets"].items()]
    lines += ["", "## Research", "", f"Champions: {r['champions']}. Pulse variants: {r['pulse']}. "
              f"CL lab last run: {r['cl_last_run']}.", ""]
    if report.get("coordination"):
        lines += ["## Coordination (Claude, ChatGPT, Atlas)", "", coordination.markdown(report["coordination"]), ""]
    return "\n".join(lines)


def _fingerprint(report: dict) -> list:
    return [(s["source"], s["verdict"]) for s in report.get("sources", [])] + [
        {s["source"]: s.get("rows", 0) for s in report.get("sources", [])
         if s.get("source", "").startswith("provider:")},
        report.get("depth", {}).get("vault_files"), report.get("research", {}).get("champions"),
        (report.get("depth", {}).get("vault_verify") or {}).get("verdict"),
        (report.get("coordination") or {}).get("awaiting_reply"),
        {k: v.get("counts") for k, v in ((report.get("coordination") or {}).get("boards") or {}).items()}]


def changed(previous: dict | None, report: dict, refresh_h: float = 24.0) -> bool:
    """Rewrite on verdict/provider-row, vault or champion changes, or once daily."""
    if not previous:
        return True
    if _fingerprint(previous) != _fingerprint(report):
        return True
    age = _age_h(previous.get("generated_at"), datetime.fromisoformat(report["generated_at"]))
    return age is None or age >= refresh_h


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("."))
    a = ap.parse_args(argv)
    report = build(a.root, os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN"))
    out = a.root / OUT
    if not changed(_load(out / "data_health.json"), report):
        print("no change in data health")
        return
    out.mkdir(parents=True, exist_ok=True)
    (out / "data_health.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "DATA_HEALTH.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["counts"]))


if __name__ == "__main__":
    main()
