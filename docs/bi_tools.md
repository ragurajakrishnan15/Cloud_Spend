# Using Tableau and Looker with CloudSpend AI

The Streamlit app is the primary interface, but the REPORTING layer is plain SQL views, so any BI tool can sit on top of it.
**All data is synthetic.** The Tableau and Looker steps below have **not** been run against a live Tableau or Looker
instance by this project; the CSV extracts they read *are* generated and reconciled to the source by tests
(`tests/unit/test_bi_export.py`).

## Which objects to read

Only read the `CLOUDSPEND_AI.REPORTING` views, using the read-only role from `sql/08_readonly_role.sql`.

| View | Grain | Use it for |
|---|---|---|
| `VW_DAILY_CLOUD_SPEND` | day x department x service x environment x region | spend trends, breakdowns |
| `VW_BUDGET_VARIANCE` | month x department x service | budget vs actual (budgets exist only at this grain) |
| `VW_COST_ANOMALIES` | flagged record x detection method | anomaly review |
| `VW_COST_FORECAST` | date x model x scope | forecast and prediction interval |
| `VW_QBR_METRICS` | calendar quarter | QBR tables |

Rules that keep the numbers right in any tool:

- **Never apply an environment or region filter to budget comparisons.** Budgets are not defined at that level.
- **Compute ratios from sums** (`SUM(variance) / SUM(budget)`); never average a percentage column.
- A record flagged by two detection methods appears twice in `VW_COST_ANOMALIES`; count `DISTINCT RECORD_ID`.

## Tableau

**Option A - live connection (Tableau Desktop / Cloud).** Snowflake connector: server `<account>.snowflakecomputing.com`,
role `CLOUDSPEND_READER`, warehouse `CLOUDSPEND_WH`, database `CLOUDSPEND_AI`, schema `REPORTING`. Prefer an *Extract* over
*Live* unless you accept warehouse credits for every interaction.

**Option B - flat files** (works with Tableau Public, which cannot connect to Snowflake):

```powershell
python -m cloudspend.reporting.bi_export     # writes data/generated/bi_extracts/*.csv
```

Connect each CSV, then add these calculated fields:

```text
Variance %          SUM([variance_amount]) / SUM([budget_amount])
Over budget lines   SUM(IIF([is_over_budget], 1, 0))
Avg daily cost      SUM([total_cost]) / COUNTD([usage_date])
Flagged records     COUNTD([record_id])
```

Suggested sheets: monthly spend by service (stacked bars), budget variance by department (sorted bars), anomalies by date
coloured by severity, forecast with the lower/upper bounds as a band. Put a "synthetic data" caption on every dashboard.

## Looker

`bi/looker/` is a small LookML project (one model, three views) over the same REPORTING views:

1. Create a Looker connection to Snowflake using the read-only role, named `cloudspend_snowflake` (or edit `connection:` in
   `cloudspend.model.lkml`).
2. Create a LookML project, copy the contents of `bi/looker/` into it, and run *Validate LookML* in the IDE.
3. Explore `daily_spend`, `budget_variance` and `cost_anomalies`.

The measures follow the rules above: ratios are computed from summed measures and anomalies use distinct counts.
