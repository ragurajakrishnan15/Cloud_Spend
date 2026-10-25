"""Build the ANALYTICS / REPORTING layers from a loaded RAW source file, then run reconciliation checks.

    python -m cloudspend.ingestion.transform --billing-file cloud_billing_demo.csv --budgets-file budgets_demo.csv
Exit codes: 0 all checks pass, 1 failure, 2 usage/config error.
"""

from __future__ import annotations

import argparse
import re
import sys

from cloudspend.ingestion.snowflake_client import SQL_DIR, SnowflakeConfigError, get_connection

BUILD_SCRIPTS = (
    "03_create_dimensions.sql",
    "04_create_fact_tables.sql",
    "05_transformations.sql",
    "06_reporting_views.sql",
)
CHECK_SCRIPT = "07_data_quality_checks.sql"
_SAFE_FILE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def render_sql(text: str, billing_file: str, budgets_file: str) -> str:
    """Substitute file-name placeholders. Names are whitelisted to prevent SQL injection."""
    for name in (billing_file, budgets_file):
        if not _SAFE_FILE.fullmatch(name):
            raise ValueError(f"unsafe file name: {name!r}")
    return text.replace("{{SOURCE_FILE}}", billing_file).replace("{{BUDGET_FILE}}", budgets_file)


def build(conn, billing_file: str, budgets_file: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute("USE WAREHOUSE CLOUDSPEND_WH")
        cur.execute("USE DATABASE CLOUDSPEND_AI")
        for script in BUILD_SCRIPTS:
            sql = render_sql((SQL_DIR / script).read_text(encoding="utf-8"), billing_file, budgets_file)
            for _ in conn.execute_string(sql):
                pass
            print(f"ran {script}")
    finally:
        cur.close()


def run_checks(conn, billing_file: str, budgets_file: str) -> list[tuple]:
    cur = conn.cursor()
    try:
        cur.execute("USE WAREHOUSE CLOUDSPEND_WH")
        cur.execute(render_sql((SQL_DIR / CHECK_SCRIPT).read_text(encoding="utf-8"), billing_file, budgets_file))
        return cur.fetchall()
    finally:
        cur.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Transform RAW -> ANALYTICS/REPORTING and reconcile.")
    p.add_argument("--billing-file", default="cloud_billing_demo.csv")
    p.add_argument("--budgets-file", default="budgets_demo.csv")
    p.add_argument("--checks-only", action="store_true")
    args = p.parse_args(argv)
    try:
        with get_connection(database=None, schema=None) as conn:
            if not args.checks_only:
                build(conn, args.billing_file, args.budgets_file)
            rows = run_checks(conn, args.billing_file, args.budgets_file)
    except SnowflakeConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    failed = [r for r in rows if not r[3]]
    for name, expected, actual, passed in rows:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: expected={expected} actual={actual}")
    print(f"{len(rows) - len(failed)}/{len(rows)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
