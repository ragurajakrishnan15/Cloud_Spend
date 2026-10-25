from datetime import date

import pandas as pd
import pytest

from cloudspend.analytics.local_views import build_budget_variance, build_daily
from cloudspend.analytics.spend_metrics import (
    Filters,
    apply_filters,
    breakdown,
    budget_kpis,
    complete_months,
    period_kpis,
    previous_period,
    safe_pct,
    top_contributors,
    trend,
    variance_by,
    whole_months_in_range,
)


def make_daily(start="2025-01-01", end="2025-03-31"):
    """Every day Jan-Mar 2025: Eng/Compute prod = 10/day, Eng/Storage dev = 2/day, Ops/Compute prod = 5/day."""
    days = pd.date_range(start, end)
    rows = []
    for d in days:
        rows += [
            (d, "Eng", "Compute", "production", "us", 10.0),
            (d, "Eng", "Storage", "development", "us", 2.0),
            (d, "Ops", "Compute", "production", "eu", 5.0),
        ]
    return pd.DataFrame(rows, columns=[
        "usage_date", "department_name", "service_name", "environment_name", "region_name", "total_cost"])


@pytest.fixture()
def daily():
    return make_daily()


def test_safe_pct_handles_zero_and_missing():
    assert safe_pct(5, 10) == 0.5
    assert safe_pct(5, 0) is None
    assert safe_pct(5, None) is None
    assert safe_pct(None, 5) is None
    assert safe_pct(float("nan"), 5) is None


def test_previous_period_is_equal_length_and_adjacent_for_arbitrary_ranges():
    assert previous_period(date(2025, 2, 3), date(2025, 2, 16)) == (date(2025, 1, 20), date(2025, 2, 2))
    assert previous_period(date(2025, 1, 10), date(2025, 1, 10)) == (date(2025, 1, 9), date(2025, 1, 9))


def test_previous_period_for_whole_months_is_previous_whole_months():
    assert previous_period(date(2025, 2, 1), date(2025, 2, 28)) == (date(2025, 1, 1), date(2025, 1, 31))
    assert previous_period(date(2025, 4, 1), date(2025, 6, 30)) == (date(2025, 1, 1), date(2025, 3, 31))  # quarter
    assert previous_period(date(2025, 1, 1), date(2025, 1, 31)) == (date(2024, 12, 1), date(2024, 12, 31))


def test_filters_reject_inverted_range():
    with pytest.raises(ValueError):
        Filters(date(2025, 2, 1), date(2025, 1, 1))


def test_apply_filters(daily):
    f = Filters(date(2025, 1, 1), date(2025, 1, 10), departments=("Eng",), environments=("production",))
    out = apply_filters(daily, f)
    assert len(out) == 10 and out["total_cost"].sum() == 100.0
    ignoring = apply_filters(daily, f, env_region=False)
    assert ignoring["total_cost"].sum() == 120.0  # env filter ignored: Eng prod + dev


def test_period_kpis_basic(daily):
    k = period_kpis(daily, Filters(date(2025, 2, 1), date(2025, 2, 28)))
    assert k["total_cost"] == 17 * 28
    assert k["previous_cost"] == 17 * 31           # the whole of January
    assert k["change_amount"] == -51 and k["change_pct"] == pytest.approx(-51 / 527)


def test_period_kpis_growth(daily):
    daily.loc[pd.to_datetime(daily["usage_date"]) >= "2025-02-01", "total_cost"] *= 2
    k = period_kpis(daily, Filters(date(2025, 2, 1), date(2025, 2, 28)))
    assert k["change_pct"] == pytest.approx((34 * 28 - 17 * 31) / (17 * 31))


def test_period_kpis_previous_outside_data_is_none(daily):
    k = period_kpis(daily, Filters(date(2025, 1, 1), date(2025, 1, 31)))
    assert k["previous_period_covered"] is False
    assert k["previous_cost"] is None and k["change_pct"] is None


def test_period_kpis_zero_previous_gives_none_pct(daily):
    daily.loc[pd.to_datetime(daily["usage_date"]) < "2025-02-01", "total_cost"] = 0.0
    k = period_kpis(daily, Filters(date(2025, 2, 1), date(2025, 2, 28)))
    assert k["change_pct"] is None


def test_complete_months_excludes_partial():
    d = make_daily("2025-01-01", "2025-02-20")
    assert complete_months(d) == {pd.Timestamp("2025-01-01")}


def test_whole_months_in_range(daily):
    cm = complete_months(daily)
    assert whole_months_in_range(date(2025, 1, 1), date(2025, 2, 28), cm) == [
        pd.Timestamp("2025-01-01"), pd.Timestamp("2025-02-01")]
    assert whole_months_in_range(date(2025, 1, 2), date(2025, 2, 28), cm) is None
    assert whole_months_in_range(date(2025, 1, 1), date(2025, 2, 27), cm) is None
    assert whole_months_in_range(date(2025, 3, 1), date(2025, 4, 30), cm) is None  # April not loaded


