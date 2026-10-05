# ChatGPT — 2026-10-04 — tests for dual-credential Databento depth planning
import pandas as pd

from cl_lab.feeds import databento as dbfeed
from cl_lab.feeds import databento_depth_plan as depth


class _Meta:
    def __init__(self):
        self.calls = []

    def get_cost(self, **kwargs):
        self.calls.append(kwargs)
        schema_mult = 3.0 if kwargs["schema"] == "mbo" else 1.0
        days = max(1, (pd.Timestamp(kwargs["end"]) - pd.Timestamp(kwargs["start"])).days)
        return 0.10 * schema_mult * days


class _History:
    def __init__(self):
        self.metadata = _Meta()


def test_secondary_key_selection_is_isolated(monkeypatch):
    monkeypatch.setenv("DATABENTO_API_KEY", "primary-test")
    monkeypatch.setenv("DATABENTO_API_KEY_SECONDARY", "secondary-test")
    assert dbfeed.api_key_env("primary") == "DATABENTO_API_KEY"
    assert dbfeed.api_key_env("secondary") == "DATABENTO_API_KEY_SECONDARY"
    assert dbfeed.account_configured("primary")
    assert dbfeed.account_configured("secondary")


def test_depth_planner_estimates_only_and_never_downloads():
    hist = _History()
    plan = depth.estimate_depth_costs(
        roots=("NQ", "ES"),
        schemas=("mbo", "mbp-10"),
        lookback_days=(1, 5),
        now="2026-10-04T20:00:00Z",
        account="secondary",
        client=hist,
    )
    assert plan["status"] == "ok"
    assert plan["account"] == "secondary"
    assert len(plan["estimates"]) == 8
    assert len(hist.metadata.calls) == 8
    assert all(r["request_performed"] is False for r in plan["estimates"])
    assert {c["schema"] for c in hist.metadata.calls} == {"mbo", "mbp-10"}
    assert all(c["stype_in"] == "continuous" for c in hist.metadata.calls)


def test_depth_budget_frontier_is_deterministic_and_nonspending():
    plan = {
        "estimates": [
            dict(status="ok", root="NQ", schema="mbo", lookback_days=20,
                 estimated_cost_usd=8.0, priority_weight=1.0),
            dict(status="ok", root="ES", schema="mbo", lookback_days=20,
                 estimated_cost_usd=4.0, priority_weight=0.92),
            dict(status="ok", root="GC", schema="mbo", lookback_days=20,
                 estimated_cost_usd=5.0, priority_weight=0.84),
        ]
    }
    front = depth.budget_frontier(plan, 9.0, "mbo", 20)
    assert front["planned_estimated_spend_usd"] <= 9.0
    assert front["spend_authorized"] is False
    assert front["execution_authorized"] is False
    assert [r["root"] for r in front["selected"]] == ["ES", "GC"]
