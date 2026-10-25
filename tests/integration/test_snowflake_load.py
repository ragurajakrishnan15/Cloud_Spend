"""Integration tests: skipped unless SNOWFLAKE_ACCOUNT/USER are configured. Uses data/sample (dev profile)."""

from decimal import Decimal

import pandas as pd
import pytest

from cloudspend.ingestion.load_csv import load
from cloudspend.ingestion.snowflake_client import get_connection
from config.settings import SAMPLE_DIR, load_snowflake_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not load_snowflake_settings().is_configured,
                       reason="Snowflake credentials not set (see .env.example)"),
]

BILLING = SAMPLE_DIR / "cloud_billing_dev.csv"
BUDGETS = SAMPLE_DIR / "budgets_dev.csv"


def _scalar(sql):
    with get_connection() as conn:
        return conn.cursor().execute(sql).fetchone()


def test_load_is_idempotent_and_reconciles():
    assert load(BILLING, BUDGETS, setup=True) == 0
    first = _scalar("SELECT COUNT(*), SUM(TOTAL_COST) FROM CLOUDSPEND_AI.RAW.CLOUD_BILLING_RAW WHERE SOURCE_FILE='cloud_billing_dev.csv'")
    assert load(BILLING, BUDGETS) == 0
    second = _scalar("SELECT COUNT(*), SUM(TOTAL_COST) FROM CLOUDSPEND_AI.RAW.CLOUD_BILLING_RAW WHERE SOURCE_FILE='cloud_billing_dev.csv'")
    src = pd.read_csv(BILLING)
    assert first == second
    assert first[0] == len(src)
    assert abs(Decimal(first[1]) - Decimal(str(round(src.total_cost.sum(), 2)))) <= Decimal("0.01")
    dupes = _scalar("SELECT COUNT(*) FROM (SELECT RECORD_ID FROM CLOUDSPEND_AI.RAW.CLOUD_BILLING_RAW GROUP BY 1 HAVING COUNT(*)>1)")
    assert dupes[0] == 0
