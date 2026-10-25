"""Smoke tests: every dashboard page renders without exceptions in local mode (no Snowflake needed)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from config.settings import GENERATED_DIR, SAMPLE_DIR

APP = Path(__file__).resolve().parents[2] / "app"
PAGES = ["Home.py", *sorted(p.name for p in (APP / "pages").glob("*.py"))]

pytestmark = pytest.mark.skipif(
    not ((GENERATED_DIR / "cloud_billing_demo.csv").exists() or (SAMPLE_DIR / "cloud_billing_dev.csv").exists()),
    reason="no local data; run the generator first",
)


@pytest.fixture(autouse=True)
def local_mode(monkeypatch):
    monkeypatch.setenv("CLOUDSPEND_DATA_MODE", "local")


def _run(page: str) -> AppTest:
    path = APP / page if page == "Home.py" else APP / "pages" / page
    return AppTest.from_file(str(path), default_timeout=60).run()


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(page):
    at = _run(page)
    assert not at.exception, [e.value for e in at.exception]


def test_overview_shows_kpis_and_totals_are_consistent():
    at = _run("01_Spend_Overview.py")
    labels = [m.label for m in at.metric]
    assert {"Total cost", "Previous period", "Budget", "Variance vs budget"} <= set(labels)
    values = {m.label: m.value for m in at.metric}
    assert values["Total cost"].startswith("$")
    assert values["Budget"].startswith("$")  # default preset is a whole complete month


def test_overview_budget_na_for_partial_month_range():
    at = AppTest.from_file(str(APP / "pages" / "01_Spend_Overview.py"), default_timeout=60).run()
    at.selectbox(key="f_preset").select("Full range").run()  # includes the incomplete final month
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["Budget"] == "n/a" and values["Variance vs budget"] == "n/a"


def test_filter_changes_total():
    at = AppTest.from_file(str(APP / "pages" / "01_Spend_Overview.py"), default_timeout=60).run()
    base = {m.label: m.value for m in at.metric}["Total cost"]
    at.multiselect(key="f_dep").select("Engineering").run()
    filtered = {m.label: m.value for m in at.metric}["Total cost"]
    assert filtered != base and not at.exception


MODEL_PAGES = ["03_Anomaly_Detection.py", "04_Spend_Forecasting.py", "05_Optimization_Recommendations.py"]


@pytest.fixture()
def isolated_dev(monkeypatch, tmp_path):
    """Local mode on the committed dev sample, with model outputs redirected to a temp dir."""
    import streamlit as st

    from cloudspend import data_access
    from cloudspend.analytics import model_store as store

    monkeypatch.setattr(data_access, "_local_files",
                        lambda: (str(SAMPLE_DIR / "cloud_billing_dev.csv"), str(SAMPLE_DIR / "budgets_dev.csv")))
    monkeypatch.setattr(store, "OUTPUT_DIR", tmp_path)
    st.cache_data.clear()
    yield tmp_path
    st.cache_data.clear()


def test_model_pages_show_empty_state_without_outputs(isolated_dev):
    for page in MODEL_PAGES:
        at = _run(page)
        assert not at.exception, (page, [e.value for e in at.exception])
        assert any("run_models" in i.value for i in at.info), page


def test_model_pages_render_with_outputs(isolated_dev):
    from cloudspend.analytics import model_store as store
    from cloudspend.analytics.run_models import compute, load_from_csv, local_view_frames

    records, labels, budgets = load_from_csv(SAMPLE_DIR / "cloud_billing_dev.csv", SAMPLE_DIR / "budgets_dev.csv")
    store.save_local(local_view_frames(compute(records, labels, budgets)))
    for page in MODEL_PAGES:
        at = _run(page)
        assert not at.exception, (page, [e.value for e in at.exception])
    anomalies = _run("03_Anomaly_Detection.py")
    assert "Flagged records" in [m.label for m in anomalies.metric]
    forecast = _run("04_Spend_Forecasting.py")
    assert any(m.label == "Horizon" for m in forecast.metric)
    assert len(forecast.dataframe) >= 2   # month projection + backtest tables


def _ask(question: str) -> AppTest:
    at = AppTest.from_file(str(APP / "pages" / "06_AI_Finance_Analyst.py"), default_timeout=90).run()
    at.text_area(key="ai_question").set_value(question)
    return at.button(key="ai_ask").click().run()


def test_ai_page_answers_example_questions_with_grounded_text(isolated_dev):
    for q in ("Which departments are furthest over budget?", "How much did we spend?"):
        at = _ask(q)
        assert not at.exception, (q, [e.value for e in at.exception])
        assert at.session_state["ai_answer"].status == "ok"
        text = " ".join(m.value for m in at.markdown)
        assert "Period used" in text and "Limitations" in text


def test_ai_page_blocks_sql_and_handles_unsupported(isolated_dev):
    blocked = _ask("SELECT * FROM fact_cloud_cost")
    assert not blocked.exception and blocked.session_state["ai_answer"].status == "blocked"
    assert any("free-form SQL" in w.value for w in blocked.warning)
    unsupported = _ask("tell me a joke")
    assert unsupported.session_state["ai_answer"].status == "unsupported"


def test_ai_page_qbr_offers_download_and_example_buttons_work(isolated_dev):
    at = _ask("Draft a QBR summary for the selected period.")
    assert not at.exception and at.session_state["ai_answer"].qbr is not None
    assert len(at.session_state["ai_answer"].qbr.sections) == 7
    at2 = AppTest.from_file(str(APP / "pages" / "06_AI_Finance_Analyst.py"), default_timeout=90).run()
    at2.button(key="ex_1").click().run()
    assert not at2.exception and at2.session_state["ai_answer"].intent == "budget_variance"


def test_ai_answers_escape_dollar_signs_so_streamlit_does_not_render_math(isolated_dev):
    """Regression: '$a ... $b' in markdown was rendered as LaTeX and garbled every answer with two amounts."""
    at = _ask("How much did we spend?")
    assert not at.exception
    answer_md = next(m.value for m in at.markdown if "total cloud spend" in m.value)
    assert "$" in answer_md
    esc = chr(92) + "$"  # backslash + dollar
    assert esc in answer_md and answer_md.replace(esc, "").count("$") == 0


def test_md_safe_and_money_formatting():
    from components.kpi_cards import md_safe, money

    assert md_safe("$1 and $2") == chr(92) + "$1 and " + chr(92) + "$2"
    assert money(-125.0) == "-$125" and money(1234.4) == "$1,234" and money(None) == "n/a"
