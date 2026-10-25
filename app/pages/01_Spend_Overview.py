"""Page 1 - Spend Overview."""

import streamlit as st

from cloudspend.analytics.spend_metrics import (
    DIMENSIONS,
    apply_filters,
    breakdown,
    budget_kpis,
    period_kpis,
    top_contributors,
    trend,
)
from components import charts
from components.common import setup_page
from components.kpi_cards import kpi, money, pct
from components.kpi_cards import table as show_table

ctx = setup_page("Spend Overview")
f, daily = ctx.filters, ctx.daily

if apply_filters(daily, f).empty:
    st.warning("No spend matches the selected filters and period.")
    st.stop()

k = period_kpis(daily, f)
b = budget_kpis(daily, ctx.budget_variance, f)

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Total cost", money(k["total_cost"]), pct(k["change_pct"]) if k["change_pct"] is not None else None,
    help="Sum of total_cost for the selected filters and period.")
kpi(c2, "Previous period", money(k["previous_cost"]),
    help=f"{k['previous_start']} to {k['previous_end']}")
if b["available"]:
    kpi(c3, "Budget", money(b["budget"]), help="Sum of monthly budgets for the selected departments/services.")
    kpi(c4, "Variance vs budget", money(b["variance"]), pct(b["variance_pct"]),
        help="Actual - budget. Positive = over budget.")
else:
    kpi(c3, "Budget", "n/a")
    kpi(c4, "Variance vs budget", "n/a")

if not k["selected_period_covered"]:
    st.warning("The selected period extends beyond the loaded data; totals cover only the available days.")
if not k["previous_period_covered"]:
    st.info(f"The previous period ({k['previous_start']} to {k['previous_end']}) is not fully covered by the data, "
            "so no comparison is shown.")
elif k["previous_cost"] is None:
    st.info("The previous period has zero cost, so a percentage change is undefined.")
if not b["available"]:
    st.caption(f"Budget: {b['reason']}")
elif b["ignores_env_region"]:
    st.caption("Budget and variance ignore the environment / region filters (budgets are not defined at that level).")

st.subheader("Trend")
grain = st.radio("Granularity", ["daily", "monthly"], horizontal=True, label_visibility="collapsed")
st.plotly_chart(charts.trend_chart(trend(daily, f, grain), grain), use_container_width=True)
if grain == "monthly":
    st.caption("Grey bars are months with missing days in the data.")

st.subheader("Where the money goes")
left, right = st.columns(2)
for col, (label, dim) in zip((left, right, left, right), DIMENSIONS.items(), strict=True):
    with col:
        st.plotly_chart(charts.breakdown_bar(breakdown(daily, f, dim), dim, f"Cost by {label.lower()}"),
                        use_container_width=True)

st.subheader("Largest contributors to change")
label = st.selectbox("Break the change down by", list(DIMENSIONS), index=1)
contrib = top_contributors(daily, f, DIMENSIONS[label])
if k["previous_period_covered"]:
    st.plotly_chart(charts.change_bar(contrib, DIMENSIONS[label]), use_container_width=True)
    show = contrib.rename(columns={DIMENSIONS[label]: label, "current_cost": "Current", "previous_cost": "Previous",
                                   "change_amount": "Change ($)", "change_pct": "Change (%)"})
    show_table(show, money_cols=("Current", "Previous", "Change ($)"), pct_cols=("Change (%)",))
else:
    st.info("Change drivers need a fully covered previous period.")
