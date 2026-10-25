"""Integration: builds ANALYTICS/REPORTING from the loaded demo file and requires every reconciliation check to pass."""

import pytest

from cloudspend.ingestion.snowflake_client import get_connection
from cloudspend.ingestion.transform import build, run_checks
from config.settings import load_snowflake_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not load_snowflake_settings().is_configured, reason="Snowflake credentials not set"),
]

BILLING, BUDGETS = "cloud_billing_demo.csv", "budgets_demo.csv"


def test_build_is_idempotent_and_all_checks_pass():
    with get_connection(database=None, schema=None) as conn:
        build(conn, BILLING, BUDGETS)
        first = run_checks(conn, BILLING, BUDGETS)
        build(conn, BILLING, BUDGETS)
        second = run_checks(conn, BILLING, BUDGETS)
    assert len(first) >= 15
    assert all(r[3] for r in first), [r for r in first if not r[3]]
    assert first == second
