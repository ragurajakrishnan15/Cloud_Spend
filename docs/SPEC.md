# CloudSpend AI --- Product Finance Intelligence Platform

> **Portfolio project:** A Snowflake-backed business intelligence and AI
> application for cloud-spend analysis, budget variance reporting,
> anomaly detection, forecasting, cost-optimization recommendations, and
> automated quarterly business review (QBR) summaries.

**Primary audience:** Recruiters and interviewers evaluating skills
relevant to Business Intelligence, Product Finance Analytics, SQL,
Python application development, data modeling, machine learning, and
AI-assisted workflows.

**Important:** This project uses synthetic cloud-billing data. It is an
independent portfolio project and is not affiliated with, endorsed by,
or based on confidential data from Snowflake or any other cloud
provider. Do not describe synthetic results as real company savings or
production outcomes.

------------------------------------------------------------------------

## 1. Project Overview

Finance and engineering teams need to understand where cloud expenditure
is going, why costs change, whether spending is likely to exceed budget,
and which items deserve investigation. Raw billing records are difficult
to use directly for recurring reporting and executive reviews.

CloudSpend AI will transform synthetic cloud billing data into a
reusable analytics platform. It will load and validate records, store
them in Snowflake, model them for analysis, provide interactive
dashboards, evaluate anomaly-detection and forecasting models, generate
transparent optimization suggestions, and produce evidence-grounded
narrative summaries.

### Core questions the application should answer

-   How much did we spend during a selected period?
-   How did spending change versus the previous period?
-   Which department, service, environment, or region explains the
    change?
-   Which costs are unusual relative to a defensible baseline?
-   What is the forecast for the remainder of the month and the next
    month?
-   Which departments or services are over budget?
-   What potential optimization actions should a finance analyst
    investigate?
-   Can the system generate a concise, data-grounded QBR summary?

### Goals

1.  Demonstrate hands-on use of Snowflake as an analytical warehouse.
2.  Demonstrate SQL transformations, dimensional modeling, and reusable
    reporting views.
3.  Demonstrate a Python data pipeline with validation and error
    handling.
4.  Build a usable BI application with Streamlit.
5.  Evaluate anomaly detection and forecasting with appropriate metrics
    and baselines.
6.  Generate recommendations whose evidence and assumptions can be
    inspected.
7.  Add an AI assistant that calls approved analytical functions and
    grounds answers in returned data.
8.  Deliver tests, documentation, reproducible setup, and a polished
    portfolio demonstration.

### Non-goals for the first version

-   Connecting to real production cloud billing accounts.
-   Making automatic infrastructure changes or deleting resources.
-   Claiming actual financial savings.
-   Building a fully autonomous agent with unrestricted SQL execution.
-   Requiring paid AI services for the core dashboard.
-   Claiming production-scale or enterprise deployment without evidence.

------------------------------------------------------------------------

## 2. Technology Stack

Use stable, mutually compatible versions and pin dependencies after the
first successful build.

  -----------------------------------------------------------------------
  Layer                   Recommended technology  Responsibility
  ----------------------- ----------------------- -----------------------
  Language                Python 3.11+            Ingestion, analytics,
                                                  models, application

  Data warehouse          Snowflake               Raw, transformed, and
                                                  reporting data

  Query language          Snowflake SQL           Transformations,
                                                  analytical queries,
                                                  reporting views

  Data processing         pandas, NumPy           Synthetic data
                                                  generation and
                                                  validation

  Snowflake connectivity  Snowflake Connector for Loading and querying
                          Python or Snowpark      warehouse data
                          Python                  

  BI application          Streamlit               Interactive dashboard
                                                  and analyst workflow

  Visualization           Plotly                  Interactive charts

  Anomaly detection       scikit-learn Isolation  Flag unusual costs
                          Forest plus statistical 
                          baselines               

  Forecasting             statsmodels, with a     Forecast daily/monthly
                          simple baseline         costs

  Testing                 pytest                  Unit and integration
                                                  tests

  Configuration           python-dotenv for local Local environment
                          development             variables

  Code quality            Ruff and optionally     Linting and
                          mypy                    maintainability

  Version control         Git and GitHub          History, documentation,
                                                  portfolio

  AI layer                Optional LLM API or     Evidence-grounded
                          Snowflake Cortex        explanations and
                          capability if available summaries
  -----------------------------------------------------------------------

