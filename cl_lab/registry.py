# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.registry: champion registry with frozen specs and status history
"""A rule is registered the first time it reaches CANDIDATE or better; its spec
(grammar version + params, hence its id) is frozen from then on. Status changes
append to status_history; entries are never deleted. Forward evidence for a
rule only counts sessions dated after first_registered_at."""
from __future__ import annotations

PROMOTABLE = ("CANDIDATE", "CHALLENGER", "CHAMPION")


def merge(registry: dict, asset: str, records: dict, run_id: str, at: str, grammar: str) -> dict:
    reg = registry or {"schema": "cl_lab.registry/1", "entries": {}}
    ents = reg.setdefault("entries", {})
    for rid, r in records.items():
        key = f"{asset}:{rid}"
        e = ents.get(key)
        if e is None and r["status"] not in PROMOTABLE:
            continue
        if e is None:
            e = ents[key] = dict(asset=asset, id=rid, family=r["family"], params=r["params"], grammar=grammar,
                                 first_registered_at=at, first_run_id=run_id, status=None, status_history=[])
        if e["status"] != r["status"]:
            e["status_history"].append(dict(run_id=run_id, at=at, status=r["status"]))
            e["status"] = r["status"]
        e["last_run_id"] = run_id
        e["last_metrics"] = {k: r.get(k) for k in ("tune_trades", "tune_t", "dsr", "hold_t", "hold_holm_p",
                                                     "hold_mean", "hold_mean_stress", "quarters_positive",
                                                     "neighbours_positive", "forward")}
    reg["updated_at"] = at
    reg["execution_authorized"] = False
    reg["production_decision_authorized"] = False
    return reg
