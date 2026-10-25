"""Pure pandas KPI calculations used by the dashboard (no Streamlit / Snowflake imports).

Input frames use the REPORTING-view column names, lower-cased:
  daily: usage_date, department_name, service_name, environment_name, region_name, total_cost, usage_units
  budget_variance: month_start, department_name, service_name, actual_cost, budget_amount, ...

KPI formulas (also in docs/architecture.md):
  change_amount = current - previous
  change_pct    = change_amount / previous            (None when previous is 0 or missing)
  previous period = the preceding whole calendar months for whole-month ranges, otherwise the immediately
                    preceding period with the same number of days
  budget/variance are defined only for ranges made of whole, fully-loaded calendar months
  variance = actual - budget (positive = over budget); variance_pct = variance / budget (None when budget is 0)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

import pandas as pd

DIMENSIONS = {
    "Department": "department_name",
    "Service": "service_name",
    "Environment": "environment_name",
    "Region": "region_name",
}


@dataclass(frozen=True)
class Filters:
    """Empty tuple for a dimension means 'all values'."""

    start: date
    end: date
    departments: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("start date must not be after end date")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def safe_pct(numerator: float | None, denominator: float | None) -> float | None:
    """numerator / denominator, or None when the denominator is missing or zero."""
    if numerator is None or denominator is None or pd.isna(numerator) or pd.isna(denominator):
        return None
    return None if denominator == 0 else float(numerator) / float(denominator)


def _is_whole_months(start: date, end: date) -> bool:
    return start.day == 1 and (end + timedelta(days=1)).day == 1


def previous_period(start: date, end: date) -> tuple[date, date]:
    """Comparison period. Whole calendar months compare with the same number of preceding whole months
    (November -> October; a quarter -> the previous quarter). Any other range compares with the immediately
    preceding range of equal length."""
    if _is_whole_months(start, end):
        n = (end.year - start.year) * 12 + end.month - start.month + 1
        return (pd.Timestamp(start) - pd.DateOffset(months=n)).date(), start - timedelta(days=1)
    days = (end - start).days + 1
    return start - timedelta(days=days), start - timedelta(days=1)


def apply_filters(daily: pd.DataFrame, f: Filters, *, env_region: bool = True) -> pd.DataFrame:
    """Filter daily rows. env_region=False ignores environment/region (used for budget comparisons)."""
    d = pd.to_datetime(daily["usage_date"])
    mask = (d >= pd.Timestamp(f.start)) & (d <= pd.Timestamp(f.end))
    if f.departments:
        mask &= daily["department_name"].isin(f.departments)
    if f.services:
        mask &= daily["service_name"].isin(f.services)
    if env_region:
        if f.environments:
            mask &= daily["environment_name"].isin(f.environments)
        if f.regions:
            mask &= daily["region_name"].isin(f.regions)
    return daily[mask]


def _days_in_month(month_start: pd.Timestamp) -> int:
    return month_start.days_in_month


def complete_months(daily: pd.DataFrame) -> set[pd.Timestamp]:
    """Months in which every calendar day has data (unfiltered data)."""
    d = pd.to_datetime(daily["usage_date"]).drop_duplicates()
    counts = d.groupby(d.dt.to_period("M").dt.to_timestamp()).count()
    return {m for m, n in counts.items() if n == _days_in_month(m)}


def period_kpis(daily: pd.DataFrame, f: Filters) -> dict:
    cur = float(apply_filters(daily, f)["total_cost"].sum())
    p_start, p_end = previous_period(f.start, f.end)
    pf = replace(f, start=p_start, end=p_end)
    prev_rows = apply_filters(daily, pf)
    prev = float(prev_rows["total_cost"].sum())
    all_dates = pd.to_datetime(daily["usage_date"])
    data_min, data_max = all_dates.min().date(), all_dates.max().date()
    prev_complete = p_start >= data_min and p_end <= data_max
    cur_complete = f.start >= data_min and f.end <= data_max
    has_prev = prev_complete and prev != 0
    return {
        "total_cost": cur,
        "previous_cost": prev if has_prev else None,
        "change_amount": cur - prev if has_prev else None,
        "change_pct": safe_pct(cur - prev, prev) if has_prev else None,
        "previous_start": p_start,
        "previous_end": p_end,
        "previous_period_covered": prev_complete,
        "selected_period_covered": cur_complete,
        "days": f.days,
    }


def whole_months_in_range(start: date, end: date, complete: set[pd.Timestamp]) -> list[pd.Timestamp] | None:
    """Months making up [start, end] exactly, or None if the range is not whole months / any month incomplete."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    if s.day != 1 or e != e + pd.offsets.MonthEnd(0):
        return None
    months = list(pd.date_range(s, e, freq="MS"))
    return months if months and all(m in complete for m in months) else None