**Cost-conscious default:** The core data pipeline, dashboard, anomaly
detection, forecasting, and recommendation engine must work without an
LLM API. Make the AI integration optional and provide a deterministic
fallback summary. Check the current features, availability, and pricing
of any Snowflake or LLM service before enabling it.

------------------------------------------------------------------------

## 3. High-Level Architecture

``` text
Synthetic Billing Data Generator
            |
            v
CSV / Local Sample Data
            |
            v
Python Ingestion + Data Validation
            |
            v
Snowflake RAW Schema
            |
            v
SQL Transformations and Data Quality Checks
            |
            v
Snowflake ANALYTICS Schema
  - Fact table
  - Dimension tables
  - Model outputs
            |
            +-------------------------------+
            |                               |
            v                               v
Snowflake REPORTING Views             Python Analytics
            |                          - Anomaly detection
            |                          - Forecasting
            |                          - Optimization rules
            |                               |
            +---------------+---------------+
                            |
                            v
                    Streamlit Dashboard
                            |
                            v
              Finance Q&A / QBR Summary
```

### Design principles

-   Keep raw data separate from cleaned analytical data and reporting
    outputs.
-   Make transformations repeatable and safe to rerun.
-   Keep credentials out of source control.
-   Make every chart and KPI traceable to a query or calculation.
-   Show model limitations and data coverage in the UI.
-   Treat AI-generated text as an explanation of calculated results, not
    as the source of truth.
-   Keep a deterministic, non-AI path for core functionality.
-   Never execute arbitrary LLM-generated SQL without strict validation
    and authorization.

------------------------------------------------------------------------

## 4. Repository Structure

Create the repository with the following structure. Claude Code may
adjust names if it documents the reason and preserves the separation of
concerns.

``` text
cloudspend-ai/
├── app/
│   ├── Home.py
│   ├── pages/
│   │   ├── 01_Spend_Overview.py
│   │   ├── 02_Budget_Variance.py
│   │   ├── 03_Anomaly_Detection.py
│   │   ├── 04_Spend_Forecasting.py
│   │   ├── 05_Optimization_Recommendations.py
│   │   └── 06_AI_Finance_Analyst.py
│   └── components/
│       ├── filters.py
│       ├── charts.py
│       └── kpi_cards.py
├── config/
│   └── settings.py
├── data/
│   ├── generated/
│   └── sample/
├── sql/
│   ├── 01_create_database.sql
│   ├── 02_create_raw_tables.sql
│   ├── 03_create_dimensions.sql
│   ├── 04_create_fact_tables.sql
│   ├── 05_transformations.sql
│   ├── 06_reporting_views.sql
│   └── 07_data_quality_checks.sql
├── src/
│   └── cloudspend/
│       ├── __init__.py
│       ├── data_generation/
│       │   └── generate_billing.py
│       ├── ingestion/
│       │   ├── load_csv.py
│       │   └── snowflake_client.py
│       ├── validation/
│       │   └── billing_checks.py
│       ├── analytics/
│       │   ├── spend_metrics.py
│       │   ├── anomaly_detection.py
│       │   ├── forecasting.py
│       │   └── optimization.py
│       ├── ai/
│       │   ├── analyst.py
│       │   └── prompts.py
│       └── reporting/
│           └── qbr_summary.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── notebooks/
│   └── exploration.ipynb
├── docs/
│   ├── architecture.md
│   ├── data_dictionary.md
│   ├── model_evaluation.md
│   └── demo_script.md
├── .env.example
├── .gitignore
├── requirements.txt
├── pyproject.toml
├── Makefile
└── README.md
```

Do not commit credentials, real billing exports, local `.env` files, or
generated data files that unnecessarily inflate the repository. Include
a small safe sample dataset if useful.

------------------------------------------------------------------------

## 5. Synthetic Dataset Design

Generate reproducible synthetic billing data using a fixed random seed.
Target approximately 18 months of daily observations, across several
services, departments, environments, and regions. The generator should
create plausible trends and known anomalies without copying any real
provider's confidential data.

