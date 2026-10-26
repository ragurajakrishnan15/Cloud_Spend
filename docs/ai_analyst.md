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

## Multi-step investigation (`ai/agent.py`)
"Investigate ...", "deep dive", "root cause" and similar questions route to a bounded agent instead of a single tool. The plan is
rule-based and adapts to earlier results:

1. `get_spend_summary` - period total, change vs the previous period, budget position.
2. If spend moved by >= 5%: `get_top_cost_drivers` by service and by department, then a **drill-down** into the departments
   driving the largest service. If there is no comparable previous period, or the move is small, these steps are *skipped* and the
   reason is recorded.
3. `get_budget_variance`, then `get_anomalies`; if anything is flagged and a top driver exists, `get_anomalies` is called again
   restricted to that driver as a **cross-check** (stated as a coincidence to review, never a cause).
4. `get_forecast`; and `get_optimization_recommendations` only if the period is over budget or has flagged records.

Safety properties (each covered by `tests/unit/test_ai_agent.py`): only registered tools are called with validated parameters;
a step budget (default 8) bounds the run and is disclosed when hit; a failing step is recorded and the run continues; every
figure is namespaced in one ledger (`s<step>.<id>`) so optional LLM wording is still grounded; the full trace (step, tool,
arguments, reason, status, time) is shown in the UI under "How this answer was produced". It is an orchestration of approved
calculations, not an autonomous agent: it cannot call anything outside `TOOLS`, write data, or run SQL.

## Data access
The analyst reads the same REPORTING views as the dashboard (read-only login when `SNOWFLAKE_APP_*` is configured) or the local
files. An integration test asserts that answers are identical from Snowflake and local data.

## QBR structure
1 Executive summary, 2 Spending and budget performance, 3 Largest cost drivers, 4 Significant anomalies, 5 Forecast and risks,
6 Potential optimization actions, 7 Follow-up questions and data limitations. Downloadable as Markdown from the page.

## Optional LLM provider
`LLM_PROVIDER=none` is the default; nothing is sent anywhere. Two adapters ship: Anthropic Claude and Google Gemini (REST, no extra package).

Gemini: put `LLM_PROVIDER=gemini`, `LLM_API_KEY=<key>` (and optionally `LLM_MODEL`, default `gemini-2.5-flash`) in the git-ignored `.env`.
Claude: `pip install -e ".[ai]"` and use `LLM_PROVIDER=anthropic`.

```powershell
python scripts/eval_llm_grounding.py --provider gemini --runs 3 --out docs/llm_grounding_eval.md
```

The key is sent in a request header, never in a URL, and error messages report only the HTTP status. Free-tier Gemini keys may
log or use prompts for product improvement; the prompts contain only synthetic figures.

Enabling it sends the computed figures and small result tables (never credentials) to that API and costs API usage, so it is
opt-in. The adapters are unit-tested with fakes. A few live Gemini calls were made during development: in a first run 6 of 7
example questions passed the grounding check, and the one rejection exposed a prompt problem (the model quoted table-only numbers),
which the system prompt now forbids. Free-tier rate limits then prevented a complete, repeatable measurement, so **no
acceptance rate is claimed**. The evaluation script (which reports provider errors separately from grounding rejections)
measures it; run it with a key that has quota before quoting any rate. Another provider is any object with `name` and `complete(system, user) -> str`, registered in `ai.llm.get_provider`.

## Limits to remember
- Routing is keyword-based: unusual phrasings fall back to `unsupported` rather than guessing.
- Dates in questions: month names, `YYYY-MM`, `Q3 2025`, "last month/quarter", "last N months/days", "year to date".
- Answers inherit the limits of the underlying models (see `model_evaluation.md`).
