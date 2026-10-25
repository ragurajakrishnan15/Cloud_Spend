"""Integration: running the models twice writes identical, non-duplicated results to Snowflake."""

import pytest

from cloudspend.analytics.run_models import main
from cloudspend.ingestion.snowflake_client import get_connection
from config.settings import load_snowflake_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not load_snowflake_settings().is_configured, reason="Snowflake credentials not set"),
]

COUNT_SQL = {
    "anomalies": "SELECT COUNT(*) FROM CLOUDSPEND_AI.REPORTING.VW_COST_ANOMALIES",
    "forecast": "SELECT COUNT(*) FROM CLOUDSPEND_AI.REPORTING.VW_COST_FORECAST",
    "recommendations": "SELECT COUNT(*) FROM CLOUDSPEND_AI.REPORTING.VW_OPTIMIZATION_RECOMMENDATIONS",
    "evaluation": "SELECT COUNT(*) FROM CLOUDSPEND_AI.REPORTING.VW_MODEL_EVALUATION",
    "dup_recommendation_ids": "SELECT COUNT(*) FROM (SELECT RECOMMENDATION_ID FROM CLOUDSPEND_AI.ANALYTICS."
                              "FACT_OPTIMIZATION_RECOMMENDATION GROUP BY 1 HAVING COUNT(*) > 1)",
    "anomalies_without_fact_row": "SELECT COUNT(*) FROM CLOUDSPEND_AI.ANALYTICS.FACT_COST_ANOMALY a WHERE NOT EXISTS "
                                  "(SELECT 1 FROM CLOUDSPEND_AI.ANALYTICS.FACT_CLOUD_COST f WHERE f.RECORD_ID = a.RECORD_ID)",
}


def _counts():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("USE WAREHOUSE CLOUDSPEND_WH")
        return {k: cur.execute(q).fetchone()[0] for k, q in COUNT_SQL.items()}


def test_model_run_is_idempotent_and_consistent():
    assert main(["--source", "snowflake"]) == 0
    first = _counts()
    assert main(["--source", "snowflake"]) == 0
    second = _counts()
    assert first == second
    assert first["anomalies"] > 0 and first["forecast"] > 0 and first["evaluation"] > 0
    assert first["dup_recommendation_ids"] == 0 and first["anomalies_without_fact_row"] == 0
