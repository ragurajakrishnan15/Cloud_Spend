# Architecture & Data Model (Phases 1-3)

```
Generator -> CSV -> validate -> RAW (Snowflake) -> sql/03-05 -> ANALYTICS -> sql/06 -> REPORTING views
                                                      sql/07 reconciliation checks run after every build
```
Layers: **RAW** (as loaded) -> **ANALYTICS** (dimensional model + model outputs) -> **REPORTING** (views for the app).
Only REPORTING should be read by the dashboard / AI analyst. Source file is chosen at build time
(`transform --billing-file ... --budgets-file ...`) so dev and demo data never mix in ANALYTICS.

## Tables (logical keys; Snowflake does not enforce them)
| Table | Grain | Key |
|---|---|---|
| RAW.CLOUD_BILLING_RAW | resource-day | RECORD_ID |
| RAW.BUDGETS_RAW | source file x month x dept x service | (SOURCE_FILE, BUDGET_MONTH, DEPARTMENT, SERVICE_NAME) |
| RAW.INGESTION_RUNS / DATA_QUALITY_ISSUES | load attempt / issue | RUN_ID |
| ANALYTICS.DIM_DATE | calendar day (whole months covered) | DATE_KEY (yyyymmdd) |
| ANALYTICS.DIM_DEPARTMENT / SERVICE / ENVIRONMENT / REGION | member | *_KEY |
| ANALYTICS.FACT_CLOUD_COST | one row per source record (traceable to RAW) | RECORD_ID |
| ANALYTICS.FACT_BUDGET | month x dept x service | (BUDGET_MONTH, DEPARTMENT_KEY, SERVICE_KEY) |
| ANALYTICS.ANOMALY_GROUND_TRUTH | record | RECORD_ID - evaluation only, kept off the fact table |
| ANALYTICS.FACT_COST_ANOMALY / FACT_COST_FORECAST / FACT_OPTIMIZATION_RECOMMENDATION | model outputs | filled in Phase 5 |

Dimension surrogate keys are `DENSE_RANK` over names and are rebuilt with the facts: consistent within a build, not
stable across builds. Facts and dimensions are refreshed with `INSERT OVERWRITE`, so rebuilds are idempotent.
No raw records are excluded, so ANALYTICS cost equals RAW cost for the chosen file.

## Reporting views and KPI formulas
Ratios are fractions and NULL when the denominator is 0 (`DIV0NULL`).
- `VW_DAILY_CLOUD_SPEND`, `VW_MONTHLY_CLOUD_SPEND`: `SUM(total_cost)` at the stated grain.
- `VW_BUDGET_VARIANCE`: `variance = actual - budget` (positive = over budget); `variance_pct = variance / budget`.
  Budgets exist only per month x department x service, so **environment/region filters must not be applied to budget comparisons**.
- `VW_*_COST_TRENDS`: `mom_change_pct = (cost - prev_month_cost) / prev_month_cost`, NULL for the first month.
- `VW_QBR_METRICS`: quarterly actual vs budget, `qoq_change_pct`.
- `IS_PARTIAL_MONTH` / `IS_PARTIAL_QUARTER` mark periods with missing days. In the demo data, **December 2025 / 2025-Q4 are partial
  (data ends 2025-12-30)**; the dashboard must not present them as complete-period comparisons.
- `VW_DATA_REFRESH`: latest successful ingestion, for the "last refreshed" indicator.

## Reconciliation (sql/07)
17 checks, e.g. fact rows/cost = RAW, no orphan dimension keys, budget grain unique, and every reporting view's total = fact total.
Run: `python -m cloudspend.ingestion.transform [--checks-only]` (exit code 1 if any check fails).

## Dashboard (Phase 4)
`data_access.py` returns lower-cased frames from either backend; all KPI math lives in `analytics/spend_metrics.py`
(pure pandas, unit-tested) so Snowflake and local modes cannot diverge (`test_snowflake_app_parity.py` checks this).
- Previous period = the preceding whole calendar months for whole-month selections (a quarter -> previous quarter), otherwise the immediately preceding period of equal length; comparison hidden if not fully covered by the data.
- Budget / variance KPIs require a range of whole, fully-loaded calendar months and ignore environment / region filters.
- Percentages are recomputed from summed amounts, never averaged.
- Trend months with missing days are shown grey (partial).
- Model pages (anomaly, forecast, recommendations) read stored outputs and show an empty state until Phase 5 populates them.

## Lessons recorded
- RAW keys must include the source file when two datasets can overlap (a dev budget load once overwrote demo budgets).
  The loader now reconciles budgets against the file, and the parity test compares Snowflake with an independent pandas build.

## Models (Phase 5)
`analytics/run_models.py` reads FACT_CLOUD_COST (+ dimensions, budgets, and the separate ANOMALY_GROUND_TRUTH labels) from
Snowflake or the CSVs, runs `anomaly_detection`, `forecasting` and `optimization`, and writes:
FACT_COST_ANOMALY, FACT_COST_FORECAST, FACT_OPTIMIZATION_RECOMMENDATION and MODEL_EVALUATION (latest run only), each replaced in
one transaction (idempotent; recommendation review status is preserved across runs). The same results are written as CSVs
to `data/generated/model_outputs/` in the REPORTING-view shape, which local-mode dashboard pages read.
Labels are loaded separately and used only by `anomaly_detection.evaluate`; a test asserts they never reach model inputs.