def make_budgets():
    rows = []
    for m in ("2025-01-01", "2025-02-01", "2025-03-01"):
        rows += [(m, "Eng", "Compute", 300.0), (m, "Eng", "Storage", 100.0), (m, "Ops", "Compute", 150.0)]
    return pd.DataFrame(rows, columns=["budget_month", "department", "service_name", "budget_amount"])


def test_budget_kpis_whole_month(daily):
    bv = build_budget_variance(daily, make_budgets())
    k = budget_kpis(daily, bv, Filters(date(2025, 1, 1), date(2025, 1, 31)))
    # actual: 17*31 = 527 ; budget 550
    assert k["available"] and k["actual"] == 527 and k["budget"] == 550
    assert k["variance"] == -23 and k["variance_pct"] == pytest.approx(-23 / 550)


def test_budget_kpis_department_filter_and_env_note(daily):
    bv = build_budget_variance(daily, make_budgets())
    k = budget_kpis(daily, bv, Filters(date(2025, 1, 1), date(2025, 1, 31), departments=("Ops",),
                                       environments=("production",)))
    assert k["budget"] == 150 and k["actual"] == 155 and k["ignores_env_region"] is True


def test_budget_kpis_unavailable_for_partial_range(daily):
    bv = build_budget_variance(daily, make_budgets())
    k = budget_kpis(daily, bv, Filters(date(2025, 1, 5), date(2025, 1, 31)))
    assert k["available"] is False and "whole" in k["reason"]


def test_breakdown_shares_sum_to_one(daily):
    b = breakdown(daily, Filters(date(2025, 1, 1), date(2025, 1, 31)), "department_name")
    assert b["share"].sum() == pytest.approx(1.0)
    assert b.iloc[0]["department_name"] == "Eng"


def test_top_contributors_sorted_by_abs_change(daily):
    mask = (pd.to_datetime(daily["usage_date"]) >= "2025-02-01") & (daily["department_name"] == "Eng")
    daily.loc[mask & (daily["service_name"] == "Compute"), "total_cost"] = 20.0   # +10/day
    daily.loc[mask & (daily["service_name"] == "Storage"), "total_cost"] = 1.0    # -1/day
    out = top_contributors(daily, Filters(date(2025, 2, 1), date(2025, 2, 28)), "service_name")
    # Compute: Feb = (20 + 5) * 28 = 700 ; Jan = (10 + 5) * 31 = 465
    assert out.iloc[0]["service_name"] == "Compute" and out.iloc[0]["change_amount"] == 700 - 465


def test_trend_monthly_flags_partial_month():
    d = make_daily("2025-01-01", "2025-02-20")
    t = trend(d, Filters(date(2025, 1, 1), date(2025, 2, 20)), "monthly")
    assert list(t["is_partial"]) == [False, True]
    assert t["total_cost"].tolist() == [17 * 31, 17 * 20]


def test_trend_daily_rolling_needs_seven_days(daily):
    t = trend(daily, Filters(date(2025, 1, 1), date(2025, 1, 10)), "daily")
    assert t["rolling_7d"].isna().sum() == 6 and t["rolling_7d"].iloc[-1] == 17
    with pytest.raises(ValueError):
        trend(daily, Filters(date(2025, 1, 1), date(2025, 1, 10)), "weekly")


def test_variance_by_recomputes_pct_not_averages(daily):
    bv = build_budget_variance(daily, make_budgets())
    v = variance_by(bv[bv["month_start"] == "2025-01-01"], ["department_name"])
    eng = v[v["department_name"] == "Eng"].iloc[0]
    assert eng["actual_cost"] == 12 * 31 and eng["budget_amount"] == 400
    assert eng["variance_pct"] == pytest.approx((12 * 31 - 400) / 400)


def test_variance_by_zero_budget_gives_none():
    bv = pd.DataFrame({"department_name": ["X"], "actual_cost": [10.0], "budget_amount": [0.0]})
    assert variance_by(bv, ["department_name"]).iloc[0]["variance_pct"] is None


def test_local_budget_variance_keeps_unbudgeted_and_unspent(daily):
    b = make_budgets()
    b = pd.concat([b, pd.DataFrame([("2025-01-01", "Ghost", "Compute", 50.0)], columns=b.columns)])
    bv = build_budget_variance(daily, b)
    ghost = bv[bv["department_name"] == "Ghost"].iloc[0]
    assert ghost["actual_cost"] == 0 and ghost["budget_amount"] == 50 and not ghost["is_over_budget"]
    assert bv["actual_cost"].sum() == pytest.approx(daily["total_cost"].sum())


def test_build_daily_aggregates_resources():
    billing = pd.DataFrame({
        "record_id": ["a", "b"], "usage_date": ["2025-01-01"] * 2, "department": ["Eng"] * 2,
        "service_name": ["Compute"] * 2, "environment": ["production"] * 2, "region": ["us"] * 2,
        "total_cost": [1.5, 2.5], "usage_units": [10.0, 20.0]})
    d = build_daily(billing)
    assert len(d) == 1 and d.iloc[0]["total_cost"] == 4.0 and d.iloc[0]["record_count"] == 2
