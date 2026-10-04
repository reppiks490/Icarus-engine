# CL (Claude, Anthropic) — 2026-10-04 — cl_lab.watch: federation and automation health monitor with issue alerting
"""python -m cl_lab.watch --out automation_intelligence/cl_lab/federation_health.json [--issue]

Reads current state only (never repairs, never relaxes a check):
  * latest completed run on main of the canonical gate (Icarus live-engine-federation-gate)
    and of this repo's brain-federation-contract and tests workflows;
  * peer packet age (automation_intelligence/interrepo/latest.json) vs the 1800 s window;
  * custom-agent events missing contract.json required fields (minus exact legacy blobs);
  * scheduled-run delivery over 24 h for this repo's frequent crons (GitHub throttling).
With --issue it opens one "[CL] Federation health" issue when RED, updates it when the
reasons change, and closes it when GREEN. Writes the JSON only when the verdict changes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
ENGINE = "reppiks490/Icarus-engine"
CANON = "reppiks490/Icarus"
ISSUE_TITLE = "[CL] Federation health"
PEER = "automation_intelligence/interrepo/latest.json"
EVENTS = "automation_intelligence/mcp_interface/events"
FRESH_S = 1800


def _api(path, token=None, method="GET", body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "icarus-cl-watch",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def latest_main_run(repo, workflow, token=None):
    for tok in (token, None):
        try:
            d = _api(f"/repos/{repo}/actions/workflows/{workflow}/runs?branch=main&status=completed&per_page=1", tok)
            r = (d.get("workflow_runs") or [None])[0]
            return None if r is None else dict(conclusion=r["conclusion"], at=r["created_at"], url=r["html_url"],
                                               event=r["event"], sha=r["head_sha"][:7])
        except urllib.error.HTTPError:
            continue
    return None


def scheduled_runs_24h(repo, workflow, token=None):
    since = datetime.now(timezone.utc).timestamp() - 86400
    stamp = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        d = _api(f"/repos/{repo}/actions/workflows/{workflow}/runs?event=schedule&created=>{stamp}&per_page=1", token)
        return int(d.get("total_count", 0))
    except urllib.error.HTTPError:
        return None


def packet_age(root, now):
    try:
        d = json.load(open(os.path.join(root, PEER), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for k in ("observed_at", "generated_at", "exported_at", "at_utc"):
        if isinstance(d.get(k), str):
            t = datetime.fromisoformat(d[k].replace("Z", "+00:00"))
            return round((now - t).total_seconds(), 1)
    return None


def malformed_events(root):
    try:
        producer = json.load(open(os.path.join(root, "automation_intelligence/mcp_interface/contract.json")))
        consumer = json.load(open(os.path.join(root, "automation_intelligence/mcp_interface/icarus_consumer_contract.json")))
    except (OSError, ValueError):
        return ["contract unreadable"]
    req = set(producer.get("required_fields") or [])
    legacy = {s.lower() for s in consumer.get("event_validation", {}).get("legacy_relaxed_blob_shas", [])}
    bad = []
    d = os.path.join(root, EVENTS)
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".json"):
            continue
        p = os.path.join(d, name)
        raw = open(p, "rb").read()
        blob = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()
        try:
            ev = json.loads(raw)
        except ValueError:
            bad.append(f"{name}: invalid JSON")
            continue
        if str(ev.get("source") or "").upper() not in set(consumer.get("accepted_sources", [])):
            continue
        missing = sorted(req - set(ev))
        if missing and blob not in legacy:
            bad.append(f"{name}: missing {','.join(missing)}")
    return bad


def assess(state):
    reasons = []
    for key in ("canonical_gate", "engine_event_contract", "engine_tests"):
        r = state.get(key)
        if r is None:
            reasons.append(f"{key}: no completed run on main visible")
        elif r["conclusion"] != "success":
            reasons.append(f"{key}: {r['conclusion']} ({r['at']}, {r['sha']})")
    age = state.get("peer_packet_age_s")
    if age is None or age > FRESH_S:
        reasons.append(f"peer packet age {age} s exceeds {FRESH_S} s")
    if state.get("malformed_events"):
        reasons.append(f"{len(state['malformed_events'])} malformed custom-agent event(s)")
    hard = [r for r in reasons if not r.startswith("peer packet")]
    verdict = "GREEN" if not reasons else ("RED" if hard else "DEGRADED")
    return verdict, reasons


def collect(root=".", token=None, now=None):
    now = now or datetime.now(timezone.utc)
    st = dict(checked_at=now.isoformat(), lane="CL",
              canonical_gate=latest_main_run(CANON, "live-engine-federation-gate.yml", token),
              engine_event_contract=latest_main_run(ENGINE, "brain-federation-contract.yml", token),
              engine_tests=latest_main_run(ENGINE, "tests.yml", token),
              peer_packet_age_s=packet_age(root, now), malformed_events=malformed_events(root),
              scheduled_runs_24h={w: scheduled_runs_24h(ENGINE, f"{w}.yml", token)
                                  for w in ("interrepo-peer-intelligence", "restored-five-durability-watchdog")},
              execution_authorized=False)
    st["verdict"], st["reasons"] = assess(st)
    return st


def sync_issue(st, repo, token):
    issues = _api(f"/repos/{repo}/issues?state=open&per_page=100", token) or []
    mine = [i for i in issues if i.get("title") == ISSUE_TITLE and "pull_request" not in i]
    body = (f"Verdict: **{st['verdict']}** (checked {st['checked_at']}, CL monitor)\n\n" +
            "\n".join(f"- {r}" for r in st["reasons"]) +
            "\n\nResearch-only monitor: it reports, it never relaxes a check. Closes itself when GREEN.")
    if st["verdict"] == "GREEN":
        for i in mine:
            _api(f"/repos/{repo}/issues/{i['number']}/comments", token, "POST", {"body": "GREEN again — closing."})
            _api(f"/repos/{repo}/issues/{i['number']}", token, "PATCH", {"state": "closed"})
        return "closed" if mine else "none"
    if mine:
        _api(f"/repos/{repo}/issues/{mine[0]['number']}", token, "PATCH", {"body": body})
        return "updated"
    _api(f"/repos/{repo}/issues", token, "POST", {"title": ISSUE_TITLE, "body": body})
    return "opened"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="automation_intelligence/cl_lab/federation_health.json")
    ap.add_argument("--root", default=".")
    ap.add_argument("--issue", action="store_true")
    a = ap.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    st = collect(a.root, token)
    prev = {}
    if os.path.exists(a.out):
        try:
            prev = json.load(open(a.out, encoding="utf-8"))
        except ValueError:
            prev = {}
    changed = (prev.get("verdict"), prev.get("reasons")) != (st["verdict"], st["reasons"])
    if changed:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=1, sort_keys=True)
            f.write("\n")
    if a.issue and token and changed:
        st["issue"] = sync_issue(st, ENGINE, token)
    print(json.dumps(dict(verdict=st["verdict"], reasons=st["reasons"], changed=changed, issue=st.get("issue"))))


if __name__ == "__main__":
    main()
