"""Generate docs/model_evaluation.md from the stored result files (no hand-copied numbers).

    python -m cloudspend.analytics.run_models --source csv      # produces evaluation.csv
    python -m cloudspend.analytics.evaluate_seeds               # produces seed_robustness.csv
    python -m cloudspend.analytics.eval_report
"""

from __future__ import annotations

import json

import pandas as pd

from cloudspend.analytics import model_store as store
from config.settings import PROJECT_ROOT

OUT = PROJECT_ROOT / "docs" / "model_evaluation.md"
A, B = "rolling_median_mad", "isolation_forest"
NAIVE, ETS = "seasonal_naive_7d", "ets_damped_additive_weekly"


def _get(ev: pd.DataFrame, family, model, scope, metric):
    m = ev[(ev.model_family == family) & (ev.model_name == model) & (ev.scope == scope) & (ev.metric_name == metric)]
    return None if m.empty or pd.isna(m.iloc[0]["metric_value"]) else float(m.iloc[0]["metric_value"])


def _f(x, nd=3):
    return "n/a" if x is None or pd.isna(x) else f"{x:.{nd}f}"


def build() -> str:
    ev = store.load_local("evaluation")
    seeds = pd.read_csv(store.OUTPUT_DIR / "seed_robustness.csv")
    recs = store.load_local("recommendations")
    params = json.loads(ev[(ev.model_family == "anomaly")].iloc[0]["parameters"])
    fparams = json.loads(ev[(ev.model_family == "forecast")].iloc[0]["parameters"])
    L = ["# Model Evaluation", "",
         "> **All figures are measured on SYNTHETIC data** with injected anomalies. They show the methods work on this "
         "generator's patterns; they are not evidence of performance on real billing data.", "",
         f"Generated from `data/generated/model_outputs/` ({len(seeds.seed.unique())} extra seeds in the robustness check).", "",
         "## 1. Anomaly detection", "",
         "Grain: resource-day (~39k rows, 72 resources, demo profile, seed 42). Only cost **increases** are flagged.", "",
         "- **A `rolling_median_mad`**: robust z-score against the resource's previous same-day-type (weekday/weekend) "
         f"observations (windows {params['baseline']['window_weekday']}/{params['baseline']['window_weekend']}, minimum "
         f"{params['baseline']['min_periods']}). The current day is never part of its own baseline.",
         "- **B `isolation_forest`**: scikit-learn IsolationForest on baseline-relative features (log ratio to baseline, robust z, "
         "day-over-day and week-over-week ratios, weekend flag, day of week, log cost, environment and service one-hots). "
         "Ground-truth labels are never features (enforced by a test).", "",
         f"**Evaluation design.** Chronological split: rows before **{params['split_date']}** are training "
         f"({int(params['train_fraction'] * 100)}% of the time span), later rows are the holdout. The Isolation Forest is fitted on "
         "training rows only. Each method's score threshold is chosen on training data (maximum F1; the labels are used here "
         "only to calibrate the threshold) and then applied unchanged to the holdout. **Reported metrics are holdout metrics.**", "",
         f"Chosen thresholds: A robust z >= {params['stat_z_threshold']}; B score >= {params['if_score_threshold']:.3f}.", "",
         "### 1a. Holdout metrics, seed 42 (single draw)", "",
         "| Method | Precision | Recall | F1 | TP | FP | FN | TN | FP rate |", "|---|---|---|---|---|---|---|---|---|"]
    for m in (A, B):
        g = lambda k, m=m: _get(ev, "anomaly", m, "holdout", k)  # noqa: E731
        L.append(f"| {m} | {_f(g('precision'))} | {_f(g('recall'))} | {_f(g('f1'))} | {int(g('tp'))} | {int(g('fp'))} | "
                 f"{int(g('fn'))} | {int(g('tn'))} | {_f(g('false_positive_rate'), 5)} |")
    L += ["", "Detection rate by injected anomaly type (holdout, seed 42):", "",
          "| Method | spike | drift | weekend_spend |", "|---|---|---|---|"]
    for m in (A, B):
        cells = []
        for t in ("spike", "drift", "weekend_spend"):
            n, d = _get(ev, "anomaly", m, f"holdout:{t}", "n"), _get(ev, "anomaly", m, f"holdout:{t}", "detected")
            cells.append("n/a" if not n else f"{int(d)}/{int(n)} ({d / n:.0%})")
        L.append(f"| {m} | " + " | ".join(cells) + " |")
    an = seeds[seeds.family == "anomaly"]
    L += ["", f"### 1b. Robustness across {an.seed.nunique()} independently generated datasets (holdout, mean ± sd)", "",
          "| Method | Precision | Recall | F1 | False positives | Recall: spike | Recall: drift | Recall: weekend |",
          "|---|---|---|---|---|---|---|---|"]
    for m in (A, B):
        s = an[an.model == m]
        cell = lambda c, s=s: f"{s[c].mean():.2f} ± {s[c].std():.2f}"  # noqa: E731
        L.append(f"| {m} | {cell('precision')} | {cell('recall')} | {cell('f1')} | {cell('false_positives')} | "
                 f"{cell('recall_spike')} | {cell('recall_drift')} | {cell('recall_weekend_spend')} |")
    piv = an.pivot(index="seed", columns="model", values="f1")
    L += ["", f"Method A had the higher F1 in {int((piv[A] > piv[B]).sum())}/{len(piv)} seeds. Seed 42 is one draw; "
          "prefer the table above for any claim about typical performance.", "",
          "**Reading the results.** Spikes and weekend spend are detected reliably. Gradual drift is the weak spot: a rolling "
          "baseline adapts to a slow ramp, so only the later, larger days are flagged, and the Isolation Forest (which sees the "
          "same baseline-relative signal) misses most of it. Holdout size is small (~40 positives per dataset), so single-dataset "
          "figures are noisy. A flag means *unusual versus a baseline*; it does not establish a cause.", "",
          "## 2. Forecasting", "",
          f"Grain: **daily** cost, total and per department; weekly seasonality (period {fparams['seasonal_period']}). Rolling-origin "
          f"backtest: {fparams['backtest_folds']} expanding-window folds of {fparams['backtest_horizon_days']} days, each trained only "
          "on data before its test window. MAE in dollars/day; WAPE = sum|error| / sum|actual| (undefined if actuals sum to 0). "
          f"Minimum history: {fparams['min_train_days']} days.", "",
          "- **Baseline `seasonal_naive_7d`**: repeat the last observed week (no prediction interval).",
          f"- **`ets_damped_additive_weekly`**: statsmodels ETS (additive error, damped additive trend, additive weekly seasonality) "
          f"with {fparams['interval']} prediction intervals.", "",
          "### 2a. Backtest, seed 42", "",
          "| Scope | Naive MAE | ETS MAE | Naive WAPE | ETS WAPE | ETS 80% interval coverage |", "|---|---|---|---|---|---|"]
    scopes = sorted({s for s in ev[ev.model_family == "forecast"].scope.unique()}, key=lambda s: (s != "total", s))
    for sc in scopes:
        L.append(f"| {sc} | {_f(_get(ev, 'forecast', NAIVE, sc, 'mae'), 1)} | {_f(_get(ev, 'forecast', ETS, sc, 'mae'), 1)} | "
                 f"{_f(_get(ev, 'forecast', NAIVE, sc, 'wape'))} | {_f(_get(ev, 'forecast', ETS, sc, 'wape'))} | "
                 f"{_f(_get(ev, 'forecast', ETS, sc, 'interval_coverage'), 2)} |")
    fs = seeds[seeds.family == "forecast"]
    pv = fs.pivot(index="seed", columns="model", values="wape")
    L += ["", f"### 2b. Robustness across {fs.seed.nunique()} datasets (total cost, mean ± sd)", "",
          "| Model | MAE | WAPE | 80% interval coverage |", "|---|---|---|---|"]
    for m in (NAIVE, ETS):
        s = fs[fs.model == m]
        cov = "n/a" if s["interval_coverage"].isna().all() else f"{s['interval_coverage'].mean():.2f} ± {s['interval_coverage'].std():.2f}"
        L.append(f"| {m} | {s['mae'].mean():.1f} ± {s['mae'].std():.1f} | {s['wape'].mean():.3f} ± {s['wape'].std():.3f} | {cov} |")
    L += ["", f"ETS had the lower WAPE in {int((pv[ETS] < pv[NAIVE]).sum())}/{len(pv)} seeds. The improvement over the baseline is "
          "modest. **Caveat:** the synthetic data is built from a smooth trend plus weekly seasonality, which is exactly what ETS "
          "models, so real billing data (promotions, migrations, step changes) would be harder. The training series also contains "
          "the injected anomalies. Month-end projections should be read together with their intervals.", "",
          "## 3. Optimization recommendations", "",
          "Transparent rules (versioned `v1`); thresholds are configurable in `RuleConfig`. Dollar savings are given only where a "
          "formula is supported by the data; otherwise the UI shows *Requires investigation*.", "",
          "| Rule | Recommendations produced (seed 42) |", "|---|---|"]
    counts = recs.groupby("rule_name").size() if not recs.empty else pd.Series(dtype=int)
    for rule in ("persistent_cost_increase", "repeated_budget_overrun", "nonprod_weekend_spend",
                 "cost_growth_exceeds_usage_growth", "repeated_anomalies"):
        L.append(f"| {rule} | {int(counts.get(rule, 0))} |")
    L += ["", "Rules that produce none on this dataset are not broken: they are unit-tested on crafted fixtures, and the synthetic "
          "data simply does not contain that pattern (e.g. unit prices are constant, so cost growth equals usage growth). "
          "Budgets were generated as actual spend x U(0.85, 1.10), so the overrun rule fires on random budget noise; its output "
          "demonstrates the mechanism, not a real finding.", "",
          "## 4. Limitations", "",
          "- Synthetic data; injected anomalies are simple, labelled increases. No claim is made about real-world accuracy or savings.",
          "- Thresholds are calibrated on labelled training data, which real deployments would not have.",
          "- Only increases are flagged. Level shifts and gradual drift are detected late or not at all.",
          "- Forecast intervals assume well-behaved errors; backtests cover the last ~6 months only.", ""]
    return "\n".join(L)


def main() -> int:
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