### Recommended fields

  -----------------------------------------------------------------------
  Field                   Type                    Description
  ----------------------- ----------------------- -----------------------
  `record_id`             string                  Unique source-record
                                                  identifier

  `usage_date`            date                    Date the usage occurred

  `department`            string                  Synthetic owning
                                                  department

  `service_name`          string                  Synthetic cloud service
                                                  category

  `environment`           string                  Production, staging, or
                                                  development

  `region`                string                  Synthetic or generic
                                                  region

  `resource_id`           string                  Synthetic resource
                                                  identifier

  `usage_units`           decimal                 Usage quantity

  `unit_cost`             decimal                 Cost per usage unit

  `total_cost`            decimal                 Cost for the record

  `budget_amount`         decimal                 Budget allocation at
                                                  the selected reporting
                                                  grain

  `is_injected_anomaly`   boolean                 Ground-truth label for
                                                  evaluation only

  `anomaly_type`          string, nullable        Reason for synthetic
                                                  anomaly injection

  `generated_at`          timestamp               Data-generation
                                                  timestamp
  -----------------------------------------------------------------------

### Data generation requirements

-   Use a fixed random seed and document how to change it.
-   Generate daily seasonality, weekly patterns, gradual growth, and
    different cost profiles by service.
-   Generate a consistent budget grain. Avoid repeating a monthly budget
    on every daily record and then summing it incorrectly.
-   Inject a known proportion of anomalies such as cost spikes, gradual
    drift, and unusual weekend spending.
-   Keep ground-truth labels out of model input features.
-   Include a data dictionary and assumptions.
-   Support a small development dataset and a larger demo dataset.
-   Include deterministic tests for uniqueness, valid dates, nonnegative
    costs, expected schema, and known injected anomaly counts.

All data and results must be clearly labeled as synthetic.

------------------------------------------------------------------------

## 6. Snowflake Data Model

Create a dedicated database named `CLOUDSPEND_AI` with three schemas:

-   `RAW`: source records as loaded.
-   `ANALYTICS`: cleaned data, dimensional model, and model outputs.
-   `REPORTING`: views intended for dashboard and finance queries.

### Suggested objects

#### RAW

-   `CLOUD_BILLING_RAW`: records loaded from generated CSV.
-   `INGESTION_RUNS`: file name, row count, status, timestamps, and
    error summary.
-   Optional `DATA_QUALITY_ISSUES`: invalid rows and issue codes,
    avoiding unnecessary sensitive data.

#### ANALYTICS

-   `DIM_DATE`
-   `DIM_SERVICE`
-   `DIM_DEPARTMENT`
-   `DIM_ENVIRONMENT`
-   `DIM_REGION`
-   `FACT_CLOUD_COST`
-   `FACT_COST_ANOMALY`
-   `FACT_COST_FORECAST`
-   `FACT_OPTIMIZATION_RECOMMENDATION`

Use stable keys and define the grain of each table explicitly. For
example, `FACT_CLOUD_COST` may have one row per source billing record or
per day/service/department/environment/region combination. Choose one
grain and document it. If source rows are aggregated, preserve
traceability to the raw data.

#### REPORTING

Create reusable views such as:

-   `VW_DAILY_CLOUD_SPEND`
-   `VW_MONTHLY_CLOUD_SPEND`
-   `VW_BUDGET_VARIANCE`
-   `VW_DEPARTMENT_COST_TRENDS`
-   `VW_SERVICE_COST_TRENDS`
-   `VW_COST_ANOMALIES`
-   `VW_COST_FORECAST`
-   `VW_OPTIMIZATION_RECOMMENDATIONS`
-   `VW_QBR_METRICS`

### Data model requirements

-   Document primary keys and logical relationships, even if physical
    constraints are not enforced.
-   Add `created_at` or `updated_at` timestamps to derived outputs where
    useful.
-   Make loading and transformation operations idempotent.
-   Handle duplicate source records intentionally.
-   Validate that costs aggregate consistently between raw and modeled
    tables.
