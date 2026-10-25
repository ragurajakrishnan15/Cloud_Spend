"""Validate and load billing + budget CSVs into Snowflake RAW (idempotent).

    python -m cloudspend.ingestion.load_csv --billing data/generated/cloud_billing_demo.csv \
        --budgets data/generated/budgets_demo.csv [--setup]

Idempotency: data is PUT to an internal stage, COPY'd into a temp table, then MERGEd
into RAW on its logical key, so re-running the same file updates rows rather than duplicating.
Exit codes: 0 success, 1 validation/reconciliation failure, 2 usage/config error.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from cloudspend.ingestion.snowflake_client import (
    SnowflakeConfigError,
    get_connection,
    setup_warehouse,
)
from cloudspend.validation.billing_checks import (
    ValidationReport,
    validate_billing,
    validate_budgets,
)

COPY_FORMAT = (
    "TYPE=CSV SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='\"' NULL_IF=('') EMPTY_FIELD_AS_NULL=TRUE"
)

BILLING_COLS = (
    "RECORD_ID", "USAGE_DATE", "DEPARTMENT", "SERVICE_NAME", "ENVIRONMENT", "REGION", "RESOURCE_ID",
    "USAGE_UNITS", "UNIT_COST", "TOTAL_COST", "IS_INJECTED_ANOMALY", "ANOMALY_TYPE", "GENERATED_AT",
)
BUDGET_COLS = ("BUDGET_MONTH", "DEPARTMENT", "SERVICE_NAME", "BUDGET_AMOUNT")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _stage_and_copy(cur, path: Path, temp_table: str, col_ddl: str) -> int:
    """PUT file to the internal stage and COPY into a temp table (all VARCHAR-typed -> typed in MERGE)."""
    cur.execute(f"CREATE OR REPLACE TEMPORARY TABLE {temp_table} ({col_ddl})")
    # Windows paths: Snowflake wants forward slashes in file:// URIs.
    uri = path.resolve().as_posix()
    cur.execute(f"PUT 'file://{uri}' @CLOUDSPEND_AI.RAW.INGEST_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE")
    cur.execute(
        f"COPY INTO {temp_table} FROM @CLOUDSPEND_AI.RAW.INGEST_STAGE/{path.name}.gz "
        f"FILE_FORMAT=({COPY_FORMAT}) ON_ERROR=ABORT_STATEMENT"
    )
    cur.execute(f"SELECT COUNT(*) FROM {temp_table}")
    return int(cur.fetchone()[0])


def _record_issues(cur, run_id: str, report: ValidationReport) -> None:
    rows = [(run_id, "ERROR", m[:2000]) for m in report.errors] + [
        (run_id, "WARNING", m[:2000]) for m in report.warnings
    ]
    if rows:
        cur.executemany(
            "INSERT INTO CLOUDSPEND_AI.RAW.DATA_QUALITY_ISSUES (RUN_ID, SEVERITY, MESSAGE) VALUES (%s,%s,%s)", rows
        )


def load(billing_path: Path, budgets_path: Path | None, setup: bool = False) -> int:
    billing = pd.read_csv(billing_path)
    report = validate_billing(billing)
    budgets = None
    if budgets_path:
        budgets = pd.read_csv(budgets_path)
        brep = validate_budgets(budgets, billing)
        report.errors += brep.errors
        report.warnings += brep.warnings

    src_rows = len(billing)
    src_sum = Decimal(str(round(float(billing["total_cost"].sum()), 2)))
    run_id = str(uuid.uuid4())
    started = _now()

    with get_connection(database=None, schema=None) as conn:
        cur = conn.cursor()
        try:
            if setup:
                print("setup:", ", ".join(setup_warehouse(conn)))
            cur.execute("USE SCHEMA CLOUDSPEND_AI.RAW")
            if _has_warehouse(conn):
                cur.execute("USE WAREHOUSE CLOUDSPEND_WH")
            cur.execute(
                "INSERT INTO CLOUDSPEND_AI.RAW.INGESTION_RUNS (RUN_ID, FILE_NAME, STATUS, ROWS_IN_FILE, "
                "SOURCE_COST_SUM, STARTED_AT) VALUES (%s,%s,'RUNNING',%s,%s,%s)",
                (run_id, billing_path.name, src_rows, src_sum, started),
            )
            _record_issues(cur, run_id, report)

            if not report.ok:
                _finish(cur, run_id, "FAILED", None, None, "; ".join(report.errors)[:2000])
                print(report.summary())
                return 1

            n_staged = _stage_and_copy(cur, billing_path, "TMP_BILLING", ", ".join(f"{c} VARCHAR" for c in BILLING_COLS))
            cur.execute(_merge_billing_sql(), {"f": billing_path.name})
            cur.execute(
                "SELECT COUNT(*), SUM(TOTAL_COST) FROM CLOUDSPEND_AI.RAW.CLOUD_BILLING_RAW WHERE SOURCE_FILE=%s",
                (billing_path.name,),
            )
            raw_rows, raw_sum = cur.fetchone()
            raw_sum = Decimal(raw_sum or 0)

            if budgets_path:
                _stage_and_copy(cur, budgets_path, "TMP_BUDGETS", ", ".join(f"{c} VARCHAR" for c in BUDGET_COLS))
                cur.execute(_merge_budgets_sql(), {"f": budgets_path.name})
                cur.execute(
                    "SELECT COUNT(*), SUM(BUDGET_AMOUNT) FROM CLOUDSPEND_AI.RAW.BUDGETS_RAW WHERE SOURCE_FILE=%s",
                    (budgets_path.name,),
                )
                b_rows, b_sum = cur.fetchone()
                budget_problems = []
                if b_rows != len(budgets):
                    budget_problems.append(f"raw budget rows {b_rows} != file rows {len(budgets)}")
                file_budget_sum = Decimal(str(round(float(budgets["budget_amount"].sum()), 2)))
                if abs(Decimal(b_sum or 0) - file_budget_sum) > Decimal("0.01"):
                    budget_problems.append(f"raw budget sum {b_sum} != file budget sum {file_budget_sum}")

            problems = list(budget_problems) if budgets_path else []
            if n_staged != src_rows:
                problems.append(f"staged rows {n_staged} != file rows {src_rows}")
            if raw_rows != src_rows:
                problems.append(f"raw rows {raw_rows} != file rows {src_rows}")
            if abs(raw_sum - src_sum) > Decimal("0.01"):
                problems.append(f"raw cost {raw_sum} != file cost {src_sum}")
            if problems:
                _finish(cur, run_id, "FAILED", raw_rows, raw_sum, "reconciliation: " + "; ".join(problems))
                print("RECONCILIATION FAILED:", *problems, sep="\n  ")
                return 1

            _finish(cur, run_id, "SUCCESS", raw_rows, raw_sum, None)
            print(report.summary())
            print(f"OK run_id={run_id} rows={raw_rows:,} cost={raw_sum:,} (file cost {src_sum:,})")
            return 0
        except Exception as exc:  # record failure, then re-raise as nonzero exit
            try:
                _finish(cur, run_id, "FAILED", None, None, f"{type(exc).__name__}: {str(exc)[:500]}")
            except Exception:
                pass
            raise
        finally:
            cur.close()


def _has_warehouse(conn) -> bool:
    cur = conn.cursor()
    try:
        cur.execute("SHOW WAREHOUSES LIKE 'CLOUDSPEND_WH'")
        return bool(cur.fetchall())
    finally:
        cur.close()


def _finish(cur, run_id, status, rows_loaded, loaded_sum, error) -> None:
    cur.execute(
        "UPDATE CLOUDSPEND_AI.RAW.INGESTION_RUNS SET STATUS=%s, ROWS_LOADED=%s, LOADED_COST_SUM=%s, "
        "ERROR_SUMMARY=%s, FINISHED_AT=%s WHERE RUN_ID=%s",
        (status, rows_loaded, loaded_sum, error, _now(), run_id),
    )


def _merge_billing_sql() -> str:
    return """
