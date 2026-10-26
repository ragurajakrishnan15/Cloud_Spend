"""Page 4 - Spend Forecasting (reads stored forecasts and backtest metrics)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # `cloudspend` / `config` importable without pip install

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cloudspend import data_access
from cloudspend.analytics.forecasting import MIN_TRAIN_DAYS, MODEL_BASELINE, MODEL_ETS, month_projections
from components import charts
from components.common import setup_page
from components.kpi_cards import table as show_table

ctx = setup_page("Spend Forecasting")
st.caption("Forecasts are precomputed at total / department grain, so the sidebar date, service, environment and region "
           "filters do not apply on this page.")

try:
    fc = data_access.load_forecast()
    evaluation = data_access.load_model_evaluation()
except Exception as exc:
    st.error(f"Could not load forecasts ({type(exc).__name__}).")
    st.stop()

if fc.empty:
    st.info("No forecasts yet. Run `python -m cloudspend.analytics.run_models` to compute them.")
    st.stop()

fc["forecast_date"] = pd.to_datetime(fc["forecast_date"])
scopes = ["total", *sorted(set(fc["scope_value"]) - {"total"})]
scope = st.selectbox("Scope", scopes)
fs = fc[fc["scope_value"] == scope]
ets, naive = fs[fs["model_name"] == MODEL_ETS].sort_values("forecast_date"), fs[fs["model_name"] == MODEL_BASELINE].sort_values("forecast_date")
if ets.empty:
    st.warning(f"No forecast for '{scope}': at least {MIN_TRAIN_DAYS} days of history are required.")
    st.stop()

daily = ctx.daily if scope == "total" else ctx.daily[ctx.daily["department_name"] == scope]
history = daily.groupby(pd.to_datetime(daily["usage_date"]))["total_cost"].sum().sort_index()
trained_through = pd.to_datetime(ets["trained_through_date"].iloc[0])
horizon = len(ets)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Model", f"ETS {ets['model_version'].iloc[0]}", help=f"{MODEL_ETS}: additive error, damped additive trend, additive weekly seasonality")
m2.metric("Trained through", f"{trained_through.date()}")
m3.metric("Horizon", f"{horizon} days")
m4.metric("Interval", "80% prediction")

show_naive = st.checkbox("Show seasonal-naive baseline", value=False)
recent = history[history.index >= trained_through - pd.Timedelta(days=90)]
fig = go.Figure()
fig.add_scatter(x=recent.index, y=recent.values, name="Actual", line=dict(color=charts.GREY, width=2))
fig.add_scatter(x=ets["forecast_date"], y=ets["upper_bound"].astype(float), line=dict(width=0), showlegend=False, hoverinfo="skip")
fig.add_scatter(x=ets["forecast_date"], y=ets["lower_bound"].astype(float), line=dict(width=0), fill="tonexty",
                fillcolor="rgba(37,99,235,0.15)", name="80% interval", hoverinfo="skip")
fig.add_scatter(x=ets["forecast_date"], y=ets["forecast_cost"].astype(float), name="ETS forecast", line=dict(color=charts.BLUE, width=2))
if show_naive and not naive.empty:
    fig.add_scatter(x=naive["forecast_date"], y=naive["forecast_cost"].astype(float), name="Seasonal naive",
                    line=dict(color=charts.GREEN, dash="dot"))
fig.update_layout(template="plotly_white", height=380, margin=dict(l=10, r=10, t=10, b=10),
                  yaxis_title="Daily cost ($)", yaxis_tickformat="$,.0f", legend_title_text="")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Month projection and budget")
budgets = ctx.budget_variance if scope == "total" else ctx.budget_variance[ctx.budget_variance["department_name"] == scope]
bud = budgets.groupby(pd.to_datetime(budgets["month_start"]))["budget_amount"].sum().to_dict()
rows = []
for p in month_projections(history, ets.set_index("forecast_date")["forecast_cost"].astype(float), bud):
    rows.append({"Month": p["month"].strftime("%Y-%m"), "Actual to date": p["actual_to_date"],
                 "Forecast (remaining days)": p["forecast_remaining"],
                 "Projected month": p.get("projected"), "Budget": p.get("budget"),
                 "Projected variance": p.get("variance"), "Variance %": p.get("variance_pct")})
proj = pd.DataFrame(rows)
show_table(proj, money_cols=("Actual to date", "Forecast (remaining days)", "Projected month", "Budget",
                             "Projected variance"), pct_cols=("Variance %",))
st.caption("Projected month = actual to date + forecast for remaining days. Months without a loaded budget show no variance. "
           "Month totals carry no interval (summing daily bounds would be invalid); read them with the daily band above.")

st.subheader("Backtest and baseline comparison")
bt = evaluation[(evaluation["model_family"] == "forecast") & (evaluation["scope"] == scope)]
if bt.empty:
    st.write("No backtest stored for this scope.")
else:
    t = bt.pivot(index="model_name", columns="metric_name", values="metric_value")
    bt_view = t[["mae", "wape", "interval_coverage", "n_folds"]].rename(columns={
        "mae": "MAE ($/day)", "wape": "WAPE", "interval_coverage": "80% interval coverage", "n_folds": "Folds"})
    bt_view.index.name = "Model"
    show_table(bt_view.reset_index(), money_cols=("MAE ($/day)",), pct_cols=("WAPE", "80% interval coverage"),
               column_config={"Folds": st.column_config.NumberColumn(format="%d")})
    if {MODEL_ETS, MODEL_BASELINE} <= set(t.index) and t.loc[MODEL_BASELINE, "wape"]:
        gain = 1 - t.loc[MODEL_ETS, "wape"] / t.loc[MODEL_BASELINE, "wape"]
        st.write(f"On rolling-origin backtests, ETS WAPE is {abs(gain) * 100:.1f}% {'lower' if gain > 0 else 'higher'} "
                 "than the seasonal-naive baseline's.")
    st.caption("Rolling-origin backtest: expanding windows, 30-day test blocks, trained only on earlier data. "
               "WAPE = sum|error| / sum|actual|. Synthetic data with smooth trend and weekly seasonality favours ETS; "
               "the training series includes the injected anomalies. Details: `docs/model_evaluation.md`.")