-   Avoid double-counting budgets when changing the reporting grain.
-   Provide SQL queries to verify row counts and financial totals at
    each stage.

------------------------------------------------------------------------

## 7. Ingestion and Data Quality

Implement a Python command that generates the data and another that
loads it into Snowflake.

### Pipeline stages

1.  Check that the input file exists and matches the expected schema.
2.  Parse dates and numeric fields.
3.  Validate required values and allowed categories.
4.  Identify duplicate IDs, invalid dates, negative costs, and
    inconsistent calculations.
5.  Record valid rows and invalid-row summaries.
6.  Load records into the raw table.
7.  Run transformations into analytics tables.
8.  Run reconciliation checks.
9.  Record the pipeline run status and row counts.
10. Return a nonzero exit status if a critical stage fails.

### Quality checks

-   Unique source record IDs.
-   Required columns are present.
-   Dates fall within the intended generated period.
-   Usage and costs obey documented rules.
-   `total_cost` reconciles with `usage_units * unit_cost` within a
    documented rounding tolerance.
-   Budgets are stored at their intended grain.
-   Raw and transformed costs reconcile after accounting for explicitly
    excluded records.
-   Dimension foreign keys resolve.
-   Re-running the same input does not duplicate data.

The pipeline must distinguish warnings from fatal errors and report
useful messages without exposing credentials.

------------------------------------------------------------------------

## 8. Business Intelligence Dashboard

Build a multi-page Streamlit application with consistent filters and a
clean finance-oriented design.

### Global filters

-   Date range.
-   Department.
-   Service.
-   Environment.
-   Region.

Filters should affect all applicable KPIs and charts consistently.
Include a visible indicator of the selected date range and the last
successful data refresh.

### Page 1 --- Spend Overview

Show: - Total cost for the selected period. - Previous-period cost and
percentage change. - Budget and variance. - Daily or monthly cost
trend. - Cost by service and department. - Environment and regional
breakdown. - Largest contributors to cost change.

Every KPI must have a documented formula. Handle zero or missing
prior-period values safely.

### Page 2 --- Budget Variance

Show: - Budget versus actual by department and service. - Absolute and
percentage variance. - Largest over-budget categories. -
Month-over-month changes. - Drill-down from department to service and
time period.

### Page 3 --- Anomaly Detection

Show: - Anomaly count and total flagged expenditure. - Severity ranking
based on a documented rule. - Actual versus baseline cost. - Anomaly
trend over time. - Filters for department, service, date, and
severity. - Details for each flagged record, including the method and
supporting evidence.

Do not equate a statistical anomaly with fraud or a confirmed cost
problem.

### Page 4 --- Spend Forecasting

Show: - Historical costs and forecasts. - Forecast horizon and model
version. - Prediction intervals if the model supports them. - Expected
budget variance. - Backtesting metrics and baseline comparison. -
Warnings when insufficient historical data is available.

### Page 5 --- Optimization Recommendations

Show: - Recommended action. - Evidence and calculation. - Affected
service or department. - Estimated opportunity, if calculable. -
Confidence or evidence strength. - Review status.

Recommendations should be reviewable, not automatically executed against
cloud infrastructure.

### Page 6 --- AI Finance Analyst

Provide a question box with example prompts: - "Explain the
month-over-month cost increase." - "Which departments are furthest over
budget?" - "Summarize the three highest-impact anomalies." - "Give me
the current forecast and its limitations." - "Draft a QBR summary for
the selected period."

The answer should include the selected period, the key calculated
figures, supporting data, and a short explanation. Show when a question
cannot be answered from the available data.

------------------------------------------------------------------------

## 9. Anomaly Detection

Implement at least two approaches so the project can compare methods
rather than relying on one model.

### Method A --- Statistical baseline

Use a rolling median or mean and a robust measure of dispersion.
Document the window, minimum history, threshold, and handling of
seasonality. Avoid letting the current observation contaminate its own
baseline when evaluating historical anomalies.

### Method B --- Isolation Forest

Use scikit-learn Isolation Forest on defensible features such as: - Cost
relative to a service-specific rolling baseline. - Percentage change
from the preceding period. - Day of week. - Historical usage or cost. -
Service and environment encoded appropriately.

