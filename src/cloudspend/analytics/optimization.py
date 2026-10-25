"""Transparent, rule-based optimization recommendations (no opaque model).

Every recommendation carries its rule name/version, the period and evidence used, a suggested next step for an
analyst, and an evidence-strength label. Dollar savings are filled in ONLY when the data supports a formula
(currently just the repeated-anomaly rule, as an upper bound); otherwise `estimated_savings` is None and the UI
shows "Requires investigation". Nothing here changes any infrastructure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import pandas as pd

from cloudspend.analytics.spend_metrics import complete_months, safe_pct

RULE_VERSION = "v1"
COLUMNS = ["recommendation_id", "rule_name", "rule_version", "department_name", "service_name", "period_start",
           "period_end", "evidence", "suggested_action", "estimated_savings", "savings_formula", "confidence",
           "review_status"]


@dataclass(frozen=True)
class RuleConfig:
    growth_months: int = 3               # persistent increase: consecutive rising months required
    growth_threshold: float = 0.10       # ... with cumulative growth at least this
    overrun_window: int = 6              # repeated overrun: look at the last N complete months
    overrun_min_months: int = 4          # ... at least this many over budget
    overrun_min_pct: float = 0.05        # ... where "over budget" means >= 5% above budget
    weekend_ratio: float = 0.90          # non-prod weekend/weekday daily-cost ratio considered "not scaled down"
    weekend_min_spend: float = 300.0     # ignore trivially small non-prod weekend spend (window total)
    weekend_months: int = 3
    divergence_months: int = 3
    divergence_gap: float = 0.05         # cost growth exceeds usage growth by at least 5 points
    anomaly_window_days: int = 90
    anomaly_min_records: int = 3


def _rec_id(rule: str, dept: str, service: str, period_end) -> str:
    return "rec-" + hashlib.sha1(f"{rule}|{dept}|{service}|{period_end}".encode()).hexdigest()[:12]


def _rec(rule, dept, service, start, end, evidence: dict, action, confidence, savings=None, formula=None) -> dict:
    return {
        "recommendation_id": _rec_id(rule, dept, service, end), "rule_name": rule, "rule_version": RULE_VERSION,
        "department_name": dept, "service_name": service,
        "period_start": pd.Timestamp(start).date(), "period_end": pd.Timestamp(end).date(),
        "evidence": json.dumps(evidence, default=str, sort_keys=True), "suggested_action": action,
        "estimated_savings": savings, "savings_formula": formula, "confidence": confidence,
        "review_status": "NEW",
    }


def _monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Complete-month totals per department x service (cost and usage)."""
    d = daily.assign(month_start=pd.to_datetime(daily["usage_date"]).dt.to_period("M").dt.to_timestamp())
    d = d[d["month_start"].isin(complete_months(daily))]
    cols = {"cost": ("total_cost", "sum")}
    if "usage_units" in d:
        cols["usage"] = ("usage_units", "sum")
    return d.groupby(["department_name", "service_name", "month_start"], as_index=False).agg(**cols)


def rule_persistent_increase(daily: pd.DataFrame, cfg: RuleConfig) -> list[dict]:
    out = []
    for (dept, svc), g in _monthly(daily).groupby(["department_name", "service_name"]):
        g = g.sort_values("month_start")
        cost = g["cost"].to_numpy()
        run = 0  # consecutive month-over-month increases ending at the latest complete month
        for i in range(len(cost) - 1, 0, -1):
            if cost[i] > cost[i - 1]:
                run += 1
            else:
                break
        if run < cfg.growth_months:
            continue
        base, last = cost[len(cost) - 1 - run], cost[-1]
        growth = safe_pct(last - base, base)
        if growth is None or growth < cfg.growth_threshold:
            continue
        months = g["month_start"].iloc[len(cost) - 1 - run:]
        conf = "High" if run >= 6 else "Medium" if run >= 4 else "Low"
        out.append(_rec(
            "persistent_cost_increase", dept, svc, months.iloc[0], months.iloc[-1] + pd.offsets.MonthEnd(0),
            {"consecutive_increasing_months": run, "cost_start": round(float(base), 2), "cost_latest": round(float(last), 2),
             "cumulative_growth_pct": round(growth * 100, 1)},
            "Confirm whether this growth is expected (new workloads) or reflects capacity that is no longer needed.",
            conf))
    return out


def rule_repeated_overrun(budget_variance: pd.DataFrame, daily: pd.DataFrame, cfg: RuleConfig) -> list[dict]:
    done = sorted(complete_months(daily))[-cfg.overrun_window:]
    bv = budget_variance[pd.to_datetime(budget_variance["month_start"]).isin(done)]
    out = []
    for (dept, svc), g in bv.groupby(["department_name", "service_name"]):
        g = g[g["budget_amount"] > 0]
        over = g[(g["actual_cost"] - g["budget_amount"]) / g["budget_amount"] >= cfg.overrun_min_pct]
        if len(over) < cfg.overrun_min_months:
            continue
        total_over = float((over["actual_cost"] - over["budget_amount"]).sum())
        conf = "High" if len(over) == len(g) and len(g) >= cfg.overrun_window else "Medium" if len(over) >= 5 else "Low"
        out.append(_rec(
            "repeated_budget_overrun", dept, svc, min(done), max(done) + pd.offsets.MonthEnd(0),
            {"months_over_budget": len(over), "months_with_budget": len(g), "min_overrun_pct": cfg.overrun_min_pct * 100,
             "total_overrun": round(total_over, 2),
             "avg_overrun_pct": round(float(((over["actual_cost"] - over["budget_amount"]) / over["budget_amount"]).mean() * 100), 1)},
            "Review the budget assumptions and the drivers of the recurring overrun with the owning team.",
            conf))
    return out


