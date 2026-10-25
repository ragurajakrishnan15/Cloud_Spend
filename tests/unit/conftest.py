"""Shared fixtures: a tiny hand-checkable dataset for the AI analyst tests.

Jan-Mar 2025, every day. Daily cost: Eng/Compute prod 10, Eng/Storage dev 2, Ops/Compute prod 5 (17/day).
Jan = 527, Feb = 476, Mar = 527. Monthly budgets: Eng/Compute 300, Eng/Storage 50, Ops/Compute 150 (=500/month).
"""

import json

import pandas as pd
import pytest

from cloudspend.ai.tools import DataBundle
from cloudspend.analytics.local_views import build_budget_variance


def _daily() -> pd.DataFrame:
    rows = []
    for d in pd.date_range("2025-01-01", "2025-03-31"):
        rows += [
            (d, "Eng", "Compute", "production", "us", 10.0, 10.0),
            (d, "Eng", "Storage", "development", "us", 2.0, 2.0),
            (d, "Ops", "Compute", "production", "eu", 5.0, 5.0),
        ]
    return pd.DataFrame(rows, columns=["usage_date", "department_name", "service_name", "environment_name",
                                       "region_name", "total_cost", "usage_units"])


def _budgets() -> pd.DataFrame:
    rows = []
    for m in ("2025-01-01", "2025-02-01", "2025-03-01"):
        rows += [(m, "Eng", "Compute", 300.0), (m, "Eng", "Storage", 50.0), (m, "Ops", "Compute", 150.0)]
    return pd.DataFrame(rows, columns=["budget_month", "department", "service_name", "budget_amount"])


def _anomalies() -> pd.DataFrame:
    base = dict(method_version="v1", environment_name="production", region_name="us", severity="high")
    rows = [
        dict(record_id="a1", usage_date="2025-02-10", department_name="Eng", service_name="Compute", resource_id="res-0001",
             detection_method="rolling_median_mad", observed_cost=40.0, baseline_cost=10.0, abs_diff=30.0, pct_diff=3.0,
             anomaly_score=20.0, reason="spike", **base),
        dict(record_id="a1", usage_date="2025-02-10", department_name="Eng", service_name="Compute", resource_id="res-0001",
             detection_method="isolation_forest", observed_cost=40.0, baseline_cost=10.0, abs_diff=30.0, pct_diff=3.0,
             anomaly_score=0.7, reason="spike", **base),
        dict(record_id="a2", usage_date="2025-02-20", department_name="Ops", service_name="Compute", resource_id="res-0002",
             detection_method="rolling_median_mad", observed_cost=20.0, baseline_cost=5.0, abs_diff=15.0, pct_diff=3.0,
             anomaly_score=15.0, reason="spike", **base),
    ]
    return pd.DataFrame(rows)


def _forecast() -> pd.DataFrame:
    rows = []
    for model, lo in (("ets_damped_additive_weekly", True), ("seasonal_naive_7d", False)):
        for d in pd.date_range("2025-04-01", "2025-04-30"):
            rows.append(dict(model_name=model, model_version="v1", scope_type="total", scope_value="total",
                             forecast_date=d, forecast_cost=17.0, lower_bound=15.0 if lo else None,
                             upper_bound=19.0 if lo else None, trained_through_date="2025-03-31"))
    return pd.DataFrame(rows)


def _recs() -> pd.DataFrame:
    return pd.DataFrame([
        dict(recommendation_id="rec-1", rule_name="repeated_budget_overrun", rule_version="v1", department_name="Eng",
             service_name="Compute", period_start="2025-01-01", period_end="2025-03-31",
             evidence=json.dumps({"months_over_budget": 3, "total_overrun": 120.5, "avg_overrun_pct": 8.0}),
             suggested_action="Review the budget.", estimated_savings=None, savings_formula=None, confidence="High",
             review_status="NEW", estimated_savings_display="Requires investigation"),
        dict(recommendation_id="rec-2", rule_name="repeated_anomalies", rule_version="v1", department_name="Ops",
             service_name="Compute", period_start="2025-01-01", period_end="2025-03-31",
             evidence=json.dumps({"flagged_records": 4, "excess_over_baseline": 200.0}),
             suggested_action="Investigate the flagged days.", estimated_savings=200.0,
             savings_formula="Upper bound: sum of excess.", confidence="Low", review_status="NEW",
             estimated_savings_display="200.00"),
    ])


def _evaluation() -> pd.DataFrame:
    def row(family, model, scope, metric, value):
        return dict(run_id="t", model_family=family, model_name=model, model_version="v1", scope=scope,
                    metric_name=metric, metric_value=value, parameters="{}", created_at="2025-01-01")
    return pd.DataFrame([
        row("anomaly", "rolling_median_mad", "holdout", "f1", 0.76),
        row("forecast", "ets_damped_additive_weekly", "total", "wape", 0.025),
        row("forecast", "ets_damped_additive_weekly", "total", "interval_coverage", 0.87),
        row("forecast", "seasonal_naive_7d", "total", "wape", 0.028),
    ])


@pytest.fixture()
def bundle() -> DataBundle:
    daily = _daily()
    return DataBundle(daily, build_budget_variance(daily, _budgets()), _anomalies(), _forecast(), _recs(), _evaluation())


@pytest.fixture()
def bare_bundle() -> DataBundle:
    """Only spend and budgets; no model outputs (the 'not computed yet' state)."""
    daily = _daily()
    return DataBundle(daily, build_budget_variance(daily, _budgets()))
