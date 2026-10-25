"""Global sidebar filters shared by every page."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from cloudspend.analytics.spend_metrics import Filters, complete_months

PRESETS = ["Last complete month", "Last 3 complete months", "Full range", "Custom"]


def _preset_range(daily: pd.DataFrame, preset: str) -> tuple[date, date]:
    dates = pd.to_datetime(daily["usage_date"])
    dmin, dmax = dates.min().date(), dates.max().date()
    done = sorted(complete_months(daily))
    if preset == "Full range" or not done:
        return dmin, dmax
    n = 1 if preset == "Last complete month" else min(3, len(done))
    first, last = done[-n], done[-1]
    return first.date(), (last + pd.offsets.MonthEnd(0)).date()


def _options(daily: pd.DataFrame, col: str) -> list[str]:
    return sorted(daily[col].dropna().unique().tolist())


def render_global_filters(daily: pd.DataFrame) -> Filters:
    dates = pd.to_datetime(daily["usage_date"])
    dmin, dmax = dates.min().date(), dates.max().date()
    st.markdown("#### Filters")
    preset = st.selectbox("Period", PRESETS, key="f_preset")
    if preset == "Custom":
        picked = st.date_input(
            "Date range", value=_preset_range(daily, "Last complete month"),
            min_value=dmin, max_value=dmax, key="f_custom",
        )
        if isinstance(picked, tuple) and len(picked) == 2:
            start, end = picked
        else:
            st.info("Pick an end date.")
            st.stop()
    else:
        start, end = _preset_range(daily, preset)
    departments = st.multiselect("Department", _options(daily, "department_name"), key="f_dep")
    services = st.multiselect("Service", _options(daily, "service_name"), key="f_svc")
    envs = st.multiselect("Environment", _options(daily, "environment_name"), key="f_env")
    regions = st.multiselect("Region", _options(daily, "region_name"), key="f_reg")
    st.caption(f"Data available: {dmin} to {dmax}")
    return Filters(start, end, tuple(departments), tuple(services), tuple(envs), tuple(regions))