def budget_kpis(daily: pd.DataFrame, budget_variance: pd.DataFrame, f: Filters) -> dict:
    """Budget vs actual for the selected range. Budgets exist only per month x department x service, so
    environment/region filters are ignored here; `reason` explains when no budget figure can be given."""
    months = whole_months_in_range(f.start, f.end, complete_months(daily))
    if months is None:
        return {"available": False, "reason": "Budgets are monthly: select whole, fully-loaded calendar months."}
    bv = budget_variance[pd.to_datetime(budget_variance["month_start"]).isin(months)]
    if f.departments:
        bv = bv[bv["department_name"].isin(f.departments)]
    if f.services:
        bv = bv[bv["service_name"].isin(f.services)]
    actual, budget = float(bv["actual_cost"].sum()), float(bv["budget_amount"].sum())
    return {
        "available": True,
        "actual": actual,
        "budget": budget,
        "variance": actual - budget,
        "variance_pct": safe_pct(actual - budget, budget),
        "ignores_env_region": bool(f.environments or f.regions),
    }


def breakdown(daily: pd.DataFrame, f: Filters, dim: str) -> pd.DataFrame:
    """Total cost by one dimension column for the selected filters, with share of total."""
    g = apply_filters(daily, f).groupby(dim, as_index=False)["total_cost"].sum()
    total = g["total_cost"].sum()
    g["share"] = g["total_cost"] / total if total else None
    return g.sort_values("total_cost", ascending=False, ignore_index=True)


def top_contributors(daily: pd.DataFrame, f: Filters, dim: str) -> pd.DataFrame:
    """Per-member change vs the previous period, sorted by absolute change."""
    p_start, p_end = previous_period(f.start, f.end)
    cur = apply_filters(daily, f).groupby(dim)["total_cost"].sum().rename("current_cost")
    prev = apply_filters(daily, replace(f, start=p_start, end=p_end)).groupby(dim)["total_cost"].sum()
    out = pd.concat([cur, prev.rename("previous_cost")], axis=1).fillna(0.0).reset_index()
    out["change_amount"] = out["current_cost"] - out["previous_cost"]
    out["change_pct"] = [safe_pct(c, p) for c, p in zip(out["change_amount"], out["previous_cost"], strict=True)]
    return out.reindex(out["change_amount"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def trend(daily: pd.DataFrame, f: Filters, grain: str = "daily") -> pd.DataFrame:
    """Cost over time. Monthly rows carry is_partial (incomplete month in the *data*, not just the filter)."""
    rows = apply_filters(daily, f).copy()
    rows["usage_date"] = pd.to_datetime(rows["usage_date"])
    if grain == "daily":
        out = rows.groupby("usage_date", as_index=False)["total_cost"].sum()
        out["rolling_7d"] = out["total_cost"].rolling(7, min_periods=7).mean()
        return out
    if grain != "monthly":
        raise ValueError("grain must be 'daily' or 'monthly'")
    rows["month_start"] = rows["usage_date"].dt.to_period("M").dt.to_timestamp()
    out = rows.groupby("month_start", as_index=False)["total_cost"].sum()
    complete = complete_months(daily)
    out["is_partial"] = ~out["month_start"].isin(complete)
    return out


def complete_months_in_range(daily: pd.DataFrame, start: date, end: date) -> list[pd.Timestamp]:
    """Fully-loaded calendar months lying entirely inside [start, end], in order."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return sorted(m for m in complete_months(daily) if m >= s and m + pd.offsets.MonthEnd(0) <= e)


def filter_model_output(df: pd.DataFrame, f: Filters, date_col: str | None) -> pd.DataFrame:
    """Apply dimension filters (and the date range, when date_col is given) to a model-output frame."""
    if df.empty:
        return df
    mask = pd.Series(True, index=df.index)
    if date_col:
        d = pd.to_datetime(df[date_col])
        mask = (d >= pd.Timestamp(f.start)) & (d <= pd.Timestamp(f.end))
    for values, col in (
        (f.departments, "department_name"),
        (f.services, "service_name"),
        (f.environments, "environment_name"),
        (f.regions, "region_name"),
    ):
        if values and col in df:
            mask &= df[col].isin(values)
    return df[mask]


def anomaly_summary(anomalies: pd.DataFrame) -> dict:
    """Count and total flagged spend. A flag is statistical evidence, not a confirmed problem."""
    if anomalies.empty:
        return {"count": 0, "flagged_cost": 0.0}
    unique = anomalies.drop_duplicates("record_id")
    return {"count": len(unique), "flagged_cost": float(unique["observed_cost"].astype(float).sum())}


def variance_by(budget_variance: pd.DataFrame, dims: list[str]) -> pd.DataFrame:
    """Aggregate actual/budget over any dimensions of the variance frame and recompute variance (never average pcts)."""
    g = budget_variance.groupby(dims, as_index=False)[["actual_cost", "budget_amount"]].sum()
    g["variance_amount"] = g["actual_cost"] - g["budget_amount"]
    g["variance_pct"] = [safe_pct(v, b) for v, b in zip(g["variance_amount"], g["budget_amount"], strict=True)]
    return g
