"""Page 2 - Budget Variance."""

import pandas as pd
import streamlit as st

from cloudspend.analytics.spend_metrics import complete_months_in_range, safe_pct, variance_by
from components import charts
from components.common import setup_page
from components.kpi_cards import kpi, money, pct, table

ctx = setup_page("Budget Variance")
f = ctx.filters
months = complete_months_in_range(ctx.daily, f.start, f.end)

if not months:
    st.warning("The selected period contains no complete calendar month. Budgets are monthly; widen the period.")
    st.stop()

bv = ctx.budget_variance
bv = bv[pd.to_datetime(bv["month_start"]).isin(months)]
if f.departments:
    bv = bv[bv["department_name"].isin(f.departments)]
if f.services:
    bv = bv[bv["service_name"].isin(f.services)]
if bv.empty:
    st.warning("No budget data for the selected filters.")
    st.stop()

st.caption(
    f"Complete months included: {months[0]:%Y-%m} to {months[-1]:%Y-%m} ({len(months)}). "
    "Budgets are defined per month x department x service, so environment / region filters do not apply here."
)

total = variance_by(bv.assign(all="Total"), ["all"]).iloc[0]
c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Actual", money(total["actual_cost"]))
kpi(c2, "Budget", money(total["budget_amount"]))
kpi(c3, "Variance", money(total["variance_amount"]), help="Actual - budget; positive = over budget.")
kpi(c4, "Variance %", pct(total["variance_pct"], signed=False))

st.subheader("Budget vs actual by department")
dept = variance_by(bv, ["department_name"]).sort_values("variance_amount", ascending=False)
left, right = st.columns([1, 1])
left.plotly_chart(charts.budget_vs_actual(dept, "department_name"), use_container_width=True)
with right:
    table(dept.rename(columns={"department_name": "Department", "actual_cost": "Actual", "budget_amount": "Budget",
                               "variance_amount": "Variance ($)", "variance_pct": "Variance (%)"}),
          money_cols=("Actual", "Budget", "Variance ($)"), pct_cols=("Variance (%)",))

st.subheader("Largest over-budget categories")
combo = variance_by(bv, ["department_name", "service_name"])
over = combo[combo["variance_amount"] > 0].sort_values("variance_amount", ascending=False).head(10)
if over.empty:
    st.success("No department / service combination is over budget in this period.")
else:
    table(over.rename(columns={"department_name": "Department", "service_name": "Service", "actual_cost": "Actual",
                               "budget_amount": "Budget", "variance_amount": "Over by ($)", "variance_pct": "Over by (%)"}),
          money_cols=("Actual", "Budget", "Over by ($)"), pct_cols=("Over by (%)",))

st.subheader("Month-over-month")
monthly = variance_by(bv, ["month_start"]).sort_values("month_start")
monthly["mom_change_pct"] = [safe_pct(a - p, p) if i else None for i, (a, p) in enumerate(
    zip(monthly["actual_cost"], monthly["actual_cost"].shift(1), strict=True))]
st.plotly_chart(charts.budget_vs_actual(monthly.assign(month=monthly["month_start"].dt.strftime("%Y-%m")), "month"),
                use_container_width=True)
table(monthly.assign(Month=monthly["month_start"].dt.strftime("%Y-%m"))[
    ["Month", "actual_cost", "budget_amount", "variance_pct", "mom_change_pct"]
].rename(columns={"actual_cost": "Actual", "budget_amount": "Budget", "variance_pct": "Variance (%)",
                  "mom_change_pct": "MoM actual (%)"}),
      money_cols=("Actual", "Budget"), pct_cols=("Variance (%)", "MoM actual (%)"))

st.subheader("Drill-down: department -> service -> time")
dep_choice = st.selectbox("Department", sorted(bv["department_name"].unique()))
by_service = variance_by(bv[bv["department_name"] == dep_choice], ["service_name"]).sort_values(
    "variance_amount", ascending=False)
table(by_service.rename(columns={"service_name": "Service", "actual_cost": "Actual", "budget_amount": "Budget",
                                 "variance_amount": "Variance ($)", "variance_pct": "Variance (%)"}),
      money_cols=("Actual", "Budget", "Variance ($)"), pct_cols=("Variance (%)",))
svc_choice = st.selectbox("Service", by_service["service_name"].tolist())
series = variance_by(bv[(bv["department_name"] == dep_choice) & (bv["service_name"] == svc_choice)],
                     ["month_start"]).sort_values("month_start")
series["month"] = series["month_start"].dt.strftime("%Y-%m")
st.plotly_chart(charts.budget_vs_actual(series, "month"), use_container_width=True)
