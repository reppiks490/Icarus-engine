# ChatGPT — 2026-10-04 — Databento depth-data cost planner for CL Lab
"""Preflight MBO/MBP-10 costs without downloading vendor depth data.

The planner deliberately performs metadata.get_cost() calls only. It never calls
historical timeseries.get_range(), so running it cannot consume historical data
credits beyond any provider policy for metadata requests.

Environment:
- DATABENTO_API_KEY_SECONDARY: secondary Databento credential used by default.
- DATABENTO_API_KEY_THIRD: optional third isolated Databento credential.
- DATABENTO_DEPTH_ACCOUNT: primary|secondary|third (default secondary).
- DATABENTO_DATASET: must remain GLBX.MDP3.
- DATABENTO_ROLL_RULE: v, n, or c (default v).
- CL_DATABENTO_HISTORICAL_LAG_MINUTES: historical watermark safety lag
  (default 500 minutes).

The output is a research-planning artifact, not a trading signal and not an
authorization to execute or spend.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Iterable

import pandas as pd

from . import databento as dbfeed

DEFAULT_ROOTS = (
    "NQ", "MNQ", "ES", "MES", "YM", "MYM", "RTY", "M2K",
    "GC", "MGC", "SI", "SIL", "PL", "PA", "BTC", "MBT",
)
DEFAULT_SCHEMAS = ("mbo", "mbp-10")
DEFAULT_LOOKBACK_DAYS = (1, 5, 20)

# Research-priority weights are explicit heuristics for ICARUS corpus planning,
# not expected-return forecasts. They favor the user's core NQ/MNQ stack, then
# closely related index/metals markets.
PRIORITY = {
    "NQ": 1.00, "MNQ": 0.98, "ES": 0.92, "MES": 0.90,
    "GC": 0.84, "MGC": 0.82, "RTY": 0.72, "M2K": 0.70,
    "YM": 0.66, "MYM": 0.64, "SI": 0.62, "SIL": 0.60,
    "BTC": 0.58, "MBT": 0.56, "PL": 0.46, "PA": 0.44,
}


def _normalize_account(account: str | None) -> str:
    value = (account or os.environ.get("DATABENTO_DEPTH_ACCOUNT") or "secondary").strip().lower()
    if value not in ("primary", "secondary", "third"):
        raise ValueError("DATABENTO_DEPTH_ACCOUNT must be primary, secondary, or third")
    return value


def _client(account: str, client: Any = None) -> Any:
    if client is not None:
        return client
    return dbfeed.historical_client(account=account)


def estimate_depth_costs(
    *,
    roots: Iterable[str] = DEFAULT_ROOTS,
    schemas: Iterable[str] = DEFAULT_SCHEMAS,
    lookback_days: Iterable[int] = DEFAULT_LOOKBACK_DAYS,
    now: pd.Timestamp | str | None = None,
    account: str | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Estimate MBO/MBP-10 costs for standard lookbacks; never download data."""
    account = _normalize_account(account)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    try:
        lag_minutes = int(os.environ.get("CL_DATABENTO_HISTORICAL_LAG_MINUTES") or "500")
    except ValueError as ex:
        raise ValueError("CL_DATABENTO_HISTORICAL_LAG_MINUTES must be an integer") from ex
    if lag_minutes < 0:
        raise ValueError("CL_DATABENTO_HISTORICAL_LAG_MINUTES must be >= 0")
    # Only price complete UTC days that are safely behind the historical
    # availability watermark. This also makes eventual downloads replayable.
    end = (now - pd.Timedelta(minutes=lag_minutes)).floor("D")
    dataset = (os.environ.get("DATABENTO_DATASET") or dbfeed.DATASET).strip()
    if dataset != dbfeed.DATASET:
        raise ValueError(f"depth planner requires {dbfeed.DATASET}, got {dataset!r}")

    if not dbfeed.account_configured(account) and client is None:
        return {
            "schema": "cl_lab.databento_depth_costs/1",
            "status": "unconfigured",
            "generated_at": now.isoformat(),
            "account": account,
            "dataset": dataset,
            "execution_authorized": False,
            "production_decision_authorized": False,
            "estimates": [],
            "error": f"{dbfeed.api_key_env(account)} not configured",
        }

    hist = _client(account, client)
    estimates: list[dict[str, Any]] = []
    for root0 in roots:
        root = str(root0).strip().upper()
        symbol = dbfeed.continuous_symbol(root)
        for schema0 in schemas:
            schema = str(schema0).strip().lower()
            if schema not in ("mbo", "mbp-10"):
                raise ValueError(f"unsupported depth schema {schema!r}")
            for days0 in lookback_days:
                days = int(days0)
                if days <= 0:
                    raise ValueError("lookback days must be positive")
                start = end - pd.Timedelta(days=days)
                kwargs = dict(
                    dataset=dataset,
                    symbols=symbol,
                    schema=schema,
                    stype_in="continuous",
                    start=start.isoformat(),
                    end=end.isoformat(),
                )
                row = {
                    "root": root,
                    "symbol": symbol,
                    "schema": schema,
                    "lookback_days": days,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "priority_weight": PRIORITY.get(root, 0.50),
                    "request_performed": False,
                }
                try:
                    cost = float(hist.metadata.get_cost(**kwargs))
                    row["estimated_cost_usd"] = cost
                    row["estimated_cost_per_calendar_day_usd"] = cost / days
                    row["priority_days_per_usd"] = (
                        PRIORITY.get(root, 0.50) * days / cost if cost > 0 else None
                    )
                    row["status"] = "ok"
                except Exception as ex:
                    row["status"] = "error"
                    row["error"] = f"{type(ex).__name__}: {ex}"
                estimates.append(row)

    ok = [r for r in estimates if r.get("status") == "ok"]
    return {
        "schema": "cl_lab.databento_depth_costs/1",
        "status": "ok" if ok else "error",
        "generated_at": now.isoformat(),
        "account": account,
        "dataset": dataset,
        "roll_rule": (os.environ.get("DATABENTO_ROLL_RULE") or "v").strip().lower(),
        "historical_lag_minutes": lag_minutes,
        "execution_authorized": False,
        "production_decision_authorized": False,
        "estimates": estimates,
    }


