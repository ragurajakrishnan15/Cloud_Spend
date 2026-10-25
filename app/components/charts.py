"""Plotly chart builders with one consistent look."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

BLUE, GREY, RED, GREEN = "#2563eb", "#94a3b8", "#dc2626", "#16a34a"
LAYOUT = dict(template="plotly_white", margin=dict(l=10, r=10, t=40, b=10), legend_title_text="")


def _style(fig: go.Figure, height: int = 340) -> go.Figure:
    fig.update_layout(height=height, **LAYOUT)
    return fig


def trend_chart(t: pd.DataFrame, grain: str) -> go.Figure:
    if grain == "daily":
        fig = go.Figure()
        fig.add_bar(x=t["usage_date"], y=t["total_cost"], name="Daily cost", marker_color=GREY)
        fig.add_scatter(x=t["usage_date"], y=t["rolling_7d"], name="7-day average", line=dict(color=BLUE, width=2))
    else:
        colors = [GREY if p else BLUE for p in t["is_partial"]]
        fig = go.Figure(go.Bar(
            x=t["month_start"], y=t["total_cost"], marker_color=colors,
            hovertext=["partial month" if p else "" for p in t["is_partial"]], name="Monthly cost",
        ))
    fig.update_yaxes(title="Cost ($)", tickformat="$,.0f")
    return _style(fig)


def breakdown_bar(b: pd.DataFrame, dim: str, title: str) -> go.Figure:
    b = b.sort_values("total_cost")
    fig = px.bar(b, x="total_cost", y=dim, orientation="h", title=title,
                 color_discrete_sequence=[BLUE], text=b["share"].map(lambda s: f"{s:.0%}"))
    fig.update_xaxes(title="Cost ($)", tickformat="$,.0f")
    fig.update_yaxes(title="")
    return _style(fig, 300)


def change_bar(c: pd.DataFrame, dim: str, top: int = 10) -> go.Figure:
    c = c.head(top).sort_values("change_amount")
    fig = go.Figure(go.Bar(
        x=c["change_amount"], y=c[dim], orientation="h",
        marker_color=[RED if v > 0 else GREEN for v in c["change_amount"]],
    ))
    fig.update_xaxes(title="Change vs previous period ($)", tickformat="$,.0f")
    return _style(fig, 320)


def budget_vs_actual(v: pd.DataFrame, x: str) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=v[x], y=v["budget_amount"], name="Budget", marker_color=GREY)
    fig.add_bar(x=v[x], y=v["actual_cost"], name="Actual", marker_color=BLUE)
    fig.update_layout(barmode="group")
    fig.update_xaxes(type="category")  # labels like '2025-11' must not be parsed as dates
    fig.update_yaxes(title="$", tickformat="$,.0f")
    return _style(fig)