Do not include `is_injected_anomaly` or `anomaly_type` as model
features.

### Evaluation

Use the injected labels only for offline evaluation. Report: -
Precision. - Recall. - F1-score. - Confusion matrix. - Detection rate
for injected anomalies. - False-positive count or rate. - Results by
anomaly type where sample sizes permit.

Document the split or evaluation strategy. Do not train and evaluate on
the same records and present that as reliable generalization. For
time-dependent data, use a chronological holdout when feasible.

### UI explanation

For each anomaly, display: - Observed cost. - Baseline or expected
cost. - Absolute difference. - Percentage difference. - Detection
method. - A concise reason for the flag.

The model identifies unusual patterns; it does not independently
establish why they happened.

------------------------------------------------------------------------

## 10. Cloud Spend Forecasting

Start with a simple baseline, such as the previous comparable period or
seasonal-naive forecasting. Compare it with Holt-Winters exponential
smoothing or another suitable method.

### Requirements

-   Aggregate data at a documented daily or monthly grain.
-   Use chronological train/test splits.
-   Compare forecasts with actual values for the holdout period.
-   Report MAE and WAPE, defining how zero actual values are handled.
-   Avoid data leakage from future observations.
-   Provide a forecast horizon and minimum-data requirement.
-   Save model metadata, creation time, evaluation metrics, and forecast
    values.
-   Include uncertainty intervals only when the selected method provides
    them.
-   Display limitations for short or irregular histories.

Do not claim a model is accurate based only on a visually appealing
chart. Include a baseline comparison.

------------------------------------------------------------------------

## 11. Optimization Recommendation Engine

Build transparent rules first; do not begin with an opaque generative
model.

Potential rules include: - Persistent cost increases above a
configurable threshold. - Repeated budget overruns. - Unusually high
nonproduction costs during low-usage periods. - Cost growth that is
disproportionate to usage growth. - Repeated anomalies in the same
service or department.

Each recommendation should include: - A stable recommendation ID. - Rule
name and version. - Affected dimension and time period. - Evidence
used. - Suggested next step. - Estimated savings formula, only when
supported by data. - Confidence/evidence classification. - Creation
timestamp. - Review status.

If the data cannot support a savings estimate, show "Requires
investigation" rather than inventing a dollar value. Never make changes
to real infrastructure.

------------------------------------------------------------------------

## 12. AI Finance Analyst and Agentic Workflow

Keep this module modular and optional so the project remains usable
without an AI provider.

### Safe execution model

1.  Classify the request into a supported intent.
2.  Validate requested filters and dates.
3.  Call an approved Python analytical function or query a predefined
    reporting view.
4.  Validate the returned data and calculations.
5.  Pass only the relevant results to the language model, if enabled.
6.  Ask the model to summarize the results without inventing missing
    values.
7.  Return the summary with supporting figures and a clear limitation
    note.

### Supported analytical tools

-   `get_spend_summary`
-   `get_budget_variance`
-   `get_top_cost_drivers`
-   `get_anomalies`
-   `get_forecast`
-   `get_optimization_recommendations`
-   `generate_qbr_metrics`

### Safety and reliability

-   Do not execute unrestricted LLM-generated SQL.
-   Use read-only database permissions for dashboard and AI access.
-   Use parameterized queries or tightly controlled query templates.
-   Validate date ranges and filters.
-   Limit result sizes.
-   Do not send credentials or secrets to an AI model.
-   Do not let the AI invent savings estimates or claim an anomaly's
    cause without evidence.
-   Provide a deterministic template-based summary if the AI service is
    unavailable.
-   Log intent, tool name, execution status, and timing without logging
    secrets or unnecessary user data.

### QBR summary structure

Generate: 1. Executive summary. 2. Spending and budget performance. 3.
Largest cost drivers. 4. Significant anomalies. 5. Forecast and risks.
6. Potential optimization actions. 7. Follow-up questions and data
limitations.

Every numerical claim must come from a verified query or calculation.

------------------------------------------------------------------------

## 13. Security, Configuration, and Cost Controls

### Local configuration

Create `.env.example` with placeholder variable names, never real
credentials. For example:

