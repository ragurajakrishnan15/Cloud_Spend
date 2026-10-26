"""Run anomaly detection, forecasting and recommendation rules, then persist the results.

    python -m cloudspend.analytics.run_models                    # Snowflake source if configured, writes results back
    python -m cloudspend.analytics.run_models --source csv       # local CSVs only (writes local files, no Snowflake)
    python -m cloudspend.analytics.run_models --no-write         # compute and write local files only

Ground-truth labels are loaded separately and used only for offline evaluation.
Exit codes: 0 success, 1 failure, 2 config/usage error.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import pandas as pd

from cloudspend.analytics import anomaly_detection as ad
from cloudspend.analytics import forecasting as fc
from cloudspend.analytics import model_store as store
from cloudspend.analytics import optimization as opt
from cloudspend.analytics.local_views import build_budget_variance
from cloudspend.ingestion.snowflake_client import SnowflakeConfigError, get_connection
from config.settings import GENERATED_DIR, load_snowflake_settings

RECORD_COLS = ["record_id", "usage_date", "resource_id", "department_name", "service_name", "environment_name",
               "region_name", "usage_units", "total_cost"]

RECORDS_SQL = """
SELECT f.RECORD_ID, d.FULL_DATE, f.RESOURCE_ID, dep.DEPARTMENT_NAME, s.SERVICE_NAME, e.ENVIRONMENT_NAME,
       g.REGION_NAME, f.USAGE_UNITS, f.TOTAL_COST
