"""Integration: the Snowflake REPORTING views and the local pandas equivalents give the same numbers,
and every dashboard page renders against Snowflake. Requires the demo dataset loaded + transformed."""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from cloudspend import data_access
from cloudspend.analytics.local_views import build_budget_variance, build_daily
from config.settings import GENERATED_DIR, load_snowflake_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not load_snowflake_settings().is_configured, reason="Snowflake credentials not set"),
]
APP = Path(__file__).resolve().parents[2] / "app"


@pytest.fixture(scope="module")
def frames(request):
    mp = pytest.MonkeyPatch()
    mp.setenv("CLOUDSPEND_DATA_MODE", "snowflake")
    yield data_access.load_daily(), data_access.load_budget_variance()
    mp.undo()


def test_daily_view_matches_local_pandas(frames):
    sf_daily, _ = frames
    local = build_daily(pd.read_csv(GENERATED_DIR / "cloud_billing_demo.csv"))
    assert len(sf_daily) == len(local)
    assert sf_daily["total_cost"].sum() == pytest.approx(local["total_cost"].sum(), abs=0.01)
    keys = ["usage_date", "department_name", "service_name", "environment_name", "region_name"]
    m = sf_daily.merge(local, on=keys, suffixes=("_sf", "_local"))
    assert len(m) == len(local)
    assert (m["total_cost_sf"] - m["total_cost_local"]).abs().max() < 0.011


def test_budget_variance_view_matches_local_pandas(frames):
    sf_daily, sf_bv = frames
    local_bv = build_budget_variance(
        build_daily(pd.read_csv(GENERATED_DIR / "cloud_billing_demo.csv")),
        pd.read_csv(GENERATED_DIR / "budgets_demo.csv"),
    )
    keys = ["month_start", "department_name", "service_name"]
    m = sf_bv.merge(local_bv, on=keys, suffixes=("_sf", "_local"))
    assert len(m) == len(sf_bv) == len(local_bv)
    assert (m["actual_cost_sf"] - m["actual_cost_local"]).abs().max() < 0.011
    assert (m["budget_amount_sf"] - m["budget_amount_local"]).abs().max() < 0.011


@pytest.mark.parametrize("page", ["Home.py", "pages/01_Spend_Overview.py", "pages/02_Budget_Variance.py",
                                  "pages/03_Anomaly_Detection.py", "pages/04_Spend_Forecasting.py",
                                  "pages/05_Optimization_Recommendations.py", "pages/06_AI_Finance_Analyst.py"])
def test_pages_render_against_snowflake(page, monkeypatch):
    monkeypatch.setenv("CLOUDSPEND_DATA_MODE", "snowflake")
    at = AppTest.from_file(str(APP / page), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]


QUESTIONS = ["Explain the month-over-month cost increase.", "Which departments are furthest over budget?",
             "Summarize the three highest-impact anomalies.", "Give me the current forecast and its limitations.",
             "What optimization actions should we review?", "Draft a QBR summary for the selected period."]


def test_analyst_answers_are_identical_from_snowflake_and_local_data(monkeypatch):
    from datetime import date

    from cloudspend.ai.analyst import answer
    from cloudspend.ai.tools import DataBundle
    from cloudspend.analytics.spend_metrics import Filters

    f = Filters(date(2025, 11, 1), date(2025, 11, 30))
    monkeypatch.setenv("CLOUDSPEND_DATA_MODE", "snowflake")
    sf = DataBundle.load()
    monkeypatch.setenv("CLOUDSPEND_DATA_MODE", "local")
    local = DataBundle.load()
    for q in QUESTIONS:
        a, b = answer(q, sf, f), answer(q, local, f)
        assert a.status == b.status == "ok", q
        assert a.text == b.text, q
        assert a.ledger.ungrounded_numbers(a.text) == []


def test_refresh_info_names_the_file_the_analytics_layer_was_built_from(monkeypatch):
    """Regression: the sidebar once reported the latest load of ANY file (e.g. the dev sample), not the modelled one."""
    monkeypatch.setenv("CLOUDSPEND_DATA_MODE", "snowflake")
    info = data_access.load_refresh_info()
    assert "cloud_billing_demo.csv" in info.detail and "dev" not in info.detail