``` dotenv
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
SNOWFLAKE_PASSWORD=
SNOWFLAKE_ROLE=
SNOWFLAKE_WAREHOUSE=
SNOWFLAKE_DATABASE=CLOUDSPEND_AI
SNOWFLAKE_SCHEMA=RAW
SNOWFLAKE_AUTHENTICATOR=
LLM_PROVIDER=none
LLM_API_KEY=
```

Use only the authentication variables appropriate to the chosen
Snowflake authentication method. Prefer supported key-pair, SSO, or
other secure authentication methods where practical; do not hard-code
passwords.

### Required safeguards

-   Add `.env`, private keys, credentials, and local generated files to
    `.gitignore`.
-   Use the minimum required Snowflake privileges.
-   Keep the AI/dashboard role read-only where possible.
-   Never commit real billing data or personal information.
-   Never print connection secrets in logs.
-   Close database connections reliably.
-   Configure warehouse auto-suspend and review usage.
-   Avoid running large warehouses or repeated expensive queries
    unnecessarily.
-   Make sample mode work locally without Snowflake credentials where
    practical.
-   Document the difference between local sample mode and
    Snowflake-connected mode.

------------------------------------------------------------------------

## 14. Testing Strategy

### Unit tests

Test: - Synthetic data generation and reproducibility. - Data validation
rules. - Cost and variance calculations. - Percentage changes when prior
values are zero. - Anomaly feature generation. - Forecast metric
calculations. - Recommendation rule logic. - AI output validation and
deterministic fallback.

### Integration tests

When Snowflake credentials are available, test: - Connection setup. -
Table creation. - Data loading. - Idempotent reruns. - SQL
transformations. - Reporting view results. - Reconciliation between raw
and modeled totals.

Integration tests should be clearly marked and skipped with a helpful
message when credentials are unavailable.

### Acceptance criteria

The first complete version is ready when:

-   [ ] A fresh developer can set up the project using the README.
-   [ ] Synthetic data generation is reproducible.
-   [ ] Data can be loaded into Snowflake.
-   [ ] Raw, analytics, and reporting layers exist and are documented.
-   [ ] Pipeline reruns do not duplicate records.
-   [ ] Financial totals reconcile across layers.
-   [ ] Dashboard filters behave consistently.
-   [ ] Anomaly detection is evaluated with labeled synthetic anomalies.
-   [ ] Forecasting is compared against a baseline using chronological
    evaluation.
-   [ ] Recommendations show evidence and avoid unsupported savings
    claims.
-   [ ] The AI assistant uses approved analytical functions and has a
    non-AI fallback.
-   [ ] Unit tests pass.
-   [ ] Secrets are absent from the repository.
-   [ ] The README documents setup, architecture, assumptions,
    evaluation, and limitations.
-   [ ] Screenshots and a demo script are available for a portfolio
    presentation.

Do not invent model scores, processing times, savings, or performance
figures to satisfy these criteria. Record measured results after running
the project.

------------------------------------------------------------------------

## 15. Implementation Roadmap

Build in small, testable increments. Do not ask Claude Code to implement
every feature in one enormous change.

### Phase 1 --- Repository and local sample mode

-   Create project structure.
-   Add configuration and dependency files.
-   Generate synthetic billing records.
-   Add data dictionary and basic tests.
-   Implement local sample mode.

**Exit condition:** The dataset can be regenerated and validated without
Snowflake credentials.

### Phase 2 --- Snowflake warehouse and ingestion

-   Create database and schemas.
-   Create raw table and ingestion-run table.
-   Implement Snowflake connection handling.
-   Load generated CSV data.
-   Add validation, error reporting, and idempotency.

**Exit condition:** Data loads into Snowflake and reconciles with the
source dataset.

### Phase 3 --- Data modeling and reporting SQL

-   Create dimensions and fact tables.
-   Implement transformations.
-   Add reporting views.
-   Add data-quality and reconciliation SQL.

**Exit condition:** Core dashboard metrics can be reproduced using
documented SQL queries.

### Phase 4 --- BI dashboard

-   Implement global filters.
-   Build spend overview and budget-variance pages.
-   Add anomaly and forecast pages using stored outputs.
-   Add clear empty states, loading indicators, and error messages.

