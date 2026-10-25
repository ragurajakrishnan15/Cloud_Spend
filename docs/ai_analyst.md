# AI Finance Analyst & QBR (Phase 6)

The analyst answers finance questions from **verified calculations**. It works fully without any AI provider.

## Safe execution model
1. **Classify** the question into a supported intent with deterministic rules (`ai/intents.py`). Free-form SQL requests
   (`SELECT ... FROM`, `DROP`, "run a query", ...) are classified `blocked`; unknown questions are `unsupported`. Neither calls a tool.
2. **Validate** the period and filters (`ai/validation.py`): dates must overlap the loaded data (partial overlap is clipped and
   noted), member names are matched to real departments/services/environments/regions, `top_n` is clamped to 20, tables to 50 rows.
3. **Call approved tools only** (`ai/tools.py`): `get_spend_summary`, `get_budget_variance`, `get_top_cost_drivers`, `get_anomalies`,
   `get_forecast`, `get_optimization_recommendations`, `generate_qbr_metrics`. Tools are pure functions over already-loaded
   REPORTING data; none accepts SQL. `call_tool` refuses any other name.
4. **Ledger**: every number a tool reports is registered with its unit and source (`ai/ledger.py`).
5. **Narrative** (`ai/narrative.py`, `reporting/qbr_summary.py`): text is built only through `Ledger.fmt*`, so it can state only
   registered figures. It never claims a cause ("shows what changed, not why"), never invents savings (unsupported estimates print
   *Requires investigation*), and points out when a question's premise contradicts the data (e.g. asking about an "increase" when spend fell).
6. **Optional LLM** (`ai/llm.py`): only if a provider is configured. It receives just the ledger figures, small tables and limitations
   (`ai/prompts.py`; never credentials or connection details). Its text is accepted **only if every number matches the ledger**;
   otherwise the deterministic summary is shown with a warning. QBRs are always deterministic.
7. **Logging**: intent, tool names, status and timing only; no question text, no secrets.

## Data access
The analyst reads the same REPORTING views as the dashboard (read-only login when `SNOWFLAKE_APP_*` is configured) or the local
files. An integration test asserts that answers are identical from Snowflake and local data.

## QBR structure
1 Executive summary, 2 Spending and budget performance, 3 Largest cost drivers, 4 Significant anomalies, 5 Forecast and risks,
6 Potential optimization actions, 7 Follow-up questions and data limitations. Downloadable as Markdown from the page.

## Enabling an LLM provider (not included)
`LLM_PROVIDER=none` is the default and no provider SDK is a dependency. A provider is any object with `name` and
`complete(system: str, user: str) -> str`; register it in `ai.llm.get_provider`. Choosing one is a cost and data-policy decision
(the synthetic figures and table rows are sent to the provider), so it is deliberately left as a separate step.

## Limits to remember
- Routing is keyword-based: unusual phrasings fall back to `unsupported` rather than guessing.
- Dates in questions: month names, `YYYY-MM`, `Q3 2025`, "last month/quarter", "last N months/days", "year to date".
- Answers inherit the limits of the underlying models (see `model_evaluation.md`).
