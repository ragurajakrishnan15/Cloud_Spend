from datetime import date

import pytest

from cloudspend.ai.tools import TOOLS, ToolParams, call_tool
from cloudspend.ai.validation import MAX_TOP_N, ValidationError, validate_params

FEB = ToolParams(date(2025, 2, 1), date(2025, 2, 28))


# ----------------------------------------------------------------------------- validation
def test_unknown_department_is_rejected_with_valid_values(bundle):
    with pytest.raises(ValidationError, match="Unknown department 'Sales'.*Eng, Ops"):
        validate_params(ToolParams(date(2025, 2, 1), date(2025, 2, 28), departments=("Sales",)), bundle)


def test_names_are_canonicalised_case_insensitively(bundle):
    p, _ = validate_params(ToolParams(date(2025, 2, 1), date(2025, 2, 28), departments=("eng",), regions=("US",)), bundle)
    assert p.departments == ("Eng",) and p.regions == ("us",)


def test_period_is_clipped_to_data_with_note(bundle):
    p, notes = validate_params(ToolParams(date(2025, 3, 1), date(2025, 4, 30)), bundle)
    assert p.end == date(2025, 3, 31) and notes and "clipped" in notes[0]


def test_period_outside_data_and_inverted_range_are_rejected(bundle):
    with pytest.raises(ValidationError, match="outside"):
        validate_params(ToolParams(date(2024, 1, 1), date(2024, 2, 1)), bundle)
    with pytest.raises(ValidationError, match="after"):
        validate_params(ToolParams(date(2025, 3, 1), date(2025, 2, 1)), bundle)
    with pytest.raises(ValidationError, match="longer"):
        validate_params(ToolParams(date(2020, 1, 1), date(2025, 2, 1)), bundle)


def test_top_n_is_clamped(bundle):
    assert validate_params(ToolParams(date(2025, 2, 1), date(2025, 2, 28), top_n=999), bundle)[0].top_n == MAX_TOP_N
    assert validate_params(ToolParams(date(2025, 2, 1), date(2025, 2, 28), top_n=0), bundle)[0].top_n == 1


def test_unknown_forecast_scope_is_rejected(bundle):
    with pytest.raises(ValidationError):
        validate_params(ToolParams(date(2025, 2, 1), date(2025, 2, 28), scope="Nope"), bundle)


# ----------------------------------------------------------------------------- tools: exact numbers
def test_spend_summary_numbers(bundle):
    r = call_tool("get_spend_summary", bundle, FEB)
    L = r.figures
    assert r.status == "ok"
    assert L.get("total_cost").value == 17 * 28
    assert L.get("previous_cost").value == 17 * 31
    assert L.get("change_amount").value == 476 - 527
    assert L.get("change_pct").value == pytest.approx(-51 / 527)
    assert L.get("budget").value == 500 and L.get("variance").value == -24
    assert set(r.tables) == {"by_department", "by_service", "by_environment", "by_region"}


def test_spend_summary_filters_and_env_limitation(bundle):
    r = call_tool("get_spend_summary", bundle, ToolParams(date(2025, 2, 1), date(2025, 2, 28), departments=("Ops",),
                                                          environments=("production",)))
    assert r.figures.get("total_cost").value == 5 * 28
    assert r.figures.get("budget").value == 150
    assert any("environment / region" in x for x in r.limitations)


def test_spend_summary_without_previous_period_data(bundle):
    r = call_tool("get_spend_summary", bundle, ToolParams(date(2025, 1, 1), date(2025, 1, 31)))
    assert not r.figures.has("change_pct") and any("not fully covered" in x for x in r.limitations)


def test_budget_variance_numbers(bundle):
    r = call_tool("get_budget_variance", bundle, ToolParams(date(2025, 1, 1), date(2025, 3, 31)))
    L = r.figures
    assert L.get("months").value == 3 and L.get("total_actual").value == 17 * 90
    assert L.get("total_budget").value == 1500 and L.get("total_variance").value == 17 * 90 - 1500
    assert L.get("depts_total").value == 2
    assert r.facts["over"][0]["name"] == "Eng" and L.get("dept_0_variance").value == 12 * 90 - 1050


