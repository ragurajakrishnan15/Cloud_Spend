"""Local-mode equivalents of the REPORTING views, built from the CSVs with pandas.

These mirror VW_DAILY_CLOUD_SPEND and VW_BUDGET_VARIANCE (an integration test checks parity with Snowflake).
"""

from __future__ import annotations

import pandas as pd

DAILY_KEYS = ["usage_date", "department_name", "service_name", "environment_name", "region_name"]


def build_daily(billing: pd.DataFrame) -> pd.DataFrame:
    df = billing.rename(
        columns={
            "department": "department_name",
            "environment": "environment_name",
            "region": "region_name",
        }
    ).copy()
    df["usage_date"] = pd.to_datetime(df["usage_date"])
    out = df.groupby(DAILY_KEYS, as_index=False).agg(
        total_cost=("total_cost", "sum"), usage_units=("usage_units", "sum"), record_count=("record_id", "count")
    )
    out["year_month"] = out["usage_date"].dt.strftime("%Y-%m")
    out["is_weekend"] = out["usage_date"].dt.dayofweek >= 5
    return out


def build_budget_variance(daily: pd.DataFrame, budgets: pd.DataFrame) -> pd.DataFrame:
    d = daily.assign(month_start=pd.to_datetime(daily["usage_date"]).dt.to_period("M").dt.to_timestamp())
    actual = d.groupby(["month_start", "department_name", "service_name"], as_index=False)["total_cost"].sum()
    actual = actual.rename(columns={"total_cost": "actual_cost"})
    b = budgets.rename(
        columns={"budget_month": "month_start", "department": "department_name"}
    )[["month_start", "department_name", "service_name", "budget_amount"]].copy()
    b["month_start"] = pd.to_datetime(b["month_start"])
    out = actual.merge(b, on=["month_start", "department_name", "service_name"], how="outer")
    out[["actual_cost", "budget_amount"]] = out[["actual_cost", "budget_amount"]].fillna(0.0)
    out["year_month"] = out["month_start"].dt.strftime("%Y-%m")
    out["variance_amount"] = out["actual_cost"] - out["budget_amount"]
    out["variance_pct"] = out["variance_amount"] / out["budget_amount"].where(out["budget_amount"] != 0)
    out["is_over_budget"] = out["actual_cost"] > out["budget_amount"]
    return out
