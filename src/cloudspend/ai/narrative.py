"""Deterministic narrative templates. Every number is formatted from a ToolResult's ledger (`L.fmt*`), so the text can
state only registered, sourced figures. Nothing here claims a cause or invents a saving."""

from __future__ import annotations

from cloudspend.ai.tools import ToolResult


def _unavailable(what: str, r: ToolResult) -> str:
    detail = r.limitations[0] if r.limitations else r.status
    return f"{what} is not available: {detail}"


def summarize_spend(r: ToolResult) -> str:
    if r.status != "ok":
        return _unavailable("The spend summary", r)
    L, f = r.figures, r.facts
    s = f"For **{f['period']}** ({L.fmt('days')}), total cloud spend was **{L.fmt('total_cost')}**"
    if L.has("previous_cost"):
        s += (f", versus {L.fmt('previous_cost')} in the previous period ({f['prev_period']}): a change of "
              f"**{L.fmt_signed('change_amount')} ({L.fmt_signed('change_pct')})**.")
    else:
        s += "."
    if L.has("budget"):
        s += (f" Against a budget of {L.fmt('budget')}, the variance is **{L.fmt_signed('variance')} "
              f"({L.fmt_signed('variance_pct')})** (positive = over budget).")
    return s


def summarize_drivers(r: ToolResult) -> str:
    if r.status != "ok":
        return _unavailable("The cost-driver breakdown", r)
    L, f = r.figures, r.facts
    parts = []
    for it in f["drivers"]:
        i = it["i"]
        pct = f" ({L.fmt_signed(f'driver_{i}_change_pct')})" if L.has(f"driver_{i}_change_pct") else ""
        parts.append(f"**{it['name']}** {L.fmt_signed(f'driver_{i}_change')}{pct}")
    return (f"By {f['dimension_label']}, the largest movements versus {f['prev_period']} were: " + "; ".join(parts)
            + f". The net change across all {f['dimension_label']}s was {L.fmt_signed('net_change')}. "
            "This shows what changed, not why.")


def summarize_budget(r: ToolResult) -> str:
    if r.status != "ok":
        return _unavailable("The budget comparison", r)
    L, f = r.figures, r.facts
    s = (f"Across {L.fmt('months')} complete month(s) ({f['months']}), actual spend was {L.fmt('total_actual')} against a "
         f"budget of {L.fmt('total_budget')}: variance **{L.fmt_signed('total_variance')} "
         f"({L.fmt_signed('total_variance_pct')})**. {L.fmt('depts_over')} of {L.fmt('depts_total')} departments are over budget")
    if f["over"]:
        items = []
        for it in f["over"]:
            i = it["i"]
            items.append(f"**{it['name']}** {L.fmt_signed(f'dept_{i}_variance')} ({L.fmt_signed(f'dept_{i}_variance_pct')})")
        s += ". Furthest over budget: " + "; ".join(items) + "."
    else:
        s += "; none is over budget."
    return s


def summarize_anomalies(r: ToolResult) -> str:
    if r.status != "ok":
        if r.facts.get("not_computed"):
            return "Anomaly results are not available yet (detection has not been run)."
        return _unavailable("The anomaly summary", r) if r.status != "empty" else "No records were flagged for this period and filters."
    L, f = r.figures, r.facts
    lines = [f"**{L.fmt('flagged_count')}** resource-days were flagged in {f['period']}, totalling {L.fmt('flagged_spend')} of observed "
             f"spend ({L.fmt('excess')} above their baselines); {L.fmt('high_count')} are high severity. Highest-impact flags:"]
    for it in f["items"]:
        i = it["i"]
        lines.append(f"- **{it['date']}** {it['resource']} ({it['dept']} / {it['service']}), detected by {it['methods']}: observed "
                     f"{L.fmt(f'anom_{i}_observed')} vs baseline {L.fmt(f'anom_{i}_baseline')} "
                     f"({L.fmt_signed(f'anom_{i}_diff')}, {L.fmt_signed(f'anom_{i}_pct')}).")
    if L.has("eval_f1_rolling_median_mad"):
        lines.append(f"\nOn one synthetic holdout dataset the baseline detector scored F1 {L.fmt('eval_f1_rolling_median_mad')}; "
                     "it is weakest on gradual drift.")
    return "\n".join(lines)


