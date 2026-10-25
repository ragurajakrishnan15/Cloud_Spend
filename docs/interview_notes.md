# Interview notes

Everything here is measured or verifiable in the repo. Reproduce the key results yourself before an interview:
`pytest -m "not integration"`, `python -m cloudspend.analytics.run_models --source csv`, and `python -m cloudspend.analytics.evaluate_seeds`.

## 30-second pitch
"I built a cloud-spend analytics platform on synthetic billing data: a seeded generator with labelled anomalies, a validated load
into Snowflake, a RAW → ANALYTICS → REPORTING model with 17 reconciliation checks, a Streamlit dashboard, two evaluated anomaly
detectors and a baseline-vs-ETS forecast, rule-based recommendations, and a finance analyst that can only state numbers it can
trace to a calculation."

## Design choices and why
| Decision | Why | Trade-off |
|---|---|---|
| Budgets in their own table (month × dept × service) | Repeating a monthly budget on daily rows invites double-counting | Needs a full-outer join with actuals so one-sided rows aren't lost |
| `MERGE` on a logical key for loads; `INSERT OVERWRITE` for rebuilds | Re-runs must not duplicate | RAW keys must include the source file when datasets can overlap (see bug 1) |
| Ground-truth labels in a separate table | They can't leak into features | One extra join at evaluation time |
| Rolling median + MAD **excluding the current day**, weekday/weekend compared separately | The current observation must not contaminate its own baseline; weekly seasonality is the dominant pattern | Slow drift is absorbed by the baseline |
| Thresholds chosen on a chronological training period, metrics on the later holdout | Avoids reporting in-sample numbers as generalisation | ~40 holdout positives per dataset, so single-dataset figures are noisy, hence the 10-dataset check |
| Daily grain for forecasting | 548 daily points support weekly seasonality; 18 monthly points would not | Monthly totals are sums of daily forecasts and carry no interval |
| Pure-pandas KPI module shared by both backends | Snowflake and local mode cannot diverge; unit-testable | Data is pulled to pandas (fine at this scale; not at 100× scale) |
| Evidence ledger + deterministic narrative; optional LLM only as a checked rewrite | "Every numerical claim must come from a verified calculation" | Templated text is less fluent than an LLM's |
| Key-pair auth and a least-privilege service role | MFA-enforced accounts reject scripted passwords; dashboard shouldn't write | One-time admin setup step |

## Results to quote (synthetic data, with caveats)
- **Anomalies (holdout, mean ± sd, 10 datasets):** rolling median/MAD F1 0.70 ± 0.07 (precision 0.83, recall 0.64); Isolation Forest F1 0.55 ± 0.09.
  Spikes ~99% / 94% detected, weekend spend 93% / 100%, **gradual drift only 43% / 18%**. The simpler method won in 10/10 datasets.
- **Forecast (daily total):** ETS WAPE 2.5% vs 2.9% for seasonal-naive, better in 10/10 datasets; 80% interval coverage 86% ± 4%.
- **Pipeline:** 39,456 demo rows, $1,617,087.78 total; raw = fact = all views at the cent (17/17 checks).
- Seed 42 happens to be a better-than-average draw (F1 0.76), which is why I report the multi-dataset figures as the headline.

## Bugs that testing and review caught (good stories)
1. **Budget overwrite.** `BUDGETS_RAW` merged on month × dept × service without the source file, so loading the small dev dataset
   silently overwrote 120 of 738 demo budget rows. The reconciliation checks couldn't see it (they compared the model layer to the
   already-damaged RAW); an independent pandas-vs-Snowflake parity test did. Fix: key includes the source file; the loader now reconciles budgets against the file.
2. **Record-ID collision.** Dev and demo both numbered records from `rec-00000000`, so one load overwrote the other. IDs now carry the profile.
3. **Dollar signs rendered as LaTeX.** Streamlit markdown turned "$96,629 against a budget of $93,851" into garbled math. Headless tests
   passed; only looking at the rendered page showed it. Fix: escape `$` and add a regression test.
4. **Misleading refresh label.** The sidebar said the data came from the *dev* file because the freshness view picked the latest load of *any* file. Now it reports the modelled file.
5. **Threshold at the grid edge.** My first z-threshold search selected the largest grid value, so I widened the grid before trusting the number.
6. **Corrupted file.** A shell patch wrote literal backspace characters into a source file; a grounding test failed and exposed it.