FROM CLOUDSPEND_AI.ANALYTICS.FACT_CLOUD_COST f
JOIN CLOUDSPEND_AI.ANALYTICS.DIM_DATE d ON d.DATE_KEY = f.DATE_KEY
JOIN CLOUDSPEND_AI.ANALYTICS.DIM_DEPARTMENT dep ON dep.DEPARTMENT_KEY = f.DEPARTMENT_KEY
JOIN CLOUDSPEND_AI.ANALYTICS.DIM_SERVICE s ON s.SERVICE_KEY = f.SERVICE_KEY
JOIN CLOUDSPEND_AI.ANALYTICS.DIM_ENVIRONMENT e ON e.ENVIRONMENT_KEY = f.ENVIRONMENT_KEY
JOIN CLOUDSPEND_AI.ANALYTICS.DIM_REGION g ON g.REGION_KEY = f.REGION_KEY
"""


def _frame(cur, sql: str, columns: list[str]) -> pd.DataFrame:
    cur.execute(sql)
    df = pd.DataFrame(cur.fetchall(), columns=columns)
    for c in df.columns:
        if df[c].map(lambda v: type(v).__name__).eq("Decimal").any():
            df[c] = df[c].astype(float)
    return df


def load_from_csv(billing: Path, budgets: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(billing, parse_dates=["usage_date"])
    records = raw.rename(columns={"department": "department_name", "environment": "environment_name",
                                  "region": "region_name"})[RECORD_COLS]
    labels = raw[["record_id", "is_injected_anomaly", "anomaly_type"]]
    return records, labels, pd.read_csv(budgets)


def load_from_snowflake(conn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cur = conn.cursor()
    try:
        cur.execute("USE WAREHOUSE CLOUDSPEND_WH")
        records = _frame(cur, RECORDS_SQL, RECORD_COLS)
        records["usage_date"] = pd.to_datetime(records["usage_date"])
        labels = _frame(cur, "SELECT RECORD_ID, IS_INJECTED_ANOMALY, ANOMALY_TYPE FROM CLOUDSPEND_AI.ANALYTICS.ANOMALY_GROUND_TRUTH",
                        ["record_id", "is_injected_anomaly", "anomaly_type"])
        budgets = _frame(cur, "SELECT b.BUDGET_MONTH, dep.DEPARTMENT_NAME, s.SERVICE_NAME, b.BUDGET_AMOUNT "
                              "FROM CLOUDSPEND_AI.ANALYTICS.FACT_BUDGET b "
                              "JOIN CLOUDSPEND_AI.ANALYTICS.DIM_DEPARTMENT dep ON dep.DEPARTMENT_KEY = b.DEPARTMENT_KEY "
                              "JOIN CLOUDSPEND_AI.ANALYTICS.DIM_SERVICE s ON s.SERVICE_KEY = b.SERVICE_KEY",
                         ["budget_month", "department", "service_name", "budget_amount"])
    finally:
        cur.close()
    return records, labels, budgets


def daily_from_records(records: pd.DataFrame) -> pd.DataFrame:
    keys = ["usage_date", "department_name", "service_name", "environment_name", "region_name"]
    return records.groupby(keys, as_index=False).agg(total_cost=("total_cost", "sum"), usage_units=("usage_units", "sum"))


def compute(records: pd.DataFrame, labels: pd.DataFrame, budgets: pd.DataFrame, run_id: str | None = None) -> dict:
    """Run all three stages and return view-shaped output frames (pure; no I/O)."""
    run_id = run_id or str(uuid.uuid4())
    created = store.now_utc()

    an = ad.run_pipeline(records, labels)
    rows = ad.to_anomaly_rows(an)
    ctx = records.set_index("record_id")[["usage_date", "department_name", "service_name", "environment_name",
                                          "region_name", "resource_id"]]
    anomalies = rows.join(ctx, on="record_id")

    series: dict[str, tuple[str, pd.Series]] = {"total": ("total", records.groupby("usage_date")["total_cost"].sum())}
    for dep, g in records.groupby("department_name"):
        series[str(dep)] = ("department", g.groupby("usage_date")["total_cost"].sum())
    fr = fc.run_pipeline(series)

    daily = daily_from_records(records)
    bv = build_budget_variance(daily, budgets)
    recs = opt.generate_recommendations(daily, bv, anomalies)

    evaluation = store.evaluation_rows(an, fr, run_id, created)
    return {"run_id": run_id, "created": created, "anomaly_result": an, "forecast_result": fr,
            "anomalies": anomalies, "forecast": fr.forecasts, "recommendations": recs, "evaluation": evaluation}


def local_view_frames(out: dict) -> dict[str, pd.DataFrame]:
    """Shape results like the REPORTING views for local-mode files."""
    created = out["created"]
    a = out["anomalies"].assign(created_at=created)
    a = a[["record_id", "usage_date", "department_name", "service_name", "environment_name", "region_name",
           "resource_id", "detection_method", "method_version", "observed_cost", "baseline_cost", "abs_diff",
           "pct_diff", "anomaly_score", "severity", "reason", "created_at"]]
    r = out["recommendations"].copy()
    r["estimated_savings_display"] = [("Requires investigation" if pd.isna(v) else f"{v:,.2f}") for v in r["estimated_savings"]]
    r["created_at"] = created
    return {"anomalies": a, "forecast": out["forecast"].assign(created_at=created), "recommendations": r,
            "evaluation": out["evaluation"]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run anomaly detection, forecasting and recommendation rules.")
    p.add_argument("--source", choices=["snowflake", "csv"])
    p.add_argument("--no-write", action="store_true", help="skip writing to Snowflake (local files are always written)")
    p.add_argument("--billing-csv", type=Path, default=GENERATED_DIR / "cloud_billing_demo.csv")
    p.add_argument("--budgets-csv", type=Path, default=GENERATED_DIR / "budgets_demo.csv")
    args = p.parse_args(argv)
    source = args.source or ("snowflake" if load_snowflake_settings().is_configured else "csv")

    try:
        conn_cm = get_connection(database=None, schema=None) if source == "snowflake" else None
        if conn_cm:
            with conn_cm as conn:
                records, labels, budgets = load_from_snowflake(conn)
                out = compute(records, labels, budgets)
                _report(out)
                frames = local_view_frames(out)
                store.save_local(frames)
                if not args.no_write:
                    counts = store.write_snowflake(conn, out["anomalies"], out["forecast"], out["recommendations"],
                                                   out["evaluation"], out["created"])
                    print("written to Snowflake:", counts)
        else:
            records, labels, budgets = load_from_csv(args.billing_csv, args.budgets_csv)
            out = compute(records, labels, budgets)
            _report(out)
            store.save_local(local_view_frames(out))
    except SnowflakeConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"local files written to {store.OUTPUT_DIR}")
    return 0


def _report(out: dict) -> None:
    an, fr = out["anomaly_result"], out["forecast_result"]
    print(f"run_id={out['run_id']}  split_date={an.params['split_date']}")
    for method, periods in an.metrics.items():
        h = periods["holdout"]
        print(f"  {method:20s} holdout: precision={h['precision']} recall={h['recall']} f1={h['f1']} tp={h['tp']} fp={h['fp']} fn={h['fn']}")
    print(f"  anomaly rows={len(out['anomalies'])} forecast rows={len(out['forecast'])} recommendations={len(out['recommendations'])}")
    for w in fr.warnings:
        print("  WARNING:", w)


if __name__ == "__main__":
    sys.exit(main())
