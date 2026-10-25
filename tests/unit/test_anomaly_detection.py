import numpy as np
import pandas as pd
import pytest

from cloudspend.analytics.anomaly_detection import (
    LABEL_COLUMNS,
    BaselineConfig,
    add_baseline,
    best_threshold,
    build_iforest_features,
    chronological_split,
    evaluate,
    run_pipeline,
    severity,
    to_anomaly_rows,
)


def make_records(days=120, spike_day=None, spike=5.0, weekend_factor=0.5):
    rng = np.random.default_rng(0)
    dates = pd.date_range("2025-01-01", periods=days)
    rows = []
    for res, svc, env in (("r1", "Compute", "production"), ("r2", "Storage", "development")):
        for i, d in enumerate(dates):
            cost = 100.0 * (weekend_factor if d.dayofweek >= 5 else 1.0) * rng.lognormal(0, 0.03)
            if res == "r1" and spike_day is not None and i == spike_day:
                cost *= spike
            rows.append((f"{res}-{i}", d, res, "Eng", svc, env, "us", 1.0, round(cost, 2)))
    return pd.DataFrame(rows, columns=[
        "record_id", "usage_date", "resource_id", "department_name", "service_name",
        "environment_name", "region_name", "usage_units", "total_cost"])


def test_baseline_excludes_current_observation():
    r = make_records(60, spike_day=40)
    df = add_baseline(r)
    spike_row = df[df["record_id"] == "r1-40"].iloc[0]
    # the spike must not be in its own baseline: baseline stays near 100 (or 50 on weekends)
    assert spike_row["baseline_median"] < 120 and spike_row["robust_z"] > 10


def test_baseline_handles_weekly_seasonality():
    df = add_baseline(make_records(90))
    ok = df.dropna(subset=["robust_z"])
    # weekend days (cost 50) are compared with weekend history, so they are not outliers
    assert ok["robust_z"].abs().max() < 6


def test_baseline_needs_minimum_history():
    df = add_baseline(make_records(30), BaselineConfig(min_periods=5))
    first = df[df["resource_id"] == "r1"].sort_values("usage_date").iloc[:5]
    assert first["baseline_median"].isna().all()


def test_features_exclude_labels_and_are_finite_where_scoreable():
    df = add_baseline(make_records(90))
    df = df[df["baseline_median"].notna()]
    f = build_iforest_features(df)
    assert not set(LABEL_COLUMNS) & set(f.columns)
    assert np.isfinite(f["log_ratio_baseline"]).all()


def test_pipeline_rejects_label_columns_in_records():
    r = make_records(60)
    r["is_injected_anomaly"] = False
    labels = pd.DataFrame({"record_id": r["record_id"], "is_injected_anomaly": False, "anomaly_type": None})
    with pytest.raises(ValueError):
        run_pipeline(r, labels)


def test_evaluate_confusion_matrix_and_types():
    y = pd.Series([True, True, False, False, True])
    p = pd.Series([True, False, True, False, True])
    t = pd.Series(["spike", "drift", None, None, "spike"])
    m = evaluate(y, p, t)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 1)
    assert m["precision"] == pytest.approx(2 / 3) and m["recall"] == pytest.approx(2 / 3)
    assert m["false_positive_rate"] == pytest.approx(0.5)
    assert m["by_type"]["spike"] == {"n": 2, "detected": 2, "detection_rate": 1.0}
    assert m["by_type"]["drift"]["detection_rate"] == 0.0


def test_evaluate_handles_no_positives():
    m = evaluate(pd.Series([False, False]), pd.Series([False, False]))
    assert m["precision"] is None and m["recall"] is None and m["f1"] is None


def test_best_threshold_prefers_best_f1():
    y = pd.Series([False] * 8 + [True] * 2)
    score = pd.Series([1, 1, 1, 1, 2, 2, 2, 2, 9, 9], dtype=float)
    assert best_threshold(y, score, [0.5, 5.0, 9.5]) == 5.0


def test_chronological_split():
    d = pd.Series(pd.date_range("2025-01-01", periods=101))
    assert chronological_split(d, 0.6) == pd.Timestamp("2025-03-02")


def test_severity_rule():
    assert severity(3.0) == "high" and severity(2.0) == "medium" and severity(1.2) == "low"


def test_pipeline_detects_clear_spike_in_holdout_and_not_in_train_leak():
    r = make_records(150, spike_day=130)
    lab = pd.DataFrame({"record_id": r["record_id"], "is_injected_anomaly": r["record_id"] == "r1-130"})
    lab["anomaly_type"] = np.where(lab["is_injected_anomaly"], "spike", None)
    res = run_pipeline(r, lab)
    assert res.metrics["rolling_median_mad"]["holdout"]["tp"] == 1
    rows = to_anomaly_rows(res)
    assert "r1-130" in set(rows["record_id"])
    assert set(rows["detection_method"]) <= {"rolling_median_mad", "isolation_forest"}
    assert (rows["abs_diff"] > 0).all() and rows["reason"].str.contains("baseline").all()
    assert not set(LABEL_COLUMNS) & set(res.scored.columns)
