"""The approved analytical tools. The analyst can call ONLY these; none accepts SQL.

Each tool is a pure function over a `DataBundle` (already-loaded REPORTING data) and validated `ToolParams`.
It returns a `ToolResult` holding: an evidence ledger (every number it reports, with unit and source),
small tables (capped at MAX_TABLE_ROWS), limitations, and structured facts for the narrative.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace

import pandas as pd

from cloudspend.ai.ledger import Ledger
from cloudspend.ai.validation import MAX_TABLE_ROWS, ToolParams, validate_params
from cloudspend.analytics.forecasting import MODEL_BASELINE, MODEL_ETS, month_projections
from cloudspend.analytics.spend_metrics import (
    DIMENSIONS,
    apply_filters,
    breakdown,
    budget_kpis,
    complete_months_in_range,
    filter_model_output,
    period_kpis,
    top_contributors,
    variance_by,
)

log = logging.getLogger("cloudspend.analyst")


@dataclass
class DataBundle:
    daily: pd.DataFrame
    budget_variance: pd.DataFrame
    anomalies: pd.DataFrame = field(default_factory=pd.DataFrame)
    forecast: pd.DataFrame = field(default_factory=pd.DataFrame)
    recommendations: pd.DataFrame = field(default_factory=pd.DataFrame)
    evaluation: pd.DataFrame = field(default_factory=pd.DataFrame)

    def members(self) -> dict[str, list[str]]:
        d = self.daily
        return {"departments": sorted(d["department_name"].unique()), "services": sorted(d["service_name"].unique()),
                "environments": sorted(d["environment_name"].unique()), "regions": sorted(d["region_name"].unique())}

    def data_range(self):
        dates = pd.to_datetime(self.daily["usage_date"])
        return dates.min().date(), dates.max().date()

    @classmethod
    def load(cls) -> DataBundle:
        from cloudspend import data_access

        return cls(data_access.load_daily(), data_access.load_budget_variance(), data_access.load_anomalies(),
                   data_access.load_forecast(), data_access.load_recommendations(), data_access.load_model_evaluation())


@dataclass
class ToolResult:
    tool: str
    status: str                       # ok | empty | unavailable | error
    params: ToolParams
    figures: Ledger = field(default_factory=Ledger)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    duration_ms: float = 0.0


def _cap(df: pd.DataFrame) -> pd.DataFrame:
    return df.head(MAX_TABLE_ROWS).reset_index(drop=True)


def _label(p: ToolParams) -> str:
    return f"{p.start} to {p.end}"


def _result(tool: str, p: ToolParams, notes: list[str]) -> ToolResult:
    return ToolResult(tool, "ok", p, limitations=list(notes))


# --------------------------------------------------------------------------- 1. spend summary
def get_spend_summary(bundle: DataBundle, params: ToolParams) -> ToolResult:
    p, notes = validate_params(params, bundle)
    r, f, src = _result("get_spend_summary", p, notes), p.filters(), "get_spend_summary"
    if apply_filters(bundle.daily, f).empty:
        r.status = "empty"
        r.limitations.append("No spend matches the selected period and filters.")
        return r
    k = period_kpis(bundle.daily, f)
    L = r.figures
    L.add("total_cost", "Total cost", k["total_cost"], "usd", f"{src}: SUM(total_cost) for the period/filters")
    L.add("days", "Days in period", k["days"], "days", f"{src}: calendar days selected")
    if k["previous_cost"] is not None:
        L.add("previous_cost", "Previous-period cost", k["previous_cost"], "usd", f"{src}: same filters, previous period")
        L.add("change_amount", "Change vs previous", k["change_amount"], "usd", f"{src}: current - previous")
        L.add("change_pct", "Change % vs previous", k["change_pct"], "pct", f"{src}: (current - previous) / previous")
    elif not k["previous_period_covered"]:
        r.limitations.append("The previous period is not fully covered by the data, so no comparison is available.")
    else:
        r.limitations.append("The previous period has zero cost, so a percentage change is undefined.")
    if not k["selected_period_covered"]:
        r.limitations.append("The selected period extends beyond the loaded data; totals cover available days only.")
    b = budget_kpis(bundle.daily, bundle.budget_variance, f)
    if b["available"]:
        L.add("budget", "Budget", b["budget"], "usd", f"{src}: SUM(monthly budgets), dept/service filters only")
        L.add("budget_actual", "Actual for budget comparison", b["actual"], "usd", f"{src}: actual, dept/service filters only")
        L.add("variance", "Variance vs budget", b["variance"], "usd", f"{src}: actual - budget (positive = over)")
        L.add("variance_pct", "Variance %", b["variance_pct"], "pct", f"{src}: variance / budget")
        if b["ignores_env_region"]:
            r.limitations.append("Budget figures ignore the environment / region filters (budgets are not defined at that level).")
    else:
        r.limitations.append(b["reason"])
    for name, dim in DIMENSIONS.items():
        r.tables[f"by_{name.lower()}"] = _cap(breakdown(bundle.daily, f, dim).head(10))
    r.facts = {"period": _label(p), "prev_period": f"{k['previous_start']} to {k['previous_end']}"}
    return r


# --------------------------------------------------------------------------- 2. budget variance
def get_budget_variance(bundle: DataBundle, params: ToolParams) -> ToolResult:
    p, notes = validate_params(params, bundle)
    r, src = _result("get_budget_variance", p, notes), "get_budget_variance"
    months = complete_months_in_range(bundle.daily, p.start, p.end)
    if not months:
        r.status = "unavailable"
        r.limitations.append("Budgets are monthly: the period contains no complete, fully-loaded calendar month.")
        return r
    bv = bundle.budget_variance
    bv = bv[pd.to_datetime(bv["month_start"]).isin(months)]
    if p.departments:
        bv = bv[bv["department_name"].isin(p.departments)]
    if p.services:
        bv = bv[bv["service_name"].isin(p.services)]
    if bv.empty:
        r.status = "empty"
        r.limitations.append("No budget data for the selected filters.")
        return r
    if p.environments or p.regions:
        r.limitations.append("Environment / region filters do not apply to budgets.")
    first, last = months[0], months[-1]
    if (first.date() > p.start) or (last + pd.offsets.MonthEnd(0)).date() < p.end:
        r.limitations.append("Months that are incomplete in the data are excluded from the budget comparison.")
    L = r.figures
    tot = variance_by(bv.assign(all="x"), ["all"]).iloc[0]
    L.add("total_actual", "Actual", tot["actual_cost"], "usd", f"{src}: SUM(actual_cost) over complete months")
    L.add("total_budget", "Budget", tot["budget_amount"], "usd", f"{src}: SUM(budget_amount)")
    L.add("total_variance", "Variance", tot["variance_amount"], "usd", f"{src}: actual - budget")
    L.add("total_variance_pct", "Variance %", tot["variance_pct"], "pct", f"{src}: variance / budget")
    L.add("months", "Complete months", len(months), "count", f"{src}: complete months in period")
    dept = variance_by(bv, ["department_name"]).sort_values("variance_amount", ascending=False)
    L.add("depts_total", "Departments", len(dept), "count", f"{src}: departments with data")
    L.add("depts_over", "Departments over budget", int((dept["variance_amount"] > 0).sum()), "count",
          f"{src}: departments with actual > budget")
    over = dept[dept["variance_amount"] > 0].head(p.top_n)
    items = []
    for i, row in enumerate(over.itertuples()):
        L.add(f"dept_{i}_variance", f"{row.department_name} variance", row.variance_amount, "usd", f"{src}: dept actual - budget")
        L.add(f"dept_{i}_variance_pct", f"{row.department_name} variance %", row.variance_pct, "pct", f"{src}: variance / budget")
        items.append({"name": row.department_name, "i": i})
    combo = variance_by(bv, ["department_name", "service_name"]).sort_values("variance_amount", ascending=False)
    r.tables["by_department"] = _cap(dept)
    r.tables["top_over_budget_department_service"] = _cap(combo[combo["variance_amount"] > 0].head(10))
    r.facts = {"period": _label(p), "months": f"{first:%Y-%m}" if first == last else f"{first:%Y-%m} to {last:%Y-%m}", "over": items}
    return r


# --------------------------------------------------------------------------- 3. cost drivers
def get_top_cost_drivers(bundle: DataBundle, params: ToolParams, dimension: str = "service_name") -> ToolResult:
    p, notes = validate_params(params, bundle)
    r, src = _result("get_top_cost_drivers", p, notes), "get_top_cost_drivers"
    if dimension not in DIMENSIONS.values():
        raise ValueError(f"unsupported dimension {dimension!r}")
    k = period_kpis(bundle.daily, p.filters())
    if not k["previous_period_covered"]:
        r.status = "unavailable"
        r.limitations.append("Cost drivers need a previous period that is fully covered by the data.")
        return r
    c = top_contributors(bundle.daily, p.filters(), dimension)
    c = c[c["change_amount"] != 0]
    if c.empty:
        r.status = "empty"
        r.limitations.append("No change versus the previous period for the selected filters.")
        return r
    L = r.figures
    L.add("net_change", "Net change", float(c["change_amount"].sum()), "usd", f"{src}: SUM of member changes = current - previous")
    items = []
    for i, row in enumerate(c.head(p.top_n).itertuples()):
        name = getattr(row, dimension)
        L.add(f"driver_{i}_change", f"{name} change", row.change_amount, "usd", f"{src}: {dimension} current - previous")
        L.add(f"driver_{i}_change_pct", f"{name} change %", row.change_pct, "pct", f"{src}: change / previous")
        L.add(f"driver_{i}_current", f"{name} current", row.current_cost, "usd", f"{src}: {dimension} current period cost")
        L.add(f"driver_{i}_previous", f"{name} previous", row.previous_cost, "usd", f"{src}: {dimension} previous period cost")
        items.append({"name": name, "i": i})
    r.tables["drivers"] = _cap(c)
    r.facts = {"dimension": dimension, "dimension_label": next(k2 for k2, v in DIMENSIONS.items() if v == dimension).lower(),
               "drivers": items, "period": _label(p), "prev_period": f"{k['previous_start']} to {k['previous_end']}"}
    r.limitations.append("These figures show what changed, not why it changed.")
    return r


# --------------------------------------------------------------------------- 4. anomalies
def _eval_f1(bundle: DataBundle, L: Ledger) -> None:
    ev = bundle.evaluation
    if ev.empty:
        return
    h = ev[(ev["model_family"] == "anomaly") & (ev["scope"] == "holdout") & (ev["metric_name"] == "f1")]
    for row in h.itertuples():
        L.add(f"eval_f1_{row.model_name}", f"Holdout F1 ({row.model_name})", row.metric_value, "ratio",
              "model_evaluation: holdout F1 on one synthetic dataset (seed 42)")


def get_anomalies(bundle: DataBundle, params: ToolParams) -> ToolResult:
    p, notes = validate_params(params, bundle)
    r, src = _result("get_anomalies", p, notes), "get_anomalies"
    if bundle.anomalies.empty:
        r.status = "empty"
        r.facts = {"not_computed": True}
        r.limitations.append("Anomaly detection results have not been computed yet.")
        return r
    a = bundle.anomalies.assign(usage_date=pd.to_datetime(bundle.anomalies["usage_date"]))
    a = filter_model_output(a, p.filters(), "usage_date")
    if a.empty:
        r.status = "empty"
        r.limitations.append("No records were flagged in the selected period and filters.")
        return r
    u = a.sort_values("abs_diff", ascending=False).drop_duplicates("record_id")
    L = r.figures
    L.add("flagged_count", "Flagged records", len(u), "count", f"{src}: distinct flagged resource-days")
    L.add("flagged_spend", "Flagged spend", u["observed_cost"].astype(float).sum(), "usd", f"{src}: SUM(observed_cost) of flagged records")
    excess = (u["observed_cost"].astype(float) - u["baseline_cost"].astype(float)).clip(lower=0).sum()
    L.add("excess", "Excess over baseline", excess, "usd", f"{src}: SUM(max(observed - baseline, 0))")
    L.add("high_count", "High-severity records", int((u["severity"] == "high").sum()), "count",
          f"{src}: observed/baseline >= 3")
    items = []
    for i, row in enumerate(u.head(p.top_n).itertuples()):
        L.add(f"anom_{i}_observed", "Observed cost", row.observed_cost, "usd", f"{src}: record observed cost")
        L.add(f"anom_{i}_baseline", "Baseline cost", row.baseline_cost, "usd", f"{src}: baseline (median of previous same-day-type)")
        L.add(f"anom_{i}_diff", "Difference", row.abs_diff, "usd", f"{src}: observed - baseline")
        L.add(f"anom_{i}_pct", "Difference %", row.pct_diff, "pct", f"{src}: (observed - baseline) / baseline")
        items.append({"i": i, "date": f"{row.usage_date:%Y-%m-%d}", "resource": row.resource_id, "dept": row.department_name,
                      "service": row.service_name, "severity": row.severity,
                      "methods": ", ".join(sorted(a.loc[a["record_id"] == row.record_id, "detection_method"].unique()))})
    _eval_f1(bundle, L)
    r.tables["top_anomalies"] = _cap(u.head(p.top_n)[["usage_date", "department_name", "service_name", "environment_name",
                                                       "resource_id", "severity", "observed_cost", "baseline_cost", "abs_diff",
                                                       "pct_diff", "reason"]])
    r.facts = {"period": _label(p), "items": items}
    r.limitations.append("A flag means unusual relative to a baseline; it does not establish a cause and is not evidence of fraud.")
    return r


# --------------------------------------------------------------------------- 5. forecast
def get_forecast(bundle: DataBundle, params: ToolParams) -> ToolResult:
    p, notes = validate_params(params, bundle)
    r, src = _result("get_forecast", p, notes), "get_forecast"
    fc = bundle.forecast
    if fc.empty:
        r.status = "empty"
        r.facts = {"not_computed": True}
        r.limitations.append("Forecasts have not been computed yet.")
        return r
    fs = fc[fc["scope_value"] == p.scope]
    ets = fs[fs["model_name"] == MODEL_ETS].assign(forecast_date=lambda d: pd.to_datetime(d["forecast_date"])).sort_values("forecast_date")
    if ets.empty:
        r.status = "unavailable"
        r.limitations.append(f"No forecast exists for '{p.scope}' (insufficient history).")
        return r
    daily = bundle.daily if p.scope == "total" else bundle.daily[bundle.daily["department_name"] == p.scope]
    hist = daily.groupby(pd.to_datetime(daily["usage_date"]))["total_cost"].sum().sort_index()
    bv = bundle.budget_variance if p.scope == "total" else bundle.budget_variance[bundle.budget_variance["department_name"] == p.scope]
    budgets = bv.groupby(pd.to_datetime(bv["month_start"]))["budget_amount"].sum().to_dict()
    L = r.figures
    L.add("horizon_days", "Forecast horizon", len(ets), "days", f"{src}: days forecast")
    L.add("interval_level", "Prediction interval level", 0.80, "pct", f"{src}: ETS prediction interval (alpha = 0.20)")
    months = []
    for m in month_projections(hist, ets.set_index("forecast_date")["forecast_cost"].astype(float), budgets):  # type: ignore[arg-type]
        if not m["fully_covered"] or m["days_forecast"] == 0:   # only months that include forecast days are projections
            continue
        key = f"{m['month']:%Y_%m}"
        L.add(f"proj_{key}_actual", "Actual to date", m["actual_to_date"], "usd", f"{src}: actual cost in month so far")
        L.add(f"proj_{key}_forecast", "Forecast remaining", m["forecast_remaining"], "usd", f"{src}: SUM(ETS forecast) for remaining days")
        L.add(f"proj_{key}_projected", "Projected month total", m["projected"], "usd", f"{src}: actual to date + forecast remaining")
        if m.get("variance") is not None:
            L.add(f"proj_{key}_budget", "Budget", m["budget"], "usd", f"{src}: monthly budget")
            L.add(f"proj_{key}_variance", "Projected variance", m["variance"], "usd", f"{src}: projected - budget")
            L.add(f"proj_{key}_variance_pct", "Projected variance %", m["variance_pct"], "pct", f"{src}: variance / budget")
        months.append({"key": key, "label": f"{m['month']:%Y-%m}", "has_budget": m.get("variance") is not None,
                       "days_actual": m["days_actual"]})
    bt = bundle.evaluation[(bundle.evaluation["model_family"] == "forecast") & (bundle.evaluation["scope"] == p.scope)] \
        if not bundle.evaluation.empty else pd.DataFrame()
    if not bt.empty:
        t = bt.pivot(index="model_name", columns="metric_name", values="metric_value")
        if MODEL_ETS in t.index:
            L.add("ets_wape", "ETS backtest WAPE", t.loc[MODEL_ETS, "wape"], "pct", "model_evaluation: rolling-origin backtest")
            L.add("ets_coverage", "ETS 80% interval coverage", t.loc[MODEL_ETS, "interval_coverage"], "pct", "model_evaluation: backtest")
        if MODEL_BASELINE in t.index:
            L.add("naive_wape", "Baseline backtest WAPE", t.loc[MODEL_BASELINE, "wape"], "pct", "model_evaluation: rolling-origin backtest")
    r.tables["forecast_daily"] = _cap(ets[["forecast_date", "forecast_cost", "lower_bound", "upper_bound"]])
    r.facts = {"scope": p.scope, "model": f"{MODEL_ETS} {ets['model_version'].iloc[0]}",
               "trained_through": str(pd.to_datetime(ets["trained_through_date"].iloc[0]).date()), "months": months}
    r.limitations += ["Month totals carry no prediction interval; only the daily forecast has an 80% band.",
                      "Backtests were run on synthetic data with a smooth trend and weekly seasonality, which favours the model.",
                      "Forecasts are precomputed at total / department grain, so service, environment and region filters do not apply."]
    return r


# --------------------------------------------------------------------------- 6. recommendations
_REC_USD = {"total_overrun", "nonprod_weekend_spend", "excess_over_baseline", "cost_start", "cost_latest",
            "avg_weekday_cost", "avg_weekend_cost"}


def _evidence_unit(field_name: str) -> str:
    if field_name in _REC_USD:
        return "usd"
    if field_name.endswith("_pct") or field_name == "gap_points":
        return "pctpts"
    if field_name.endswith("_days"):
        return "days"
    if "ratio" in field_name:
        return "ratio"
    return "count"


def get_optimization_recommendations(bundle: DataBundle, params: ToolParams) -> ToolResult:
    import json

    p, notes = validate_params(params, bundle)
    r, src = _result("get_optimization_recommendations", p, notes), "get_optimization_recommendations"
    recs = bundle.recommendations
    if recs.empty:
        r.status = "empty"
        r.facts = {"not_computed": True}
        r.limitations.append("No recommendations are available (rules have not run or found nothing).")
        return r
    recs = filter_model_output(recs, p.filters(), None)
    if recs.empty:
        r.status = "empty"
        r.limitations.append("No recommendations match the selected filters.")
        return r
    rank = {"High": 0, "Medium": 1, "Low": 2}
    recs = recs.assign(_r=recs["confidence"].map(rank)).sort_values(["_r", "rule_name", "department_name"]).drop(columns="_r")
    L = r.figures
    L.add("rec_count", "Recommendations", len(recs), "count", f"{src}: recommendations matching filters")
    supported = pd.to_numeric(recs["estimated_savings"], errors="coerce")
    if supported.notna().any():
        L.add("supported_total", "Supported estimate (upper bound)", supported.sum(), "usd",
              f"{src}: SUM of estimates with a stated formula")
    items = []
    for i, row in enumerate(recs.head(p.top_n).itertuples()):
        try:
            ev = json.loads(str(row.evidence))
        except (TypeError, ValueError):
            ev = {}
        fields = []
        for k, v in ev.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                L.add(f"rec_{i}_{k}", k, v, _evidence_unit(k), f"{src}: evidence field '{k}' of {row.rule_name}")
                fields.append(k)
        est = pd.to_numeric(pd.Series([row.estimated_savings]), errors="coerce").iloc[0]
        if pd.notna(est):
            L.add(f"rec_{i}_estimate", "Supported estimate", est, "usd", f"{src}: {row.savings_formula}")
        items.append({"i": i, "rule": row.rule_name, "dept": row.department_name, "service": row.service_name,
                      "confidence": row.confidence, "action": row.suggested_action, "fields": fields,
                      "has_estimate": bool(pd.notna(est)), "formula": row.savings_formula})
    by_rule = recs.groupby("rule_name").size().to_dict()
    for rule, n in by_rule.items():
        L.add(f"rule_count_{rule}", f"{rule} recommendations", n, "count", f"{src}: count for rule {rule}")
    r.facts = {"items": items, "by_rule": by_rule}
    r.tables["recommendations"] = _cap(recs[["rule_name", "department_name", "service_name", "confidence",
                                             "suggested_action", "estimated_savings_display", "review_status"]])
    r.limitations += ["Recommendations are for analyst review only; nothing is executed against infrastructure.",
                      "Where the data cannot support a savings formula the estimate is shown as 'Requires investigation'."]
    return r


# --------------------------------------------------------------------------- 7. QBR metrics
def quarter_table(bundle: DataBundle) -> pd.DataFrame:
    d = bundle.daily.assign(date=pd.to_datetime(bundle.daily["usage_date"]))
    d["quarter"] = d["date"].dt.to_period("Q")
    act = d.groupby("quarter").agg(actual=("total_cost", "sum"), days=("date", "nunique"))
    bv = bundle.budget_variance.assign(quarter=pd.to_datetime(bundle.budget_variance["month_start"]).dt.to_period("Q"))
    act["budget"] = bv.groupby("quarter")["budget_amount"].sum()
    act["days_in_quarter"] = [(q.end_time.normalize() - q.start_time).days + 1 for q in act.index]
    act["is_partial"] = act["days"] < act["days_in_quarter"]
    act["qoq_pct"] = act["actual"].pct_change()
    return act.reset_index().assign(quarter=lambda x: x["quarter"].astype(str))


def generate_qbr_metrics(bundle: DataBundle, params: ToolParams) -> ToolResult:
    p, notes = validate_params(params, bundle)
    r = _result("generate_qbr_metrics", p, notes)
    sub = replace(p, top_n=min(p.top_n, 3))
    parts = {
        "summary": get_spend_summary(bundle, sub),
        "drivers_service": get_top_cost_drivers(bundle, sub, "service_name"),
        "drivers_department": get_top_cost_drivers(bundle, sub, "department_name"),
        "budget": get_budget_variance(bundle, sub),
        "anomalies": get_anomalies(bundle, sub),
        "forecast": get_forecast(bundle, replace(sub, scope="total")),
        "recommendations": get_optimization_recommendations(bundle, sub),
    }
    for name, part in parts.items():
        r.figures.merge(part.figures, prefix=f"{name}.")
    r.tables["quarters"] = quarter_table(bundle)
    r.facts = {"parts": parts, "period": _label(p)}
    if any(r.tables["quarters"]["is_partial"]):
        r.limitations.append("The latest quarter in the data is incomplete, so quarter totals are not directly comparable.")
    if parts["summary"].status == "empty":
        r.status = "empty"
    return r


TOOLS = {
    "get_spend_summary": get_spend_summary,
    "get_budget_variance": get_budget_variance,
    "get_top_cost_drivers": get_top_cost_drivers,
    "get_anomalies": get_anomalies,
    "get_forecast": get_forecast,
    "get_optimization_recommendations": get_optimization_recommendations,
    "generate_qbr_metrics": generate_qbr_metrics,
}


def call_tool(name: str, bundle: DataBundle, params: ToolParams, **kwargs) -> ToolResult:
    """Run an approved tool with timing and structured logging (tool name, status, duration; no question text, no secrets)."""
    if name not in TOOLS:
        raise KeyError(f"'{name}' is not an approved tool")
    t0 = time.perf_counter()
    try:
        res = TOOLS[name](bundle, params, **kwargs)
    except Exception:
        log.exception("tool=%s status=error", name)
        raise
    res.duration_ms = (time.perf_counter() - t0) * 1000
    log.info("tool=%s status=%s ms=%.1f", name, res.status, res.duration_ms)
    return res