def budget_frontier(plan: dict[str, Any], budget_usd: float, schema: str = "mbo", horizon_days: int = 20) -> dict[str, Any]:
    """Produce a deterministic information-density shortlist from cost estimates.

    This does not spend or download. The shortlist is based on explicit ICARUS
    research-priority weights divided by estimated cost, then greedily packs
    whole horizon requests inside the supplied planning budget.
    """
    budget = float(budget_usd)
    if budget < 0:
        raise ValueError("budget_usd must be >= 0")
    candidates = [
        dict(r)
        for r in plan.get("estimates", [])
        if r.get("status") == "ok"
        and r.get("schema") == schema
        and int(r.get("lookback_days", -1)) == int(horizon_days)
    ]
    candidates.sort(
        key=lambda r: (
            -(float(r.get("priority_weight", 0.0)) / max(float(r.get("estimated_cost_usd", 0.0)), 1e-12)),
            -float(r.get("priority_weight", 0.0)),
            r.get("root", ""),
        )
    )
    selected, spent = [], 0.0
    for row in candidates:
        cost = float(row["estimated_cost_usd"])
        if spent + cost <= budget + 1e-12:
            selected.append(row)
            spent += cost
    return {
        "schema": "cl_lab.databento_depth_budget_frontier/1",
        "depth_schema": schema,
        "horizon_days": int(horizon_days),
        "budget_usd": budget,
        "planned_estimated_spend_usd": spent,
        "remaining_budget_usd": max(0.0, budget - spent),
        "selected": selected,
        "selection_basis": "explicit ICARUS research-priority weight / estimated request cost",
        "spend_authorized": False,
        "execution_authorized": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--account", default=os.environ.get("DATABENTO_DEPTH_ACCOUNT") or "secondary")
    ap.add_argument("--budget-usd", type=float, default=125.0)
    ap.add_argument("--horizon-days", type=int, default=20)
    ap.add_argument("--roots", default=",".join(DEFAULT_ROOTS))
    a = ap.parse_args(argv)
    roots = tuple(x.strip().upper() for x in a.roots.split(",") if x.strip())
    plan = estimate_depth_costs(roots=roots, account=a.account)
    plan["mbo_budget_frontier"] = budget_frontier(plan, a.budget_usd, "mbo", a.horizon_days)
    plan["mbp10_budget_frontier"] = budget_frontier(plan, a.budget_usd, "mbp-10", a.horizon_days)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=1, sort_keys=True)
        f.write("\n")
    print(json.dumps({
        "status": plan["status"],
        "account": plan["account"],
        "estimates": len(plan["estimates"]),
        "mbo_selected": len(plan["mbo_budget_frontier"]["selected"]),
        "mbo_estimated_spend_usd": plan["mbo_budget_frontier"]["planned_estimated_spend_usd"],
    }))


if __name__ == "__main__":
    main()