MERGE INTO CLOUDSPEND_AI.RAW.CLOUD_BILLING_RAW t
USING (
  SELECT RECORD_ID, TO_DATE(USAGE_DATE) USAGE_DATE, DEPARTMENT, SERVICE_NAME, ENVIRONMENT, REGION, RESOURCE_ID,
         TO_NUMBER(USAGE_UNITS,18,2) USAGE_UNITS, TO_NUMBER(UNIT_COST,18,6) UNIT_COST,
         TO_NUMBER(TOTAL_COST,18,2) TOTAL_COST, TO_BOOLEAN(IS_INJECTED_ANOMALY) IS_INJECTED_ANOMALY,
         ANOMALY_TYPE, TRY_TO_TIMESTAMP_NTZ(REPLACE(GENERATED_AT,'Z','')) GENERATED_AT
  FROM TMP_BILLING
) s ON t.RECORD_ID = s.RECORD_ID
WHEN MATCHED THEN UPDATE SET USAGE_DATE=s.USAGE_DATE, DEPARTMENT=s.DEPARTMENT, SERVICE_NAME=s.SERVICE_NAME,
  ENVIRONMENT=s.ENVIRONMENT, REGION=s.REGION, RESOURCE_ID=s.RESOURCE_ID, USAGE_UNITS=s.USAGE_UNITS,
  UNIT_COST=s.UNIT_COST, TOTAL_COST=s.TOTAL_COST, IS_INJECTED_ANOMALY=s.IS_INJECTED_ANOMALY,
  ANOMALY_TYPE=s.ANOMALY_TYPE, GENERATED_AT=s.GENERATED_AT, SOURCE_FILE=%(f)s, LOADED_AT=CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (RECORD_ID, USAGE_DATE, DEPARTMENT, SERVICE_NAME, ENVIRONMENT, REGION, RESOURCE_ID,
  USAGE_UNITS, UNIT_COST, TOTAL_COST, IS_INJECTED_ANOMALY, ANOMALY_TYPE, GENERATED_AT, SOURCE_FILE)