## Likely questions
- **Why does the simple baseline beat Isolation Forest?** Both see essentially the same baseline-relative signal; the forest adds
  complexity and a calibrated threshold but no new information on this generator. I'd expect more separation with richer real features.
- **Is 2.5% WAPE good?** Only relative to the baseline (2.9%), and the data is smooth by construction; I wouldn't quote it as accuracy on real spend.
- **How do you stop the assistant hallucinating?** It doesn't generate numbers: tools return a ledger, templates format from it, and any LLM output is rejected if a number isn't in the ledger. SQL-like input never reaches a tool.
- **What would you do with real data?** Add incremental ingestion, replace labelled-threshold tuning with unsupervised calibration, add level-shift detection, monitor drift, and re-tune recommendation thresholds against reviewed outcomes.
- **What's not done?** No hosted deployment; no LLM provider (deliberately left as a cost/data-policy decision); keyword routing is brittle; the read-only Snowflake role is optional setup.

## Resume bullets (replace nothing — these already use measured figures)
**CloudSpend AI — Product Finance Intelligence Platform** · *Python, Snowflake SQL, Streamlit, scikit-learn, statsmodels*
- Built a Snowflake-backed BI platform that models synthetic cloud billing data (39k records, 18 months) into dimensional
  tables and reporting views, with idempotent loads and 17 automated reconciliation checks tying raw data to every view to the cent.
- Implemented and evaluated cost-anomaly detection and daily forecasting: rolling-median/MAD anomaly F1 0.70 ± 0.07 and ETS forecast
  WAPE 2.5% vs a 2.9% seasonal-naive baseline, using chronological holdouts and backtests repeated over 10 generated datasets
  (synthetic data; drift detection identified as a weakness).
- Developed an evidence-grounded finance analyst and QBR generator that routes questions to approved calculations only, traces every
  figure to its source, and rejects any LLM text containing an unverified number; covered by an automated test suite.

Do **not** claim real savings, production deployment, or accuracy on real billing data.

## Acceptance checklist (evidence, not assertions)
| Criterion (from the spec) | Status | Evidence |
|---|---|---|
| A fresh developer can set up from the README | Verified | New virtual environment from `requirements-dev.txt`, data generated, models run, lint and tests pass (clean-clone run) |
| Synthetic data generation is reproducible | Yes | `test_reproducible`; fixed seed, same output byte for byte |
| Data can be loaded into Snowflake | Yes | Loaded to a real account; `INGESTION_RUNS` shows runs |
| Raw, analytics and reporting layers exist and are documented | Yes | `sql/`, `docs/architecture.md`, `docs/data_dictionary.md` |
| Pipeline reruns do not duplicate records | Yes | Integration tests for load, transform and model write-back |
| Financial totals reconcile across layers | Yes | 17/17 checks; independent pandas parity test |
| Dashboard filters behave consistently | Yes, with documented exceptions | Shared `Filters`; budgets ignore env/region and forecasts ignore all filters, and the pages say so |
| Anomaly detection evaluated with labelled anomalies | Yes | `docs/model_evaluation.md` (holdout + 10 datasets) |
| Forecasting compared with a baseline, chronologically | Yes | Rolling-origin backtests, same document |
| Recommendations show evidence and avoid unsupported savings | Yes | Rule tests; "Requires investigation" |
| AI assistant uses approved functions and has a non-AI fallback | Yes | `ai/tools.py`; deterministic by default; guard-rail tests |
| Unit tests pass | Yes | `pytest -m "not integration"` |
| Secrets absent from the repository | Yes | Pattern scan clean (only fake values in a privacy test); `.env`, keys and generated data git-ignored; simulated `git add` lists no sensitive paths |
| README documents setup, architecture, assumptions, evaluation, limitations | Yes | `README.md` |
| Screenshots and a demo script are available | Yes | `docs/screenshots/`, `docs/demo_script.md` |

**Still on you:** create a git repository and push if you want it public (not done here), choose a licence, and — optionally — run
`sql/08_readonly_role.sql` so the dashboard uses a read-only login.
