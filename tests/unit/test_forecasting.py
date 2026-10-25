from datetime import date

import numpy as np
import pandas as pd
import pytest

from cloudspend.analytics.forecasting import (
    MIN_TRAIN_DAYS,
    backtest,
    expected_month_variance,
    horizon_to_end_of_next_month,
    mae,
    run_pipeline,
    seasonal_naive,
    wape,
)


def make_series(n=300, seed=0, trend=0.05, noise=1.0):
    t = np.arange(n)
    y = 100 + trend * t + 10 * np.sin(2 * np.pi * t / 7) + np.random.default_rng(seed).normal(0, noise, n)
    return pd.Series(y, index=pd.date_range("2025-01-01", periods=n, freq="D"))


def test_mae_and_wape():
    assert mae([10, 20], [12, 18]) == 2.0
    assert wape([10, 20], [12, 18]) == pytest.approx(4 / 30)


def test_wape_undefined_when_actuals_zero():
    assert wape([0, 0], [1, 2]) is None


def test_seasonal_naive_repeats_last_week():
    y = pd.Series(np.arange(14, dtype=float), index=pd.date_range("2025-01-01", periods=14))
    fc = seasonal_naive(y, 10)
    assert fc["mean"].tolist() == [7, 8, 9, 10, 11, 12, 13, 7, 8, 9]
    assert fc.index[0] == pd.Timestamp("2025-01-15") and fc["lower"].isna().all()


def test_horizon_to_end_of_next_month():
    assert horizon_to_end_of_next_month(date(2025, 12, 30)) == 32     # Dec 31 + all of January
    assert horizon_to_end_of_next_month(date(2025, 12, 31)) == 31     # month end -> all of January
    assert horizon_to_end_of_next_month(date(2025, 1, 15)) == 44      # rest of Jan (16) + Feb (28)


def test_backtest_folds_never_train_on_test_window():
    y = make_series()
    bt = backtest(y, horizon=30, n_folds=4)
    for model in bt.values():
        ends = [pd.Timestamp(f["train_end"]) for f in model["folds"]]
        assert ends == sorted(ends) and ends[-1] <= y.index[-1] - pd.Timedelta(days=30)
        assert model["n_folds"] == 4


def test_ets_beats_naive_on_trending_seasonal_series_and_has_valid_intervals():
    y = make_series(noise=0.5, trend=0.3)
    bt = backtest(y, horizon=30, n_folds=4)
    assert bt["ets_damped_additive_weekly"]["mae"] < bt["seasonal_naive_7d"]["mae"]
    cov = bt["ets_damped_additive_weekly"]["interval_coverage"]
    assert 0.0 <= cov <= 1.0
    assert bt["seasonal_naive_7d"]["interval_coverage"] is None  # baseline has no interval


def test_run_pipeline_outputs_and_skips_short_history():
    y = make_series(200)
    res = run_pipeline({"total": ("total", y), "short": ("department", y.iloc[:40])}, backtest_horizon=30, n_folds=2)
    assert set(res.forecasts["scope_value"]) == {"total"}
    assert any("short" in w and str(MIN_TRAIN_DAYS) in w for w in res.warnings)
    f = res.forecasts
    ets = f[f["model_name"] == "ets_damped_additive_weekly"]
    assert ets["lower_bound"].notna().all() and (ets["lower_bound"] <= ets["upper_bound"]).all()
    assert f[f["model_name"] == "seasonal_naive_7d"]["lower_bound"].isna().all()
    assert f["forecast_date"].min() > y.index[-1].date()


def test_run_pipeline_interpolates_missing_days_with_warning():
    y = make_series(200)
    y = y.drop(y.index[50:53])
    res = run_pipeline({"total": ("total", y)}, backtest_horizon=30, n_folds=1)
    assert any("missing days" in w for w in res.warnings) and not res.forecasts.empty


def test_expected_month_variance():
    v = expected_month_variance(900.0, 200.0, 1000.0)
    assert v["projected"] == 1100.0 and v["variance"] == 100.0 and v["variance_pct"] == pytest.approx(0.1)
    assert expected_month_variance(1.0, 1.0, None)["variance"] is None


def test_month_projections_combines_actual_and_forecast_with_budget():
    from cloudspend.analytics.forecasting import month_projections
    actual = pd.Series(10.0, index=pd.date_range("2025-12-01", "2025-12-30"))
    fc = pd.Series(12.0, index=pd.date_range("2025-12-31", "2026-01-31"))
    out = month_projections(actual, fc, {pd.Timestamp("2025-12-01"): 300.0})
    dec, jan = out
    assert dec["actual_to_date"] == 300.0 and dec["forecast_remaining"] == 12.0 and dec["fully_covered"]
    assert dec["projected"] == 312.0 and dec["variance"] == 12.0 and dec["variance_pct"] == pytest.approx(0.04)
    assert jan["projected"] == 12.0 * 31 and jan["variance"] is None   # no January budget loaded


def test_month_projections_skips_uncovered_months():
    from cloudspend.analytics.forecasting import month_projections
    actual = pd.Series(10.0, index=pd.date_range("2025-12-01", "2025-12-30"))
    fc = pd.Series(12.0, index=pd.date_range("2025-12-31", "2026-01-10"))   # January only partly forecast
    jan = month_projections(actual, fc)[1]
    assert jan["fully_covered"] is False and "projected" not in jan
