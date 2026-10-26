"""Daily cloud-spend forecasting with a baseline and a second model, evaluated by rolling-origin backtests.

Grain: daily cost (total, and per department). Weekly seasonality (period 7).
Models:
  seasonal_naive_7d              baseline: repeat the last observed week. No prediction interval.
  ets_damped_additive_weekly     statsmodels ETS: additive error, damped additive trend, additive weekly seasonality.
                                 Provides 80% prediction intervals.
Evaluation: rolling-origin (expanding window) backtests, each fold trains only on data before its test window.
Metrics: MAE and WAPE = sum|error| / sum|actual| (undefined -> None when the actuals sum to zero).
Limitations: training data includes injected anomalies; ETS intervals assume well-behaved errors.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

SEASONAL_PERIOD = 7
MIN_TRAIN_DAYS = 90
INTERVAL_ALPHA = 0.20  # 80% prediction interval
MODEL_BASELINE = "seasonal_naive_7d"
MODEL_ETS = "ets_damped_additive_weekly"
MODEL_VERSION = "v1"


def mae(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(pred))))


def wape(actual: np.ndarray, pred: np.ndarray) -> float | None:
    """sum|actual - pred| / sum|actual|; None when the actuals sum to zero (undefined)."""
    a = np.asarray(actual, dtype=float)
    denom = float(np.abs(a).sum())
    return None if denom == 0 else float(np.abs(a - np.asarray(pred, dtype=float)).sum() / denom)


def seasonal_naive(y: pd.Series, horizon: int) -> pd.DataFrame:
    last = y.iloc[-SEASONAL_PERIOD:].to_numpy()
    idx = pd.date_range(y.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    return pd.DataFrame({"mean": np.resize(last, horizon), "lower": np.nan, "upper": np.nan}, index=idx)


def ets_forecast(y: pd.Series, horizon: int) -> pd.DataFrame:
    model = ETSModel(y.asfreq("D"), error="add", trend="add", damped_trend=True,
                     seasonal="add", seasonal_periods=SEASONAL_PERIOD)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = model.fit(disp=False)
        pred = fit.get_prediction(start=len(y), end=len(y) + horizon - 1).summary_frame(alpha=INTERVAL_ALPHA)
    out = pred.rename(columns={"pi_lower": "lower", "pi_upper": "upper"})[["mean", "lower", "upper"]]
    out.index = pd.date_range(y.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    return out.clip(lower=0)


FORECASTERS = {MODEL_BASELINE: seasonal_naive, MODEL_ETS: ets_forecast}


def horizon_to_end_of_next_month(last_date: date) -> int:
    """Days from the day after the last observation to the end of the following calendar month."""
    last = pd.Timestamp(last_date)
    end = (last + pd.offsets.MonthBegin(1)) + pd.offsets.MonthEnd(1)
    if last == last + pd.offsets.MonthEnd(0):  # last data day is a month end
        end = (last + pd.Timedelta(days=1)) + pd.offsets.MonthEnd(0)
    return int((end - last).days)


def backtest(y: pd.Series, horizon: int = 30, n_folds: int = 6) -> dict:
    """Rolling-origin backtest; fold k's test window is the k-th block of `horizon` days counting back from the end."""
    results: dict = {}
    for name, fn in FORECASTERS.items():
        folds, actuals, preds, covered, total_pts = [], [], [], 0, 0
        for k in range(n_folds, 0, -1):
            test_end = len(y) - (k - 1) * horizon
            test_start = test_end - horizon
            if test_start < MIN_TRAIN_DAYS:
                continue
            train, test = y.iloc[:test_start], y.iloc[test_start:test_end]
            fc = fn(train, horizon)
            folds.append({"train_end": str(train.index[-1].date()), "mae": mae(test, fc["mean"]),
                          "wape": wape(test, fc["mean"])})
            actuals.append(test.to_numpy())
            preds.append(fc["mean"].to_numpy())
            if fc["lower"].notna().all():
                covered += int(((test.to_numpy() >= fc["lower"].to_numpy()) & (test.to_numpy() <= fc["upper"].to_numpy())).sum())
                total_pts += len(test)
        if not folds:
            results[name] = {"n_folds": 0}
            continue
        a, p = np.concatenate(actuals), np.concatenate(preds)
        results[name] = {
            "n_folds": len(folds), "mae": mae(a, p), "wape": wape(a, p), "folds": folds,
            "interval_coverage": covered / total_pts if total_pts else None,
        }
    return results


