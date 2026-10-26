"""Bounded multi-step analysis agent ("investigate ...").

Unlike the single-intent router in `analyst.py`, the agent runs a *sequence* of approved tool calls in which each step is
chosen from the results of the previous ones (e.g. drill into the largest cost driver, then check whether flagged anomalies
coincide with it). It stays inside the same safety model as the rest of the analyst:

- only tools registered in `cloudspend.ai.tools.TOOLS` can be called, with validated `ToolParams`; no SQL is built or run;
- the plan is deterministic (rule-based) and bounded by `max_steps`; skipped and failed steps are recorded, not hidden;
- every number in the answer is a ledger figure produced by a tool; an optional LLM may reword the final text but is
  rejected unless all numbers are grounded (same guard as the single-step analyst);
- every step is traced (tool, arguments, reason, status, timing) so the run can be audited in the UI.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace

from cloudspend.ai import narrative as N
from cloudspend.ai.analyst import Answer, _params
from cloudspend.ai.intents import Intent
from cloudspend.ai.ledger import Ledger
from cloudspend.ai.llm import LLMProvider, grounded_or_none
from cloudspend.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from cloudspend.ai.tools import DataBundle, ToolResult, call_tool
from cloudspend.ai.validation import ToolParams, ValidationError
from cloudspend.analytics.spend_metrics import Filters

log = logging.getLogger("cloudspend.analyst")

DEFAULT_MAX_STEPS = 8
SIGNIFICANT_CHANGE_PCT = 0.05   # a period-over-period move of at least 5% triggers the driver drill-down


@dataclass
class Step:
    n: int
    tool: str
    arguments: str          # human-readable, e.g. "dimension=service_name; services=Compute"
    reason: str
    status: str             # ok | empty | unavailable | skipped | error
    duration_ms: float = 0.0


@dataclass
class _State:
    bundle: DataBundle
    base: ToolParams
    max_steps: int
    steps: list[Step] = field(default_factory=list)
    results: dict[str, ToolResult] = field(default_factory=dict)   # keyed by step label
    ledger: Ledger = field(default_factory=Ledger)
    notes: list[str] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return sum(1 for s in self.steps if s.status != "skipped")

    def skip(self, tool: str, reason: str) -> None:
        self.steps.append(Step(len(self.steps) + 1, tool, "-", reason, "skipped"))

    def run(self, label: str, tool: str, params: ToolParams, reason: str, **kwargs) -> ToolResult | None:
        if self.calls >= self.max_steps:
            self.skip(tool, f"step budget of {self.max_steps} reached")
            if "step budget" not in " ".join(self.notes):
                self.notes.append(f"The step budget of {self.max_steps} was reached, so the investigation is partial.")
            return None
        args = "; ".join([f"{k}={v}" for k, v in kwargs.items()]
                         + ([f"services={','.join(params.services)}"] if params.services and params.services != self.base.services else []))
        step = Step(len(self.steps) + 1, tool, args or "-", reason, "ok")
        self.steps.append(step)
        try:
            res = call_tool(tool, self.bundle, params, **kwargs)
        except ValidationError:
            raise
        except Exception as exc:  # one failing step must not abort the whole investigation
            step.status = "error"
            self.notes.append(f"Step {step.n} ({tool}) failed ({type(exc).__name__}); the analysis continues without it.")
            log.warning("agent step=%s tool=%s status=error", step.n, tool)
            return None
        step.status, step.duration_ms = res.status, res.duration_ms
        self.results[label] = res
        self.ledger.merge(res.figures, prefix=f"s{step.n}.")
        return res


def _top_driver(res: ToolResult | None) -> str | None:
    if res is not None and res.status == "ok" and res.facts.get("drivers"):
        return str(res.facts["drivers"][0]["name"])
    return None


def _plan(state: _State) -> None:
    """The decision logic. Each branch inspects earlier results; nothing here computes a business number."""
    p = state.base

    summary = state.run("summary", "get_spend_summary", p, "Establish the period total, previous-period change and budget position.")
    if summary is None or summary.status != "ok":
        state.skip("get_top_cost_drivers", "no spend in the selected period, so there is nothing to break down")
        return

    has_change = summary.figures.has("change_pct")
    moved = has_change and abs(summary.figures.get("change_pct").value) >= SIGNIFICANT_CHANGE_PCT
    if not has_change:
        state.skip("get_top_cost_drivers", "no comparable previous period, so drivers of change cannot be computed")
    elif not moved:
        state.skip("get_top_cost_drivers",
                   f"spend moved by less than {SIGNIFICANT_CHANGE_PCT:.0%} versus the previous period; no drill-down needed")

    top_service = None
    if moved:
        svc = state.run("drivers_service", "get_top_cost_drivers", p, "Spend moved materially: find which services explain it.",
                        dimension="service_name")
        state.run("drivers_dept", "get_top_cost_drivers", p, "Find which departments explain the move.",
                         dimension="department_name")
        top_service = _top_driver(svc)
        if top_service:
            state.run("drill_dept", "get_top_cost_drivers", replace(p, services=(top_service,)),
                      f"Drill down: which departments drive the change within the largest service ({top_service})?",
                      dimension="department_name")

    state.run("budget", "get_budget_variance", p, "Check whether the period is over budget and where.")
    state.run("anomalies", "get_anomalies", p, "Look for flagged records in the period.")
    anomalies = state.results.get("anomalies")
    if top_service and anomalies is not None and anomalies.status == "ok":
        state.run("anomalies_driver", "get_anomalies", replace(p, services=(top_service,)),
                  f"Flagged records exist: check whether any fall in the largest cost driver ({top_service}).")
    state.run("forecast", "get_forecast", p, "Project the rest of the horizon and the expected budget position.")

    budget = state.results.get("budget")
    over = budget is not None and budget.status == "ok" and budget.figures.has("total_variance") \
        and budget.figures.get("total_variance").value > 0
    flagged = anomalies is not None and anomalies.status == "ok"
    if over or flagged:
        state.run("recs", "get_optimization_recommendations", p, "Spend is over budget or has flagged records: list review actions.")
    else:
        state.skip("get_optimization_recommendations", "no overspend or flagged records, so no review actions are warranted")


def _narrative(state: _State, period: str, question: str) -> str:
    R = state.results
    lines = [f"**Investigation of {period}** - {state.calls} analysis step(s), each an approved calculation "
             "(see the step trace for what was run and why).", ""]
    lines += ["### Headline", N.premise_note(question, [R["summary"]]) + N.summarize_spend(R["summary"]), ""]
    if "drivers_service" in R or "drivers_dept" in R:   # either may be missing if a step failed or the budget ran out
        lines += ["### What moved", *(N.summarize_drivers(R[k]) for k in ("drivers_service", "drivers_dept") if k in R)]
        if "drill_dept" in R and R["drill_dept"].status == "ok":
            top = _top_driver(R["drivers_service"])
            lines.append(f"Within **{top}** alone: " + N.summarize_drivers(R["drill_dept"]))
        lines.append("")
    elif state.steps and any(s.tool == "get_top_cost_drivers" and s.status == "skipped" for s in state.steps):
        reason = next(s.reason for s in state.steps if s.tool == "get_top_cost_drivers" and s.status == "skipped")
        lines += ["### What moved", f"No driver breakdown was run: {reason}.", ""]
    if "budget" in R:
        lines += ["### Budget", N.summarize_budget(R["budget"]), ""]
    if "anomalies" in R:
        lines += ["### Unusual costs", N.summarize_anomalies(R["anomalies"])]
        ad = R.get("anomalies_driver")
        if ad is not None:
            top = _top_driver(R.get("drivers_service")) or "the top driver"
            if ad.status == "ok":
                L = ad.figures
                lines.append(f"**Cross-check:** {L.fmt('flagged_count')} flagged record(s) totalling {L.fmt('flagged_spend')} fall in "
                             f"**{top}**, the largest cost driver. That is a coincidence worth reviewing, not an established cause.")
            else:
                lines.append(f"**Cross-check:** no flagged records fall in **{top}**, so the largest cost driver is not explained by "
                             "the flagged anomalies.")
        lines.append("")
    if "forecast" in R:
        lines += ["### Outlook", N.summarize_forecast(R["forecast"]), ""]
    if "recs" in R:
        lines += ["### Suggested review actions", N.summarize_recommendations(R["recs"]), ""]
    return "\n".join(lines).rstrip() + "\n"


def investigate(question: str, bundle: DataBundle, defaults: Filters, intent: Intent, llm: LLMProvider | None = None,
                max_steps: int = DEFAULT_MAX_STEPS) -> Answer:
    t0 = time.perf_counter()
    base = Answer(question, "investigate", "ok", "")
    max_steps = max(1, min(int(max_steps), 12))
    try:
        state = _State(bundle, _params(defaults, intent), max_steps)
        _plan(state)
    except ValidationError as exc:
        base.status, base.text = "invalid", str(exc)
        return base

    results = list(state.results.values())
    summary = state.results.get("summary")
    if summary is None or all(r.status in ("empty", "unavailable") for r in results):
        base.status = "no_data"
        base.text = "There is no spend for the selected period and filters, so there is nothing to investigate."
        base.trace = state.steps
        base.limitations = N.collect_limitations(results, ["All data is synthetic."])
        return base

    period = summary.facts.get("period") or f"{state.base.start} to {state.base.end}"
    text = _narrative(state, period, question)
    limits = N.collect_limitations(results, ["All data is synthetic.", *state.notes])
    ans = replace(base, text=text, period=period, results=results, ledger=state.ledger, limitations=limits,
                  trace=state.steps)

    if llm is not None:
        try:
            llm_text, bad = grounded_or_none(llm, SYSTEM_PROMPT, build_user_prompt(question, "investigate", results, state.ledger, limits),
                                             state.ledger)
        except Exception as exc:
            llm_text, bad = None, [f"provider error: {type(exc).__name__}"]
        if llm_text:
            ans.text, ans.mode = llm_text, "llm"
        else:
            ans.warnings.append("AI wording was rejected (" + ", ".join(bad[:5]) + "); showing the deterministic summary.")

    ans.duration_ms = (time.perf_counter() - t0) * 1000
    log.info("intent=investigate steps=%s status=%s mode=%s ms=%.1f", [s.tool for s in state.steps if s.status != "skipped"],
             ans.status, ans.mode, ans.duration_ms)
    return ans
