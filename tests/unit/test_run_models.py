"""End-to-end (no Snowflake) test of the model runner on the small committed sample dataset."""

import pandas as pd
import pytest

from cloudspend.analytics import model_store as store
from cloudspend.analytics.anomaly_detection import LABEL_COLUMNS
from cloudspend.analytics.run_models import compute, load_from_csv, local_view_frames
from config.settings import SAMPLE_DIR


@pytest.fixture(scope="module")
def out():
    records, labels, budgets = load_from_csv(SAMPLE_DIR / "cloud_billing_dev.csv", SAMPLE_DIR / "budgets_dev.csv")
    return compute(records, labels, budgets, run_id="test-run")


def test_labels_never_reach_outputs_or_inputs(out):
    records, _, _ = load_from_csv(SAMPLE_DIR / "cloud_billing_dev.csv", SAMPLE_DIR / "budgets_dev.csv")
    assert not set(LABEL_COLUMNS) & set(records.columns)
    for key in ("anomalies", "forecast", "recommendations", "evaluation"):
        assert not set(LABEL_COLUMNS) & set(out[key].columns), key


def test_outputs_have_expected_shape(out):
    a = out["anomalies"]
    assert len(a) > 0 and set(a["detection_method"]) <= {"rolling_median_mad", "isolation_forest"}
    assert a["usage_date"].notna().all() and a["department_name"].notna().all()
    assert (a["observed_cost"] > a["baseline_cost"]).all()          # increase-only
    f = out["forecast"]
    assert {"total"} <= set(f["scope_value"]) and f["forecast_date"].min() > pd.Timestamp("2025-06-29").date()
    ev = out["evaluation"]
    assert {"anomaly", "forecast"} == set(ev["model_family"])
    assert ((ev["model_family"] == "anomaly") & (ev["scope"] == "holdout") & (ev["metric_name"] == "f1")).any()
    r = out["recommendations"]
    assert r["recommendation_id"].is_unique and (r["review_status"] == "NEW").all()


def test_results_are_reproducible():
    records, labels, budgets = load_from_csv(SAMPLE_DIR / "cloud_billing_dev.csv", SAMPLE_DIR / "budgets_dev.csv")
    a = compute(records, labels, budgets, run_id="x")["anomalies"]
    b = compute(records, labels, budgets, run_id="x")["anomalies"]
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


def test_local_store_roundtrip(out, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "OUTPUT_DIR", tmp_path)
    frames = local_view_frames(out)
    store.save_local(frames)
    for key, df in frames.items():
        back = store.load_local(key)
        assert len(back) == len(df) and set(df.columns) == set(back.columns)


def test_load_local_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "OUTPUT_DIR", tmp_path)
    assert store.load_local("anomalies").empty