def test_budget_variance_unavailable_without_complete_month(bundle):
    r = call_tool("get_budget_variance", bundle, ToolParams(date(2025, 2, 3), date(2025, 2, 20)))
    assert r.status == "unavailable" and not len(r.figures)


def test_cost_drivers_rank_by_absolute_change(bundle):
    bundle.daily.loc[(bundle.daily["usage_date"] >= "2025-03-01") & (bundle.daily["service_name"] == "Compute"), "total_cost"] *= 2
    r = call_tool("get_top_cost_drivers", bundle, ToolParams(date(2025, 3, 1), date(2025, 3, 31)), dimension="service_name")
    assert r.facts["drivers"][0]["name"] == "Compute"
    assert r.figures.get("driver_0_change").value == 15 * 31 * 2 - 15 * 28
    assert r.figures.get("net_change").value == pytest.approx(r.figures.get("driver_0_change").value + r.figures.get("driver_1_change").value)


def test_cost_drivers_unavailable_without_previous_period(bundle):
    assert call_tool("get_top_cost_drivers", bundle, ToolParams(date(2025, 1, 1), date(2025, 1, 31))).status == "unavailable"


def test_anomaly_tool_dedupes_records_and_ranks(bundle):
    r = call_tool("get_anomalies", bundle, FEB)
    L = r.figures
    assert L.get("flagged_count").value == 2                     # a1 flagged by two methods counts once
    assert L.get("flagged_spend").value == 60.0 and L.get("excess").value == 45.0
    assert r.facts["items"][0]["methods"] == "isolation_forest, rolling_median_mad"
    assert L.get("eval_f1_rolling_median_mad").value == 0.76


def test_anomaly_tool_filters_by_department(bundle):
    r = call_tool("get_anomalies", bundle, ToolParams(date(2025, 2, 1), date(2025, 2, 28), departments=("Ops",)))
    assert r.figures.get("flagged_count").value == 1


def test_forecast_tool_projects_months_with_budget_and_backtest(bundle):
    r = call_tool("get_forecast", bundle, FEB)
    L = r.figures
    assert r.status == "ok" and L.get("horizon_days").value == 30
    assert L.get("proj_2025_04_projected").value == 17 * 30 and not L.has("proj_2025_04_budget")  # no April budget
    assert L.get("ets_wape").value == 0.025 and L.get("naive_wape").value == 0.028
    assert r.facts["months"][0]["label"] == "2025-04"


def test_recommendation_tool_marks_unsupported_estimates(bundle):
    r = call_tool("get_optimization_recommendations", bundle, FEB)
    L = r.figures
    assert L.get("rec_count").value == 2 and L.get("supported_total").value == 200.0
    items = {i["rule"]: i for i in r.facts["items"]}
    assert not items["repeated_budget_overrun"]["has_estimate"] and items["repeated_anomalies"]["has_estimate"]
    assert L.get("rec_0_total_overrun").unit == "usd" and L.get("rec_0_avg_overrun_pct").unit == "pctpts"


def test_tools_report_not_computed_for_missing_model_outputs(bare_bundle):
    for name in ("get_anomalies", "get_forecast", "get_optimization_recommendations"):
        r = call_tool(name, bare_bundle, FEB)
        assert r.status == "empty" and r.facts.get("not_computed") is True and not len(r.figures)


def test_qbr_tool_bundles_all_parts_and_quarter_table(bundle):
    r = call_tool("generate_qbr_metrics", bundle, ToolParams(date(2025, 1, 1), date(2025, 3, 31)))
    assert r.status == "ok" and set(r.facts["parts"]) == {
        "summary", "drivers_service", "drivers_department", "budget", "anomalies", "forecast", "recommendations"}
    q = r.tables["quarters"]
    assert q.iloc[0]["quarter"] == "2025Q1" and q.iloc[0]["actual"] == 17 * 90 and not q.iloc[0]["is_partial"]
    assert r.figures.has("summary.total_cost") and r.figures.has("budget.total_budget")


def test_only_approved_tools_exist_and_unknown_names_are_refused(bundle):
    assert set(TOOLS) == {"get_spend_summary", "get_budget_variance", "get_top_cost_drivers", "get_anomalies", "get_forecast",
                          "get_optimization_recommendations", "generate_qbr_metrics"}
    with pytest.raises(KeyError):
        call_tool("run_sql", bundle, FEB)