**Exit condition:** A user can answer the core finance questions through
the UI.

### Phase 5 --- Machine learning and recommendations

-   Implement statistical anomaly baseline.
-   Implement and evaluate Isolation Forest.
-   Implement forecast baseline and second model.
-   Add transparent optimization rules.
-   Store model outputs and metadata.

**Exit condition:** Models are evaluated and their limitations are
documented.

### Phase 6 --- AI analyst and QBR automation

-   Define supported intents and analytical tools.
-   Implement tool routing and result validation.
-   Add optional AI-generated explanations.
-   Add deterministic fallback.
-   Generate QBR summaries.

**Exit condition:** The analyst can answer supported questions using
verified calculations without unrestricted SQL execution.

### Phase 7 --- Portfolio polish

-   Add tests and code quality checks.
-   Document architecture and data model.
-   Add dashboard screenshots.
-   Write a short demo script.
-   Record actual evaluation results.
-   Add a limitations and future-work section.

**Exit condition:** The repository is reproducible, understandable, and
ready for an interview walkthrough.

------------------------------------------------------------------------

## 16. Suggested Ten-Day Schedule

This is an ambitious target for a first working version; expand the
schedule if debugging, Snowflake permissions, or model evaluation
requires more time.

  Day   Focus
  ----- ---------------------------------------------
  1     Repository, requirements, synthetic dataset
  2     Snowflake setup and ingestion
  3     Transformations, dimensions, fact table
  4     Reporting views and reconciliation
  5     Spend overview and budget dashboard
  6     Anomaly detection and evaluation
  7     Forecasting and backtesting
  8     Optimization recommendations
  9     AI analyst and QBR summaries
  10    Tests, README polish, screenshots, demo

Prioritize a working end-to-end slice over six incomplete dashboard
pages. If time is limited, complete the data pipeline, spend dashboard,
and evaluated anomaly detection first.

------------------------------------------------------------------------

## 17. Local Setup (Target Workflow)

Claude Code should verify exact dependency versions and commands as it
builds the repository. The intended workflow is:

``` bash
# Create and enter the project directory
mkdir cloudspend-ai
cd cloudspend-ai

# Create a virtual environment
python -m venv .venv

# Activate on macOS/Linux
source .venv/bin/activate

# Activate on Windows PowerShell
# .venv\Scripts\Activate.ps1

# Install dependencies after requirements.txt is created
pip install -r requirements.txt

# Create a local environment file from the template
# macOS/Linux:
cp .env.example .env

# Windows PowerShell:
# Copy-Item .env.example .env
```

Then run the commands documented by the implementation, for example:

``` bash
# Generate deterministic synthetic data
python -m cloudspend.data_generation.generate_billing

# Run unit tests
pytest

# Launch the Streamlit app
streamlit run app/Home.py
```

If the package layout requires installation, Claude Code should add a
`pyproject.toml` and document `pip install -e .`. Do not assume the
example commands work until they have been tested.

For Snowflake mode: 1. Configure connection variables using a supported
authentication method. 2. Run the SQL setup scripts in the documented
order. 3. Generate or select the sample CSV. 4. Execute the ingestion
command. 5. Run transformations and reconciliation checks. 6. Launch the
app in Snowflake-connected mode.

------------------------------------------------------------------------

## 18. Claude Code Build Instructions

Use Claude Code as the implementation partner. Paste the following
instruction after creating this README in the repository.

> Read `README.md` completely and treat it as the project specification.
> First inspect the repository and identify what exists. Do not
> implement the entire application in one pass.
>
> Begin with Phase 1 only: repository configuration, synthetic billing
> data generator, data validation, data dictionary, and unit tests. Make
> the implementation reproducible with a fixed random seed. Do not
> invent performance results or claim features are complete unless they
> are implemented and tested.
>
> Before editing, propose a concise plan and list the files you intend
> to create. Then implement Phase 1, run the relevant tests, fix
> failures, and summarize what changed, commands run, test results, and
> any remaining issues. Preserve clear separation between data
> generation, ingestion, analytics, application, and configuration.
>
> After Phase 1 passes, stop and wait for review before proceeding to
> Phase 2. Continue one phase at a time. Follow secure coding practices:
> no hard-coded credentials, no committed `.env` file, no unrestricted
> LLM-generated SQL, and no automatic changes to real cloud
> infrastructure. Keep local sample mode usable without Snowflake
> credentials where practical.
>
> When a requirement is ambiguous, choose the simplest maintainable
> option, document the assumption, and ask before introducing paid
> services or major architectural changes.

