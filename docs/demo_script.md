# Demo script (about 5 minutes)

**Goal:** show one finance story end to end — a cost change, why it matters, what to watch next, and an evidence-grounded
summary — and be explicit about what is synthetic and what is measured.

**Setup (before the call):** `streamlit run app/Home.py` in Snowflake mode (sidebar shows *Data source: Snowflake – cloud_billing_demo.csv*).
Keep the default sidebar period **Last complete month** (November 2025). Figures below are for the committed seed (42) and the
`demo` profile; they are deterministic and will match your screen.

---

### 0:00 — Frame it (20 s)
"This is a Snowflake-backed cost-analytics app on **synthetic** cloud billing data: about 39k resource-day records over 18 months.
The point isn't the dollars; it's the pipeline, the modelling, the evaluation, and an assistant that can't make numbers up."

### 0:20 — Spend Overview: the headline (60 s)
- **Total cost $96,629**, previous period (October) $100,749 → **−4.1%**. Budget $93,851, so **+$2,778 (+3.0%) over budget**.
- Scroll to **Largest contributors to change**: Database is the biggest mover (−$1,606, −7.1%); the net change across services is −$4,120.
- Point out the sidebar: filters apply everywhere, the data source and last refresh are visible, and the data is labelled synthetic.
- *Say:* "Every KPI has a documented formula. A zero or uncovered prior period shows n/a rather than a misleading percentage."

### 1:20 — Budget Variance: where the overrun is (45 s)
- Departments over budget: **Data Science +$1,778 (+9.4%)**, Finance IT +$1,457 (+6.3%), Support +$364 (+2.8%).
- Drill down: Data Science → Database (+$734, +12.7%).
- *Say:* "Budgets live at month × department × service, so they can't be double-counted by summing daily rows; environment and
  region filters deliberately don't apply here, and the page says so."

### 2:05 — Anomaly Detection: what's unusual (45 s)
- 4 resource-days flagged in November ($355 observed, $266 above baseline); the largest is **res-0070 on 2025-11-04: $146 vs a $25 baseline**.
- Open *How good are these detectors?* — "On a chronological holdout the simple rolling-median method beat the Isolation Forest, and
  across 10 generated datasets its F1 was 0.70 ± 0.07. Gradual drift is the weak spot — I'd rather show that than hide it."
- *Say:* "A flag means *unusual versus a baseline*. It doesn't claim a cause and it isn't an accusation."

### 2:50 — Forecasting: what's next and how much to trust it (45 s)
- December is **projected at $107,084** (actual to date $103,324 + forecast $3,760) against a $101,606 budget: **+$5,478 (+5.4%)**.
- Show the 80% band, then tick *Show seasonal-naive baseline*. Backtest: ETS WAPE **2.5% vs 2.8%** for the baseline; the 80% interval covered 87% of actuals.
- *Say:* "It beats the baseline, but modestly, and this data is smooth by construction — real billing would be harder."

### 3:35 — Recommendations (20 s)
- 13 rule-based items, each with evidence and a suggested next step. Savings read **"Requires investigation"** because the data doesn't support a formula.

### 3:55 — AI Finance Analyst (70 s)
1. Click **Explain the month-over-month cost increase.** → the answer opens with *"spend did not increase… it fell by $4,120 (4.1%)"*.
   *Say:* "It checks the question's premise against the data and states what changed, not why."
2. Click **Draft a QBR summary for the selected period.** → seven sections; open **Key figures and where each came from**.
   *Say:* "Every number is registered with its source. If an optional LLM were enabled, its text would be rejected unless every number matched this ledger."
3. Type `SELECT * FROM fact_cloud_cost` → refused. "Free-form SQL is never executed; it can only call seven approved functions."
4. Click **Download QBR (Markdown)**.

### 5:05 — Close (15 s)
"Seventeen reconciliation checks tie raw to every view to the cent; reruns don't duplicate; labels never reach model inputs;
and several real bugs were caught by tests and by looking at the UI. Happy to go deeper on any layer."

---

## If something goes wrong
- *Snowflake unreachable:* `CLOUDSPEND_DATA_MODE=local` — same numbers from the CSVs.
- *Numbers differ:* check the sidebar period is **Last complete month** and the data source line names `cloud_billing_demo.csv`.
- *Reset the analyst:* reload the page.
- Screenshots of every page are in `docs/screenshots/` as a backup.