VALUES (s.RECORD_ID, s.USAGE_DATE, s.DEPARTMENT, s.SERVICE_NAME, s.ENVIRONMENT, s.REGION, s.RESOURCE_ID,
  s.USAGE_UNITS, s.UNIT_COST, s.TOTAL_COST, s.IS_INJECTED_ANOMALY, s.ANOMALY_TYPE, s.GENERATED_AT, %(f)s)
"""


def _merge_budgets_sql() -> str:
    return """
MERGE INTO CLOUDSPEND_AI.RAW.BUDGETS_RAW t
USING (SELECT TO_DATE(BUDGET_MONTH) BUDGET_MONTH, DEPARTMENT, SERVICE_NAME, TO_NUMBER(BUDGET_AMOUNT,18,2) BUDGET_AMOUNT
       FROM TMP_BUDGETS) s
ON t.BUDGET_MONTH=s.BUDGET_MONTH AND t.DEPARTMENT=s.DEPARTMENT AND t.SERVICE_NAME=s.SERVICE_NAME
   AND t.SOURCE_FILE=%(f)s
WHEN MATCHED THEN UPDATE SET BUDGET_AMOUNT=s.BUDGET_AMOUNT, SOURCE_FILE=%(f)s, LOADED_AT=CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (BUDGET_MONTH, DEPARTMENT, SERVICE_NAME, BUDGET_AMOUNT, SOURCE_FILE)
VALUES (s.BUDGET_MONTH, s.DEPARTMENT, s.SERVICE_NAME, s.BUDGET_AMOUNT, %(f)s)
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Load synthetic billing CSVs into Snowflake RAW.")
    p.add_argument("--billing", type=Path, required=True)
    p.add_argument("--budgets", type=Path)
    p.add_argument("--setup", action="store_true", help="run sql/01 and sql/02 first")
    args = p.parse_args(argv)
    for f in (args.billing, args.budgets):
        if f and not f.exists():
            print(f"ERROR: file not found: {f}")
            return 2
    try:
        return load(args.billing, args.budgets, args.setup)
    except SnowflakeConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {str(exc)[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
