"""Page 3 - Anomaly Detection (reads stored model outputs written by run_models)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # `cloudspend` / `config` importable without pip install

import pandas as pd
import plotly.express as px
import streamlit as st

from cloudspend import data_access
from cloudspend.analytics.spend_metrics import anomaly_summary, filter_model_output
from components import charts
from components.common import setup_page
from components.kpi_cards import kpi, money
from components.kpi_cards import table as show_table

ctx = setup_page("Anomaly Detection")
st.caption("A flag means a cost is unusual relative to a baseline. It is not evidence of fraud or of a confirmed problem, "
           "and the model does not explain *why* it happened.")

try:
    anomalies = data_access.load_anomalies()
    evaluation = data_access.load_model_evaluation()
except Exception as exc:
    st.error(f"Could not load anomaly results ({type(exc).__name__}).")
    st.stop()

if anomalies.empty:
    st.info("No anomaly results yet. Run `python -m cloudspend.analytics.run_models` to compute them.")
    st.stop()

anomalies["usage_date"] = pd.to_datetime(anomalies["usage_date"])
shown = filter_model_output(anomalies, ctx.filters, "usage_date")
c1, c2 = st.columns(2)
methods = c1.multiselect("Detection method", sorted(shown["detection_method"].unique()),
                         default=sorted(shown["detection_method"].unique()))
severities = c2.multiselect("Severity", ["high", "medium", "low"], default=["high", "medium", "low"])
shown = shown[shown["detection_method"].isin(methods) & shown["severity"].isin(severities)]
if shown.empty:
    st.warning("No flagged records match the selected filters.")
    st.stop()

s = anomaly_summary(shown)
k1, k2, k3, k4 = st.columns(4)
kpi(k1, "Flagged records", f"{s['count']:,}", help="Unique resource-days flagged by the selected methods.")
kpi(k2, "Flagged spend", money(s["flagged_cost"]), help="Observed cost on the flagged records (not a savings figure).")
excess = (shown.drop_duplicates("record_id")["observed_cost"].astype(float)
          - shown.drop_duplicates("record_id")["baseline_cost"].astype(float)).clip(lower=0).sum()
kpi(k3, "Excess over baseline", money(float(excess)), help="Sum of max(observed - baseline, 0) on flagged records.")
both = int((shown.groupby("record_id")["detection_method"].nunique() > 1).sum())
kpi(k4, "Flagged by both methods", f"{both:,}")
st.caption("Severity rule: observed / baseline >= 3 high, >= 1.75 medium, otherwise low.")

st.subheader("Anomalies over time")
weekly = (shown.drop_duplicates("record_id").assign(week=lambda d: d["usage_date"].dt.to_period("W").dt.start_time)
          .groupby(["week", "severity"], as_index=False).size())
fig = px.bar(weekly, x="week", y="size", color="severity", color_discrete_map={
    "high": charts.RED, "medium": "#f59e0b", "low": charts.GREY},
    category_orders={"severity": ["high", "medium", "low"]})
fig.update_layout(height=300, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10),
                  yaxis_title="Flagged records", xaxis_title="")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Actual versus baseline (largest differences)")
top = shown.drop_duplicates("record_id").nlargest(15, "abs_diff").copy()
top["label"] = top["usage_date"].dt.strftime("%Y-%m-%d") + " " + top["resource_id"]
long = top.melt(id_vars="label", value_vars=["baseline_cost", "observed_cost"], var_name="kind", value_name="cost")
long["kind"] = long["kind"].map({"baseline_cost": "Baseline", "observed_cost": "Observed"})
bars = px.bar(long, x="label", y="cost", color="kind", barmode="group",
              color_discrete_map={"Baseline": charts.GREY, "Observed": charts.RED})
bars.update_yaxes(tickformat="$,.0f")
bars.update_layout(height=340, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10),
                   yaxis_title="Cost ($)", xaxis_title="", legend_title_text="")
st.plotly_chart(bars, use_container_width=True)

st.subheader("Flagged records")
flagged = shown.sort_values(["usage_date", "record_id"], ascending=[False, True])[
    ["usage_date", "department_name", "service_name", "environment_name", "resource_id", "detection_method",
     "severity", "observed_cost", "baseline_cost", "abs_diff", "pct_diff", "reason"]]
show_table(flagged, money_cols=("observed_cost", "baseline_cost", "abs_diff"), pct_cols=("pct_diff",), column_config={
    "usage_date": st.column_config.DateColumn("Date"),
    "department_name": "Department", "service_name": "Service", "environment_name": "Environment",
    "resource_id": "Resource", "detection_method": "Method", "severity": "Severity", "reason": "Reason",
    "observed_cost": st.column_config.NumberColumn("Observed", format="dollar"),
    "baseline_cost": st.column_config.NumberColumn("Baseline", format="dollar"),
    "abs_diff": st.column_config.NumberColumn("Difference", format="dollar"),
    "pct_diff": st.column_config.NumberColumn("Difference %", format="%.1f%%"),
})

with st.expander("How good are these detectors? (synthetic holdout evaluation)"):
    ev = evaluation[(evaluation["model_family"] == "anomaly") & (evaluation["scope"] == "holdout")]
    if ev.empty:
        st.write("No evaluation stored.")
    else:
        piv = ev.pivot(index="model_name", columns="metric_name", values="metric_value")
        st.dataframe(piv[["precision", "recall", "f1", "tp", "fp", "fn"]].rename_axis("Method"), use_container_width=True)
        st.caption("One synthetic dataset (seed 42), chronological holdout. Results vary across datasets; see "
                   "`docs/model_evaluation.md` for the multi-seed summary. Gradual drift is detected poorly by both methods.")