@dataclass
class ForecastResult:
    forecasts: pd.DataFrame           # shaped like FACT_COST_FORECAST
    backtests: dict[str, dict]        # scope -> model -> metrics
    params: dict
    warnings: list[str] = field(default_factory=list)


def run_pipeline(series_by_scope: dict[str, tuple[str, pd.Series]], horizon: int | None = None,
                 backtest_horizon: int = 30, n_folds: int = 6) -> ForecastResult:
    """series_by_scope: scope_value -> (scope_type, daily cost series with a DatetimeIndex)."""
    rows, backtests, notes = [], {}, []
    last_dates = set()
    for scope_value, (scope_type, raw) in series_by_scope.items():
        y = raw.sort_index().asfreq("D")
        if y.isna().any():
            notes.append(f"{scope_value}: {int(y.isna().sum())} missing days were filled by interpolation")
            y = y.interpolate()
        if len(y) < MIN_TRAIN_DAYS:
            notes.append(f"{scope_value}: only {len(y)} days of history (< {MIN_TRAIN_DAYS}); no forecast produced")
            continue
        h = horizon or horizon_to_end_of_next_month(y.index[-1].date())
        last_dates.add(y.index[-1].date())
        backtests[scope_value] = backtest(y, backtest_horizon, n_folds)
        for name, fn in FORECASTERS.items():
            fc = fn(y, h)
            for d, r in fc.iterrows():
                rows.append({
                    "model_name": name, "model_version": MODEL_VERSION, "scope_type": scope_type,
                    "scope_value": scope_value, "forecast_date": pd.Timestamp(d).date(),
                    "forecast_cost": round(float(r["mean"]), 2),
                    "lower_bound": None if pd.isna(r["lower"]) else round(float(r["lower"]), 2),
                    "upper_bound": None if pd.isna(r["upper"]) else round(float(r["upper"]), 2),
                    "trained_through_date": y.index[-1].date(),
                })
    cols = ["model_name", "model_version", "scope_type", "scope_value", "forecast_date", "forecast_cost",
            "lower_bound", "upper_bound", "trained_through_date"]
    params = {"seasonal_period": SEASONAL_PERIOD, "min_train_days": MIN_TRAIN_DAYS, "interval": f"{1 - INTERVAL_ALPHA:.0%}",
              "backtest_horizon_days": backtest_horizon, "backtest_folds": n_folds, "grain": "daily",
              "trained_through": [str(d) for d in sorted(last_dates)]}
    return ForecastResult(pd.DataFrame(rows, columns=cols), backtests, params, notes)


def expected_month_variance(actual_to_date: float, forecast_rest: float, budget: float | None) -> dict:
    """Month-end projection = actual so far + forecast for the remaining days; variance vs budget if one exists."""
    projected = actual_to_date + forecast_rest
    if not budget:
        return {"projected": projected, "budget": budget, "variance": None, "variance_pct": None}
    return {"projected": projected, "budget": budget, "variance": projected - budget,
            "variance_pct": (projected - budget) / budget}


def month_projections(actual: pd.Series, forecast: pd.Series, budgets: dict[pd.Timestamp, float] | None = None) -> list[dict]:
    """Per-month projection = actual to date + forecast for the remaining days, for every month the forecast touches.

    Only months fully covered by actual + forecast days are projected; budget variance is given only when a budget exists
    for that month. No month-level prediction interval is produced (summing daily bounds would be invalid)."""
    budgets = budgets or {}
    last_actual = actual.index.max()
    months = sorted({d.to_period("M").to_timestamp() for d in forecast.index} | {last_actual.to_period("M").to_timestamp()})
    out = []
    for m in months:
        days = pd.date_range(m, m + pd.offsets.MonthEnd(0))
        a, f = actual[actual.index.isin(days)], forecast[forecast.index.isin(days)]
        covered = len(a) + len(f) == len(days)
        row = {"month": m, "actual_to_date": float(a.sum()), "forecast_remaining": float(f.sum()),
               "days_actual": len(a), "days_forecast": len(f), "fully_covered": covered}
        if covered:
            row.update(expected_month_variance(row["actual_to_date"], row["forecast_remaining"], budgets.get(m)))
        out.append(row)
    return out
