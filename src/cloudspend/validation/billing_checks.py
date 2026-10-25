"""Validation rules for billing and budget data. Separates fatal errors from warnings.

    python -m cloudspend.validation.billing_checks data/generated/cloud_billing_demo.csv
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from cloudspend.data_generation.generate_billing import (
    BILLING_COLUMNS,
    BUDGET_COLUMNS,
    DEPARTMENTS,
    ENVIRONMENTS,
    REGIONS,
    SERVICES,
)

COST_TOLERANCE = 0.01  # absolute dollars; total_cost is rounded to cents


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    invalid_row_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [f"ERROR: {e}" for e in self.errors] + [f"WARN:  {w}" for w in self.warnings]
        return "\n".join(lines) if lines else "All checks passed."


def validate_billing(df: pd.DataFrame, start=None, end=None) -> ValidationReport:
    """Validate a billing frame. `start`/`end` optionally bound the expected date range."""
    rep = ValidationReport()
    missing = [c for c in BILLING_COLUMNS if c not in df.columns]
    if missing:
        rep.errors.append(f"missing columns: {missing}")
        return rep  # nothing else is meaningful

    bad = pd.Series(False, index=df.index)

    dup = df["record_id"].duplicated(keep=False)
    if dup.any():
        rep.errors.append(f"{int(dup.sum())} rows share a duplicate record_id")
        bad |= dup

    dates = pd.to_datetime(df["usage_date"], errors="coerce", format="ISO8601")
    bad_dates = dates.isna()
    if bad_dates.any():
        rep.errors.append(f"{int(bad_dates.sum())} rows have unparseable usage_date")
        bad |= bad_dates
    if start is not None and end is not None:
        out = (dates < pd.Timestamp(start)) | (dates > pd.Timestamp(end))
        if out.any():
            rep.errors.append(f"{int(out.sum())} rows outside expected range {start}..{end}")
            bad |= out

    for col in ("usage_units", "unit_cost", "total_cost"):
        num = pd.to_numeric(df[col], errors="coerce")
        nonnum = num.isna()
        neg = num < 0
        if nonnum.any():
            rep.errors.append(f"{int(nonnum.sum())} rows have non-numeric {col}")
            bad |= nonnum
        if neg.any():
            rep.errors.append(f"{int(neg.sum())} rows have negative {col}")
            bad |= neg

    expected = pd.to_numeric(df["usage_units"], errors="coerce") * pd.to_numeric(df["unit_cost"], errors="coerce")
    mismatch = (expected - pd.to_numeric(df["total_cost"], errors="coerce")).abs() > COST_TOLERANCE
    if mismatch.any():
        rep.errors.append(f"{int(mismatch.sum())} rows where total_cost != usage_units*unit_cost (tol {COST_TOLERANCE})")
        bad |= mismatch

    for col, allowed in (("department", DEPARTMENTS), ("environment", ENVIRONMENTS),
                         ("region", REGIONS), ("service_name", list(SERVICES))):
        unknown = ~df[col].isin(allowed)
        if unknown.any():
            rep.errors.append(f"{int(unknown.sum())} rows have unknown {col}: {sorted(df.loc[unknown, col].astype(str).unique())[:5]}")
            bad |= unknown

    required_null = df[["record_id", "resource_id", "department", "service_name"]].isna().any(axis=1)
    if required_null.any():
        rep.errors.append(f"{int(required_null.sum())} rows have null required values")
        bad |= required_null

    if (df["is_injected_anomaly"].astype(bool) != df["anomaly_type"].notna()).any():
        rep.warnings.append("is_injected_anomaly and anomaly_type are inconsistent")

    if (pd.to_numeric(df["total_cost"], errors="coerce") == 0).any():
        rep.warnings.append("some rows have zero total_cost")

    rep.invalid_row_count = int(bad.sum())
    return rep


def validate_budgets(budgets: pd.DataFrame, billing: pd.DataFrame | None = None) -> ValidationReport:
    rep = ValidationReport()
    missing = [c for c in BUDGET_COLUMNS if c not in budgets.columns]
    if missing:
        rep.errors.append(f"missing columns: {missing}")
        return rep
    if budgets.duplicated(["budget_month", "department", "service_name"]).any():
        rep.errors.append("budgets must be unique per month x department x service (grain violation)")
    if (pd.to_numeric(budgets["budget_amount"], errors="coerce") < 0).any():
        rep.errors.append("negative budget_amount")
    months = pd.to_datetime(budgets["budget_month"], errors="coerce")
    if months.isna().any() or (months.dt.day != 1).any():
        rep.errors.append("budget_month must be the first day of a month")
    if billing is not None:
        keys = set(map(tuple, budgets[["department", "service_name"]].drop_duplicates().to_numpy()))
        bkeys = set(map(tuple, billing[["department", "service_name"]].drop_duplicates().to_numpy()))
        if bkeys - keys:
            rep.warnings.append(f"{len(bkeys - keys)} dept/service pairs in billing have no budget")
    return rep


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate a billing CSV (and optional budgets CSV).")
    p.add_argument("billing_csv", type=Path)
    p.add_argument("--budgets-csv", type=Path)
    args = p.parse_args(argv)

    if not args.billing_csv.exists():
        print(f"ERROR: file not found: {args.billing_csv}")
        return 2
    billing = pd.read_csv(args.billing_csv)
    rep = validate_billing(billing)
    if args.budgets_csv:
        brep = validate_budgets(pd.read_csv(args.budgets_csv), billing)
        rep.errors += brep.errors
        rep.warnings += brep.warnings
    print(rep.summary())
    print(f"rows={len(billing):,} invalid_rows={rep.invalid_row_count}")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
