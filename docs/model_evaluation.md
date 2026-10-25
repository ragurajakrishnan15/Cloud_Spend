# Model Evaluation

> **All figures are measured on SYNTHETIC data** with injected anomalies. They show the methods work on this generator's patterns; they are not evidence of performance on real billing data.

Generated from `data/generated/model_outputs/` (10 extra seeds in the robustness check).

## 1. Anomaly detection

Grain: resource-day (~39k rows, 72 resources, demo profile, seed 42). Only cost **increases** are flagged.

- **A `rolling_median_mad`**: robust z-score against the resource's previous same-day-type (weekday/weekend) observations (windows 20/8, minimum 5). The current day is never part of its own baseline.
- **B `isolation_forest`**: scikit-learn IsolationForest on baseline-relative features (log ratio to baseline, robust z, day-over-day and week-over-week ratios, weekend flag, day of week, log cost, environment and service one-hots). Ground-truth labels are never features (enforced by a test).

**Evaluation design.** Chronological split: rows before **2025-06-05** are training (60% of the time span), later rows are the holdout. The Isolation Forest is fitted on training rows only. Each method's score threshold is chosen on training data (maximum F1; the labels are used here only to calibrate the threshold) and then applied unchanged to the holdout. **Reported metrics are holdout metrics.**

Chosen thresholds: A robust z >= 12.0; B score >= 0.590.

### 1a. Holdout metrics, seed 42 (single draw)

| Method | Precision | Recall | F1 | TP | FP | FN | TN | FP rate |
|---|---|---|---|---|---|---|---|---|
| rolling_median_mad | 1.000 | 0.614 | 0.761 | 27 | 0 | 17 | 15004 | 0.00000 |
| isolation_forest | 0.960 | 0.545 | 0.696 | 24 | 1 | 20 | 15003 | 0.00007 |

Detection rate by injected anomaly type (holdout, seed 42):

| Method | spike | drift | weekend_spend |
|---|---|---|---|
| rolling_median_mad | 15/17 (88%) | 7/21 (33%) | 5/6 (83%) |
| isolation_forest | 17/17 (100%) | 1/21 (5%) | 6/6 (100%) |

### 1b. Robustness across 10 independently generated datasets (holdout, mean ± sd)

| Method | Precision | Recall | F1 | False positives | Recall: spike | Recall: drift | Recall: weekend |
|---|---|---|---|---|---|---|---|
| rolling_median_mad | 0.83 ± 0.13 | 0.64 ± 0.18 | 0.70 ± 0.07 | 7.10 ± 6.92 | 0.99 ± 0.02 | 0.43 ± 0.28 | 0.93 ± 0.14 |
| isolation_forest | 0.64 ± 0.14 | 0.49 ± 0.11 | 0.55 ± 0.09 | 13.10 ± 8.81 | 0.94 ± 0.08 | 0.18 ± 0.11 | 1.00 ± 0.00 |

Method A had the higher F1 in 10/10 seeds. Seed 42 is one draw; prefer the table above for any claim about typical performance.

**Reading the results.** Spikes and weekend spend are detected reliably. Gradual drift is the weak spot: a rolling baseline adapts to a slow ramp, so only the later, larger days are flagged, and the Isolation Forest (which sees the same baseline-relative signal) misses most of it. Holdout size is small (~40 positives per dataset), so single-dataset figures are noisy. A flag means *unusual versus a baseline*; it does not establish a cause.

## 2. Forecasting

Grain: **daily** cost, total and per department; weekly seasonality (period 7). Rolling-origin backtest: 6 expanding-window folds of 30 days, each trained only on data before its test window. MAE in dollars/day; WAPE = sum|error| / sum|actual| (undefined if actuals sum to 0). Minimum history: 90 days.

- **Baseline `seasonal_naive_7d`**: repeat the last observed week (no prediction interval).
- **`ets_damped_additive_weekly`**: statsmodels ETS (additive error, damped additive trend, additive weekly seasonality) with 80% prediction intervals.

### 2a. Backtest, seed 42

| Scope | Naive MAE | ETS MAE | Naive WAPE | ETS WAPE | ETS 80% interval coverage |
|---|---|---|---|---|---|
| total | 90.0 | 80.2 | 0.028 | 0.025 | 0.87 |
| Data Science | 37.8 | 29.4 | 0.055 | 0.042 | 0.83 |
| Engineering | 41.5 | 38.4 | 0.076 | 0.071 | 0.71 |
| Finance IT | 37.1 | 31.8 | 0.045 | 0.039 | 0.96 |
| Marketing Tech | 17.2 | 12.6 | 0.054 | 0.040 | 0.78 |
| Platform | 25.4 | 20.5 | 0.062 | 0.050 | 0.90 |
| Support | 21.2 | 17.0 | 0.049 | 0.039 | 0.82 |

### 2b. Robustness across 10 datasets (total cost, mean ± sd)

| Model | MAE | WAPE | 80% interval coverage |
|---|---|---|---|
| seasonal_naive_7d | 96.0 ± 19.3 | 0.029 ± 0.004 | n/a |
| ets_damped_additive_weekly | 81.5 ± 17.9 | 0.025 ± 0.003 | 0.86 ± 0.04 |

ETS had the lower WAPE in 10/10 seeds. The improvement over the baseline is modest. **Caveat:** the synthetic data is built from a smooth trend plus weekly seasonality, which is exactly what ETS models, so real billing data (promotions, migrations, step changes) would be harder. The training series also contains the injected anomalies. Month-end projections should be read together with their intervals.

## 3. Optimization recommendations

Transparent rules (versioned `v1`); thresholds are configurable in `RuleConfig`. Dollar savings are given only where a formula is supported by the data; otherwise the UI shows *Requires investigation*.

| Rule | Recommendations produced (seed 42) |
|---|---|
| persistent_cost_increase | 0 |
| repeated_budget_overrun | 10 |
| nonprod_weekend_spend | 3 |
| cost_growth_exceeds_usage_growth | 0 |
| repeated_anomalies | 0 |

Rules that produce none on this dataset are not broken: they are unit-tested on crafted fixtures, and the synthetic data simply does not contain that pattern (e.g. unit prices are constant, so cost growth equals usage growth). Budgets were generated as actual spend x U(0.85, 1.10), so the overrun rule fires on random budget noise; its output demonstrates the mechanism, not a real finding.

## 4. Limitations

- Synthetic data; injected anomalies are simple, labelled increases. No claim is made about real-world accuracy or savings.
- Thresholds are calibrated on labelled training data, which real deployments would not have.
- Only increases are flagged. Level shifts and gradual drift are detected late or not at all.
- Forecast intervals assume well-behaved errors; backtests cover the last ~6 months only.
