"""Formatting helpers, KPI cards and consistently formatted tables."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def money(x: float | None) -> str:
    return "n/a" if x is None else (f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}")


def pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def md_safe(text: str) -> str:
    """Escape dollar signs so Streamlit markdown does not render '$a ... $b' as LaTeX math."""
    return text.replace("$", "\\$")


def kpi(col, label: str, value: str, delta: str | None = None, *, help: str | None = None):
    """Cost KPIs use inverse colouring (a rise in cost is shown red)."""
    with col:
        st.metric(label, value, delta=delta, delta_color="inverse", help=help)


def table(df: pd.DataFrame, *, money_cols: tuple[str, ...] = (), pct_cols: tuple[str, ...] = (), **kwargs) -> None:
    """st.dataframe with uniform formatting: money as -$1,234.00; fraction columns shown as 0.0% (one decimal)."""
    d = df.copy()
    cfg = {c: st.column_config.NumberColumn(format="dollar") for c in money_cols}
    for c in pct_cols:
        d[c] = pd.to_numeric(d[c], errors="coerce") * 100
        cfg[c] = st.column_config.NumberColumn(format="%.1f%%")
    cfg.update(kwargs.pop("column_config", {}))
    st.dataframe(d, hide_index=True, use_container_width=True, column_config=cfg, **kwargs)
