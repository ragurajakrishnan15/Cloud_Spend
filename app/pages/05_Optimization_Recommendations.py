"""Page 5 - Optimization Recommendations (rule-based; reviewable, never executed)."""

import json

import pandas as pd
import streamlit as st

from cloudspend import data_access
from cloudspend.analytics.spend_metrics import filter_model_output
from components.common import setup_page
from components.kpi_cards import kpi, money

ctx = setup_page("Optimization Recommendations")
st.caption("Recommendations are for analyst review only. Nothing here changes any infrastructure, and no savings are "
           "claimed unless the data supports a stated formula.")

try:
    recs = data_access.load_recommendations()
except Exception as exc:
    st.error(f"Could not load recommendations ({type(exc).__name__}).")
    st.stop()

if recs.empty:
    st.info("No recommendations yet. Run `python -m cloudspend.analytics.run_models` to generate them.")
    st.stop()

shown = filter_model_output(recs, ctx.filters, None)
rules = sorted(shown["rule_name"].unique())
c1, c2 = st.columns(2)
pick_rules = c1.multiselect("Rule", rules, default=rules)
pick_conf = c2.multiselect("Evidence strength", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
shown = shown[shown["rule_name"].isin(pick_rules) & shown["confidence"].isin(pick_conf)]
if shown.empty:
    st.warning("No recommendations match the selected filters.")
    st.stop()

supported = pd.to_numeric(shown["estimated_savings"], errors="coerce")
k1, k2, k3 = st.columns(3)
kpi(k1, "Recommendations", f"{len(shown)}")
kpi(k2, "With a supported dollar estimate", f"{int(supported.notna().sum())}")
kpi(k3, "Supported estimate (upper bound)", money(float(supported.sum())) if supported.notna().any() else "n/a",
    help="Only rules with a data-supported formula populate this; others show 'Requires investigation'.")


def evidence_text(raw: str) -> str:
    try:
        return "; ".join(f"{k}={v}" for k, v in json.loads(raw).items())
    except (TypeError, ValueError):
        return str(raw)


table = shown.assign(evidence_summary=shown["evidence"].map(evidence_text))[
    ["rule_name", "department_name", "service_name", "period_start", "period_end", "evidence_summary",
     "suggested_action", "estimated_savings_display", "confidence", "review_status"]]
st.dataframe(table, hide_index=True, use_container_width=True, column_config={
    "rule_name": "Rule", "department_name": "Department", "service_name": "Service",
    "period_start": st.column_config.DateColumn("From"), "period_end": st.column_config.DateColumn("To"),
    "evidence_summary": st.column_config.TextColumn("Evidence", width="large"),
    "suggested_action": st.column_config.TextColumn("Suggested next step", width="large"),
    "estimated_savings_display": "Estimated opportunity", "confidence": "Evidence strength",
    "review_status": "Review status"})

st.subheader("Inspect one recommendation")
ids = shown["recommendation_id"].tolist()
rid = st.selectbox("Recommendation", ids, format_func=lambda i: (
    f"{shown.loc[shown['recommendation_id'] == i, 'rule_name'].iloc[0]} - "
    f"{shown.loc[shown['recommendation_id'] == i, 'department_name'].iloc[0]} / "
    f"{shown.loc[shown['recommendation_id'] == i, 'service_name'].iloc[0]}"))
row = shown[shown["recommendation_id"] == rid].iloc[0]
st.markdown(f"**ID** `{row['recommendation_id']}` | **Rule** `{row['rule_name']}` `{row['rule_version']}` | "
            f"**Status** {row['review_status']}")
st.markdown(f"**Next step:** {row['suggested_action']}")
try:
    st.json(json.loads(row["evidence"]))
except (TypeError, ValueError):
    st.write(row["evidence"])
formula = row.get("savings_formula")
st.markdown(f"**Estimated opportunity:** {row['estimated_savings_display']}")
if isinstance(formula, str) and formula:
    st.caption(f"Formula: {formula}")