def rule_nonprod_weekend(daily: pd.DataFrame, cfg: RuleConfig) -> list[dict]:
    done = sorted(complete_months(daily))[-cfg.weekend_months:]
    if not done:
        return []
    start, end = min(done), max(done) + pd.offsets.MonthEnd(0)
    d = daily.assign(usage_date=pd.to_datetime(daily["usage_date"]))
    d = d[(d["usage_date"] >= start) & (d["usage_date"] <= end) & (d["environment_name"] != "production")]
    d["weekend"] = d["usage_date"].dt.dayofweek >= 5
    out = []
    for (dept, svc), g in d.groupby(["department_name", "service_name"]):
        per_day = g.groupby(["usage_date", "weekend"], as_index=False)["total_cost"].sum()
        wk, we = per_day[~per_day["weekend"]]["total_cost"], per_day[per_day["weekend"]]["total_cost"]
        if wk.empty or we.empty:
            continue
        ratio = safe_pct(we.mean(), wk.mean())
        if ratio is None or ratio < cfg.weekend_ratio or we.sum() < cfg.weekend_min_spend:
            continue
        out.append(_rec(
            "nonprod_weekend_spend", dept, svc, start, end,
            {"weekend_to_weekday_daily_cost_ratio": round(ratio, 3), "nonprod_weekend_spend": round(float(we.sum()), 2),
             "avg_weekday_cost": round(float(wk.mean()), 2), "avg_weekend_cost": round(float(we.mean()), 2)},
            "Check whether non-production resources can be scheduled off or scaled down at weekends.", "Low"))
    return out


def rule_cost_vs_usage(daily: pd.DataFrame, cfg: RuleConfig) -> list[dict]:
    if "usage_units" not in daily:
        return []
    out = []
    for (dept, svc), g in _monthly(daily).groupby(["department_name", "service_name"]):
        g = g.sort_values("month_start")
        if len(g) <= cfg.divergence_months:
            continue
        a, b = g.iloc[-1 - cfg.divergence_months], g.iloc[-1]
        cost_g, usage_g = safe_pct(b["cost"] - a["cost"], a["cost"]), safe_pct(b["usage"] - a["usage"], a["usage"])
        if cost_g is None or usage_g is None or cost_g - usage_g < cfg.divergence_gap:
            continue
        out.append(_rec(
            "cost_growth_exceeds_usage_growth", dept, svc, a["month_start"], b["month_start"] + pd.offsets.MonthEnd(0),
            {"cost_growth_pct": round(cost_g * 100, 1), "usage_growth_pct": round(usage_g * 100, 1),
             "gap_points": round((cost_g - usage_g) * 100, 1)},
            "Cost is growing faster than usage: look for rate changes, pricing tier shifts or a change in service mix.",
            "Medium"))
    return out


def rule_repeated_anomalies(anomalies: pd.DataFrame, as_of: pd.Timestamp, cfg: RuleConfig) -> list[dict]:
    if anomalies.empty:
        return []
    a = anomalies.assign(usage_date=pd.to_datetime(anomalies["usage_date"]))
    start = as_of - pd.Timedelta(days=cfg.anomaly_window_days - 1)
    a = a[(a["usage_date"] >= start) & (a["usage_date"] <= as_of)]
    out = []
    for (dept, svc), g in a.groupby(["department_name", "service_name"]):
        u = g.sort_values("detection_method").drop_duplicates("record_id")  # one row per flagged record
        if len(u) < cfg.anomaly_min_records:
            continue
        both = int((g.groupby("record_id")["detection_method"].nunique() > 1).sum())
        excess = float((u["observed_cost"].astype(float) - u["baseline_cost"].astype(float)).clip(lower=0).sum())
        out.append(_rec(
            "repeated_anomalies", dept, svc, start, as_of,
            {"flagged_records": len(u), "flagged_by_both_methods": both, "excess_over_baseline": round(excess, 2),
             "window_days": cfg.anomaly_window_days},
            "Investigate the flagged days for a common cause (deployments, misconfiguration, runaway jobs).",
            "Medium" if len(u) >= 5 else "Low",
            savings=round(excess, 2),
            formula="Upper bound: sum of max(observed - baseline, 0) over flagged records in the window; "
                    "realised only if the excess was avoidable."))
    return out


def generate_recommendations(daily: pd.DataFrame, budget_variance: pd.DataFrame, anomalies: pd.DataFrame,
                             cfg: RuleConfig = RuleConfig()) -> pd.DataFrame:
    as_of = pd.to_datetime(daily["usage_date"]).max()
    recs = (rule_persistent_increase(daily, cfg) + rule_repeated_overrun(budget_variance, daily, cfg)
            + rule_nonprod_weekend(daily, cfg) + rule_cost_vs_usage(daily, cfg)
            + rule_repeated_anomalies(anomalies, as_of, cfg))
    return pd.DataFrame(recs, columns=COLUMNS)
