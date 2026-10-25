"""Shared page bootstrap: path setup, page config, cached data loading, global filters."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from cloudspend import data_access
from cloudspend.analytics.spend_metrics import Filters
from components.filters import render_global_filters

DISCLAIMER = "All data is **synthetic**. Not real billing data; no real savings or outcomes are implied."


@st.cache_data(ttl=600, show_spinner="Loading data...")
def _load_all() -> tuple[pd.DataFrame, pd.DataFrame, data_access.SourceInfo]:
    return data_access.load_daily(), data_access.load_budget_variance(), data_access.load_refresh_info()


@dataclass
class Context:
    daily: pd.DataFrame
    budget_variance: pd.DataFrame
    source: data_access.SourceInfo
    filters: Filters


def setup_page(title: str, icon: str = ":bar_chart:") -> Context:
    st.set_page_config(page_title=f"CloudSpend AI - {title}", page_icon=icon, layout="wide")
    try:
        daily, bv, source = _load_all()
    except data_access.DataUnavailableError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:  # connection/permission problems: show a message without exposing secrets
        st.error(
            f"Could not load data ({type(exc).__name__}). Check your .env / Snowflake access, "
            "or set CLOUDSPEND_DATA_MODE=local."
        )
        st.caption(str(exc)[:200])
        st.stop()
    with st.sidebar:
        st.markdown("### CloudSpend AI")
        st.caption(DISCLAIMER)
        f = render_global_filters(daily)
        st.divider()
        st.caption(f"**Data source:** {source.detail}")
        if source.mode == "snowflake" and source.read_only is False:
            st.caption(":warning: Using the pipeline login (not read-only). See `sql/08_readonly_role.sql`.")
        if st.button("Reload data"):
            st.cache_data.clear()
            st.rerun()
    st.title(title)
    st.caption(f"Selected period: **{f.start} to {f.end}** ({f.days} days)")
    return Context(daily, bv, source, f)
