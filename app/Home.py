"""CloudSpend AI - home page."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # `cloudspend` / `config` importable without pip install

import pandas as pd
import streamlit as st

from cloudspend.analytics.spend_metrics import complete_months
from components.common import DISCLAIMER, setup_page

ctx = setup_page("CloudSpend AI", ":cloud:")

st.markdown(
    "Product-finance analytics for cloud spend: where money goes, why it changes, "
    "whether budgets hold, and what deserves investigation."
)
st.info(DISCLAIMER)

dates = pd.to_datetime(ctx.daily["usage_date"])
months = sorted(complete_months(ctx.daily))
c1, c2, c3, c4 = st.columns(4)
c1.metric("Data from", f"{dates.min().date()}")
c2.metric("Data to", f"{dates.max().date()}")
c3.metric("Complete months", len(months))
c4.metric("Daily rows", f"{len(ctx.daily):,}")
st.caption(f"Source: {ctx.source.detail}")
if dates.max().date() != (months[-1] + pd.offsets.MonthEnd(0)).date():
    st.warning(
        f"Data ends {dates.max().date()}, so the final month is incomplete. Period-over-period comparisons "
        "and budgets use complete months only."
    )

st.subheader("Pages")
st.markdown(
    """
1. **Spend Overview** - totals, change vs the previous period, trend, and what drives the change.
2. **Budget Variance** - actual vs budget by department and service, with drill-down.
3. **Anomaly Detection** - unusual costs relative to a baseline, with two methods and their evaluation.
4. **Spend Forecasting** - daily forecasts with intervals, month projections and a baseline comparison.
5. **Optimization Recommendations** - reviewable, rule-based suggestions with their evidence.
6. **AI Finance Analyst** - grounded Q&A and QBR drafts *(Phase 6)*.
"""
)

with st.expander("KPI definitions"):
    st.markdown(
        """
- **Previous period** = the preceding whole calendar months for whole-month selections (e.g. November vs October), otherwise the immediately preceding period of equal length.
- **Change %** = (current - previous) / previous; shown as n/a when the previous period is zero or not covered by the data.
- **Budget variance** = actual - budget (positive = over budget); **variance %** = variance / budget.
- Budgets exist per month x department x service, so budget figures need whole, fully-loaded calendar months
  and ignore the environment / region filters.
"""
    )
