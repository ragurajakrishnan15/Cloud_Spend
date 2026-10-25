"""AI Finance Analyst orchestration (safe execution model).

classify intent -> validate filters/dates -> call approved tools -> verify results -> deterministic narrative
-> (optional) LLM rewording, accepted only if every number is in the evidence ledger -> answer + limitations.

The analyst never builds or runs SQL; it can call only the tools registered in cloudspend.ai.tools.TOOLS.
Logging records intent, tool names, status and timing only (no question text, no secrets).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace

from cloudspend.ai import narrative as N
from cloudspend.ai.intents import SUPPORTED_QUESTIONS, Intent, classify
from cloudspend.ai.ledger import Ledger
from cloudspend.ai.llm import LLMProvider, grounded_or_none
from cloudspend.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from cloudspend.ai.tools import DataBundle, ToolResult, call_tool
from cloudspend.ai.validation import ToolParams, ValidationError
from cloudspend.analytics.spend_metrics import Filters, complete_months
from cloudspend.reporting.qbr_summary import QBRReport, build_qbr

log = logging.getLogger("cloudspend.analyst")


@dataclass
class Answer:
    question: str
    intent: str
    status: str                      # ok | unsupported | blocked | invalid | no_data
    text: str
    period: str | None = None
    results: list[ToolResult] = field(default_factory=list)
    ledger: Ledger = field(default_factory=Ledger)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mode: str = "deterministic"      # deterministic | llm
    qbr: QBRReport | None = None
    duration_ms: float = 0.0


_PLANS = {
    "spend_summary": [("get_spend_summary", {})],
    "cost_change": [("get_spend_summary", {}), ("get_top_cost_drivers", {"dimension": "service_name"}),
                    ("get_top_cost_drivers", {"dimension": "department_name"})],
    "budget_variance": [("get_budget_variance", {})],
    "anomalies": [("get_anomalies", {})],
    "forecast": [("get_forecast", {})],
    "recommendations": [("get_optimization_recommendations", {})],
    "qbr": [("generate_qbr_metrics", {})],
}


def _params(defaults: Filters, intent: Intent) -> ToolParams:
    start, end = intent.period or (defaults.start, defaults.end)
    scope = intent.departments[0] if intent.name == "forecast" and len(intent.departments) == 1 else "total"
    return ToolParams(
        start=start, end=end,
        departments=intent.departments or defaults.departments, services=intent.services or defaults.services,
        environments=intent.environments or defaults.environments, regions=intent.regions or defaults.regions,
        top_n=intent.top_n or 5, scope=scope,
    )


def _narrate(intent: str, results: list[ToolResult], question: str = "") -> tuple[str, QBRReport | None]:
    r = results[0]
    if intent == "spend_summary":
        return N.premise_note(question, results) + N.summarize_spend(r), None
    if intent == "cost_change":
        body = "\n\n".join([N.summarize_spend(results[0]), N.summarize_drivers(results[1]), N.summarize_drivers(results[2])])
        return N.premise_note(question, results) + body, None
    if intent == "budget_variance":
        return N.summarize_budget(r), None
    if intent == "anomalies":
        return N.summarize_anomalies(r), None
    if intent == "forecast":
        return N.summarize_forecast(r), None
    if intent == "recommendations":
        return N.summarize_recommendations(r), None
    report = build_qbr(r)
    return report.to_markdown(), report


def answer(question: str, bundle: DataBundle, defaults: Filters, llm: LLMProvider | None = None) -> Answer:
    t0 = time.perf_counter()
    intent = classify(question, bundle.members(), bundle.data_range(), list(complete_months(bundle.daily)))
    base = Answer(question, intent.name, "ok", "")
    if intent.name == "blocked":
        base.status = "blocked"
        base.text = ("I can't run free-form SQL or queries. I answer questions using a fixed set of approved calculations. "
                     "Try one of these:\n" + "\n".join(f"- {q}" for q in SUPPORTED_QUESTIONS))
    elif intent.name == "unsupported":
        base.status = "unsupported"
        base.text = ("I can't answer that from the available data. Supported questions include:\n"
                     + "\n".join(f"- {q}" for q in SUPPORTED_QUESTIONS))
    if base.status != "ok":
        base.duration_ms = (time.perf_counter() - t0) * 1000
        log.info("intent=%s status=%s ms=%.1f", intent.name, base.status, base.duration_ms)
        return base

    try:
        params = _params(defaults, intent)
        results = [call_tool(name, bundle, params, **kw) for name, kw in _PLANS[intent.name]]
    except ValidationError as exc:
        base.status, base.text = "invalid", str(exc)
        log.info("intent=%s status=invalid", intent.name)
        return base

    ledger = Ledger()
    for i, r in enumerate(results):
        ledger.merge(r.figures, prefix=f"{i}.")
    text, qbr = _narrate(intent.name, results, question)
    limits = N.collect_limitations(results, ["All data is synthetic."])
    ans = replace(base, text=text, period=results[0].facts.get("period") or f"{params.start} to {params.end}",
                  results=results, ledger=ledger, limitations=limits, qbr=qbr)
    if all(r.status in ("empty", "unavailable") for r in results):
        ans.status = "no_data"

    if llm is not None and ans.status == "ok" and intent.name != "qbr":
        try:
            llm_text, bad = grounded_or_none(llm, SYSTEM_PROMPT, build_user_prompt(question, intent.name, results, ledger, limits), ledger)
        except Exception as exc:  # provider failure must never break the deterministic answer
            llm_text, bad = None, [f"provider error: {type(exc).__name__}"]
        if llm_text:
            ans.text, ans.mode = llm_text, "llm"
        else:
            ans.warnings.append("AI wording was rejected (" + ", ".join(bad[:5]) + "); showing the deterministic summary.")

    ans.duration_ms = (time.perf_counter() - t0) * 1000
    log.info("intent=%s tools=%s status=%s mode=%s ms=%.1f", intent.name, [r.tool for r in results], ans.status, ans.mode, ans.duration_ms)
    return ans