def summarize_forecast(r: ToolResult) -> str:
    if r.status != "ok":
        if r.facts.get("not_computed"):
            return "Forecasts are not available yet (models have not been run)."
        return _unavailable("The forecast", r)
    L, f = r.figures, r.facts
    scope = "total spend" if f["scope"] == "total" else f"{f['scope']} spend"
    lines = [f"The {f['model']} model (trained through {f['trained_through']}; horizon: {L.fmt('horizon_days')}) projects {scope}:"]
    for m in f["months"]:
        k = m["key"]
        if m["days_actual"] == 0:
            line = f"- **{m['label']}**: {L.fmt(f'proj_{k}_projected')} (forecast only; no actuals yet)"
        else:
            line = (f"- **{m['label']}**: {L.fmt(f'proj_{k}_projected')} (actual to date {L.fmt(f'proj_{k}_actual')} + forecast "
                    f"{L.fmt(f'proj_{k}_forecast')})")
        if m["has_budget"]:
            line += (f" versus a budget of {L.fmt(f'proj_{k}_budget')}: projected variance "
                     f"{L.fmt_signed(f'proj_{k}_variance')} ({L.fmt_signed(f'proj_{k}_variance_pct')}).")
        else:
            line += "; no budget is loaded for this month."
        lines.append(line)
    if L.has("ets_wape") and L.has("naive_wape"):
        lines.append(f"\nIn rolling-origin backtests the model's WAPE was {L.fmt('ets_wape')} versus {L.fmt('naive_wape')} for the "
                     "seasonal-naive baseline" + (f"; its {L.fmt('interval_level')} prediction interval covered {L.fmt('ets_coverage')} of actuals." if L.has("ets_coverage") else "."))
    return "\n".join(lines)


def summarize_recommendations(r: ToolResult) -> str:
    if r.status != "ok":
        if r.facts.get("not_computed"):
            return "No recommendations are available yet."
        return _unavailable("The recommendation list", r)
    L, f = r.figures, r.facts
    by_rule = ", ".join(f"{rule}: {L.fmt(f'rule_count_{rule}')}" for rule in f["by_rule"])
    lines = [f"**{L.fmt('rec_count')}** rule-based recommendation(s) are available for review (nothing is executed). By rule: {by_rule}."]
    for it in f["items"]:
        i = it["i"]
        ev = "; ".join(f"{k.replace('_', ' ')} {L.fmt(f'rec_{i}_{k}')}" for k in it["fields"])
        opp = (f"{L.fmt(f'rec_{i}_estimate')} (upper bound: {it['formula']})" if it["has_estimate"] else "Requires investigation")
        lines.append(f"- **{it['dept']} / {it['service']}** - {it['rule']} ({it['confidence']} evidence). Evidence: {ev}. "
                     f"Next step: {it['action']} Estimated opportunity: {opp}.")
    return "\n".join(lines)


def collect_limitations(results: list[ToolResult], extra: list[str] | None = None) -> list[str]:
    seen, out = set(), []
    for lim in [*(extra or []), *(x for r in results for x in r.limitations)]:
        if lim not in seen:
            seen.add(lim)
            out.append(lim)
    return out


def premise_note(question: str, results: list[ToolResult]) -> str:
    """Flag when the question's direction ('increase' / 'decrease') contradicts the computed change."""
    r = results[0]
    if r.tool != "get_spend_summary" or r.status != "ok" or not r.figures.has("change_amount"):
        return ""
    L, q, change = r.figures, question.lower(), r.figures.get("change_amount").value
    if change < 0 and any(w in q for w in ("increase", "grew", "growth", "rose", "higher", "went up")):
        return (f"**Note:** spend did not increase in this period; it fell by {L.fmt('change_amount').lstrip('-')} "
                f"({L.fmt('change_pct').lstrip('-')}).\n\n")
    if change > 0 and any(w in q for w in ("decrease", "fell", "drop", "lower", "went down", "reduction")):
        return (f"**Note:** spend did not decrease in this period; it rose by {L.fmt('change_amount')} "
                f"({L.fmt('change_pct')}).\n\n")
    return ""
