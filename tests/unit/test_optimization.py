import json

import pandas as pd

from cloudspend.analytics.local_views import build_budget_variance
from cloudspend.analytics.optimization import (
    RuleConfig,
    generate_recommendations,
    rule_cost_vs_usage,
    rule_nonprod_weekend,
    rule_persistent_increase,
    rule_repeated_anomalies,
    rule_repeated_overrun,
)

CFG = RuleConfig()


def daily_frame(monthly_cost, dept="Eng", svc="Compute", env="production", usage=None, start="2025-01-01"):
    """One row per day; each month's total equals monthly_cost[i] (usage likewise)."""
    rows = []
    for i, m in enumerate(pd.date_range(start, periods=len(monthly_cost), freq="MS")):
        days = pd.date_range(m, m + pd.offsets.MonthEnd(0))
        for d in days:
            rows.append((d, dept, svc, env, monthly_cost[i] / len(days),
                         (usage[i] if usage else monthly_cost[i]) / len(days)))
    return pd.DataFrame(rows, columns=["usage_date", "department_name", "service_name", "environment_name",
                                       "total_cost", "usage_units"])


def test_persistent_increase_flags_rising_series_only():
    rising = daily_frame([100, 110, 125, 140, 160, 180])
    flat = daily_frame([100, 100, 101, 100, 100, 101], svc="Storage")
    recs = rule_persistent_increase(pd.concat([rising, flat]), CFG)
    assert [(r["service_name"]) for r in recs] == ["Compute"]
    ev = json.loads(recs[0]["evidence"])
    assert ev["consecutive_increasing_months"] == 5 and ev["cumulative_growth_pct"] == 80.0
    assert recs[0]["confidence"] == "Medium" and recs[0]["estimated_savings"] is None


def test_persistent_increase_needs_threshold_and_run():
    slow = daily_frame([100, 101, 102, 103, 104])           # rising but only +4%
    broken = daily_frame([100, 150, 140, 160, 180], svc="B")  # last run is only 2 months
    assert rule_persistent_increase(pd.concat([slow, broken]), CFG) == []


def test_repeated_overrun_counts_only_material_overruns_and_recomputes_totals():
    daily = daily_frame([120] * 6)
    budgets = pd.DataFrame({"budget_month": pd.date_range("2025-01-01", periods=6, freq="MS"),
                            "department": "Eng", "service_name": "Compute",
                            "budget_amount": [100, 100, 100, 100, 118, 118]})
    bv = build_budget_variance(daily.assign(usage_date=daily["usage_date"]), budgets)
    recs = rule_repeated_overrun(bv, daily, CFG)
    assert len(recs) == 1
    ev = json.loads(recs[0]["evidence"])
    assert ev["months_over_budget"] == 4 and ev["total_overrun"] == 80.0   # 4 months x $20; 118 is <5% over


def test_nonprod_weekend_rule_ignores_production_and_scaled_down_nonprod():
    flat_dev = daily_frame([3000, 3000, 3000], env="development")           # weekend == weekday cost
    flat_prod = daily_frame([3000, 3000, 3000], env="production", svc="B")  # production is ignored
    scaled = daily_frame([3000, 3000, 3000], env="development", svc="C")
    scaled.loc[pd.to_datetime(scaled["usage_date"]).dt.dayofweek >= 5, "total_cost"] *= 0.2
    recs = rule_nonprod_weekend(pd.concat([flat_dev, flat_prod, scaled]), CFG)
    assert [r["service_name"] for r in recs] == ["Compute"] and recs[0]["confidence"] == "Low"


def test_cost_vs_usage_divergence():
    diverging = daily_frame([100, 100, 100, 100, 130], usage=[100, 100, 100, 100, 100])
    matching = daily_frame([100, 100, 100, 100, 130], usage=[100, 100, 100, 100, 130], svc="B")
    recs = rule_cost_vs_usage(pd.concat([diverging, matching]), CFG)
    assert [r["service_name"] for r in recs] == ["Compute"]
    assert json.loads(recs[0]["evidence"])["gap_points"] == 30.0


def anomalies_frame(n, dept="Eng", svc="Compute", base_date="2025-12-01"):
    return pd.DataFrame({
        "record_id": [f"r{i}" for i in range(n)], "usage_date": pd.date_range(base_date, periods=n),
        "department_name": dept, "service_name": svc, "observed_cost": 150.0, "baseline_cost": 100.0,
        "detection_method": "rolling_median_mad"})


def test_repeated_anomalies_savings_is_supported_upper_bound():
    recs = rule_repeated_anomalies(anomalies_frame(4), pd.Timestamp("2025-12-30"), CFG)
    assert len(recs) == 1 and recs[0]["estimated_savings"] == 200.0 and "Upper bound" in recs[0]["savings_formula"]
    assert rule_repeated_anomalies(anomalies_frame(2), pd.Timestamp("2025-12-30"), CFG) == []


def test_repeated_anomalies_dedupes_records_flagged_by_both_methods():
    a = anomalies_frame(3)
    b = a.assign(detection_method="isolation_forest")
    recs = rule_repeated_anomalies(pd.concat([a, b]), pd.Timestamp("2025-12-30"), CFG)
    ev = json.loads(recs[0]["evidence"])
    assert ev["flagged_records"] == 3 and ev["flagged_by_both_methods"] == 3 and recs[0]["estimated_savings"] == 150.0


def test_generate_is_deterministic_with_stable_ids_and_new_status():
    daily = daily_frame([100, 110, 125, 140, 160, 180])
    bv = build_budget_variance(daily, pd.DataFrame(columns=["budget_month", "department", "service_name", "budget_amount"]))
    empty = anomalies_frame(0)
    r1 = generate_recommendations(daily, bv, empty)
    r2 = generate_recommendations(daily, bv, empty)
    assert r1["recommendation_id"].tolist() == r2["recommendation_id"].tolist() and not r1.empty
    assert (r1["review_status"] == "NEW").all() and r1["recommendation_id"].is_unique