### Recommended working rules for Claude Code

-   Inspect the existing repository before overwriting files.
-   Make small changes and run tests after each phase.
-   Prefer clear functions and typed interfaces over one giant script.
-   Keep SQL scripts version-controlled.
-   Use synthetic fixtures in tests.
-   Explain important architectural decisions in `docs/`.
-   Never expose credentials in output.
-   Do not add an LLM dependency until the deterministic pipeline and
    dashboard work.
-   Update this README when the implementation differs from the planned
    architecture.
-   Mark roadmap items as complete only after verifying them.

------------------------------------------------------------------------

## 19. Portfolio Presentation

Once the project works, prepare the following:

1.  **GitHub repository:** Clean code, setup instructions, SQL scripts,
    tests, and architecture documentation.
2.  **Dashboard screenshots:** Spend overview, budget variance, anomaly
    investigation, forecast, and recommendations.
3.  **Short demo:** A 3--5 minute walkthrough of a cost increase, its
    investigation, a forecast, and the resulting QBR summary.
4.  **Model evaluation report:** Metrics, baselines, holdout
    methodology, and limitations.
5.  **Architecture diagram:** Synthetic source → ingestion → Snowflake →
    transformations → analytics → dashboard and AI analyst.
6.  **Interview notes:** Explain design choices, data quality, SQL
    modeling, model evaluation, security, and trade-offs.

Be ready to explain the code and reproduce key results yourself. The
goal is not only to make the application look impressive but to
demonstrate that you understand how it works.

------------------------------------------------------------------------

## 20. Resume Bullets --- Add Only After Implementation

Use this as a template and replace the placeholders with actual measured
outcomes:

**CloudSpend AI --- Product Finance Intelligence Platform**\
*Python, Snowflake SQL, Streamlit, scikit-learn, statsmodels, Generative
AI*

-   Built a Snowflake-backed BI platform that transformed synthetic
    cloud billing records into dimensional reporting tables and
    interactive spending dashboards.
-   Implemented and evaluated cost anomaly detection and forecasting
    models using \[actual metrics\], with comparisons against documented
    baselines.
-   Developed evidence-grounded financial analysis and QBR summarization
    workflows that surfaced budget variances, cost drivers, and
    potential optimization actions.

Do not claim a specific model score, forecast accuracy, dollar savings,
production deployment, or reduction in analysis time unless you measured
it and can explain the evaluation.

------------------------------------------------------------------------

## 21. Limitations and Future Improvements

Possible future extensions include:

-   Incremental ingestion and change tracking.
-   More sophisticated orchestration and scheduled refreshes.
-   Role-based dashboard access.
-   Cost-aware query optimization.
-   More advanced time-series forecasting.
-   Model drift monitoring.
-   Improved explainability for anomalies.
-   Optional Snowflake Cortex integration, if available in the account
    and appropriate for the project.
-   Cloud-provider billing schemas or FinOps standards, using public
    documentation and clearly scoped adapters.
-   Deployment and monitoring for a hosted demo.

These are future ideas, not promises of existing functionality.

------------------------------------------------------------------------

## 22. Definition of Done

The project is complete when a reviewer can clone the repository, follow
the documented setup, generate synthetic data, load it into Snowflake,
inspect the modeled finance data, use the dashboard, review evaluated
anomalies and forecasts, inspect optimization recommendations, and
generate an evidence-grounded QBR summary.

The finished project should demonstrate **SQL, Python application
development, BI reporting, data modeling, financial analytics, machine
learning, and safe AI-assisted automation** in one coherent business use
case.

**Build order:** data correctness first, warehouse and reporting second,
dashboard third, evaluated ML fourth, AI automation fifth, and portfolio
polish last.
