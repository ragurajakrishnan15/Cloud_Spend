"""Quarterly business review summary: seven fixed sections built from verified tool results only.

Every number comes from a ToolResult ledger (via cloudspend.ai.narrative); the QBR ledger is the union of those
ledgers, so `report.ledger.ungrounded_numbers(markdown)` is empty by construction (and tested).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from cloudspend.ai import narrative as N
from cloudspend.ai.ledger import Ledger
from cloudspend.ai.tools import ToolResult

SECTION_TITLES = [
    "Executive summary",
    "Spending and budget performance",
    "Largest cost drivers",
    "Significant anomalies",
    "Forecast and risks",
    "Potential optimization actions",
    "Follow-up questions and data limitations",
]


@dataclass
class QBRReport:
    period: str
    sections: list[tuple[str, str]]
    ledger: Ledger
    limitations: list[str]
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)

    def to_markdown(self) -> str:
        out = [f"# QBR Summary - {self.period}",
               "_All figures are synthetic and are produced by approved calculations; nothing is estimated by an AI model._", ""]
        for i, (title, body) in enumerate(self.sections, 1):
            out += [f"## {i}. {title}", "", body, ""]
        return "\n".join(out)


def _executive_summary(parts: dict[str, ToolResult]) -> str:
    bullets = []
    s = parts["summary"]
    if s.status == "ok":
        L = s.figures
        line = f"- Total spend for {s.facts['period']} was **{L.fmt('total_cost')}**"
        if L.has("change_pct"):
            line += f" ({L.fmt_signed('change_pct')} versus the previous period)"
        bullets.append(line + ".")
        if L.has("variance"):
            bullets.append(f"- Spend is {L.fmt_signed('variance')} ({L.fmt_signed('variance_pct')}) versus budget (positive = over budget).")
    a = parts["anomalies"]
    if a.status == "ok":
        bullets.append(f"- {a.figures.fmt('flagged_count')} resource-days were flagged as unusual versus their baselines "
                       f"({a.figures.fmt('excess')} above baseline).")
    fc = parts["forecast"]
    if fc.status == "ok" and fc.facts["months"]:
        m = fc.facts["months"][0]
        L, k = fc.figures, fc.facts["months"][0]["key"]
        line = f"- {m['label']} is projected at **{L.fmt(f'proj_{k}_projected')}**"
        if m["has_budget"]:
            line += f" ({L.fmt_signed(f'proj_{k}_variance')} versus budget)"
        bullets.append(line + ".")
    r = parts["recommendations"]
    if r.status == "ok":
        bullets.append(f"- {r.figures.fmt('rec_count')} rule-based recommendation(s) are queued for review.")
    return "\n".join(bullets) if bullets else "No headline figures are available for this period."


def _forecast_and_risks(fc: ToolResult) -> str:
    body = N.summarize_forecast(fc)
    if fc.status != "ok":
        return body
    L = fc.figures
    risks = []
    for m in fc.facts["months"]:
        k = m["key"]
        if m["has_budget"] and L.get(f"proj_{k}_variance").value > 0:
            risks.append(f"- **Budget risk:** {m['label']} is projected {L.fmt(f'proj_{k}_variance')} "
                         f"({L.fmt(f'proj_{k}_variance_pct')}) over budget.")
    return body + ("\n\n" + "\n".join(risks) if risks else "")


def _follow_ups(parts: dict[str, ToolResult]) -> list[str]:
    q = []
    for key in ("drivers_service", "drivers_department"):
        d = parts[key]
        if d.status == "ok" and d.facts["drivers"]:
            q.append(f"What is behind the change in **{d.facts['drivers'][0]['name']}** ({d.facts['dimension_label']})?")
    b = parts["budget"]
    if b.status == "ok" and b.facts["over"]:
        q.append(f"Are the budget assumptions for **{b.facts['over'][0]['name']}** still valid?")
    a = parts["anomalies"]
    if a.status == "ok" and a.facts["items"]:
        q.append(f"Were there deployments or configuration changes around {a.facts['items'][0]['date']} "
                 f"for {a.facts['items'][0]['resource']}?")
    if parts["recommendations"].status == "ok":
        q.append("Which of the listed recommendations should be assigned an owner for review?")
    return q or ["No follow-up questions were generated from the available results."]


def build_qbr(qbr: ToolResult) -> QBRReport:
    """Assemble the seven-section QBR from a generate_qbr_metrics result."""
    parts: dict[str, ToolResult] = qbr.facts["parts"]
    if qbr.status != "ok":
        body = N.summarize_spend(parts["summary"])
        return QBRReport(qbr.facts["period"], [(SECTION_TITLES[0], body)], qbr.figures, N.collect_limitations([qbr]))
    drivers = [N.summarize_drivers(parts["drivers_service"]), N.summarize_drivers(parts["drivers_department"])]
    limits = N.collect_limitations([qbr, *parts.values()], ["All data is synthetic; nothing here reflects real spend or savings."])
    follow = "**Follow-up questions**\n" + "\n".join(f"- {x}" for x in _follow_ups(parts)) + \
             "\n\n**Data limitations**\n" + "\n".join(f"- {x}" for x in limits)
    sections = [
        (SECTION_TITLES[0], _executive_summary(parts)),
        (SECTION_TITLES[1], N.summarize_spend(parts["summary"]) + "\n\n" + N.summarize_budget(parts["budget"])),
        (SECTION_TITLES[2], "\n\n".join(drivers)),
        (SECTION_TITLES[3], N.summarize_anomalies(parts["anomalies"])),
        (SECTION_TITLES[4], _forecast_and_risks(parts["forecast"])),
        (SECTION_TITLES[5], N.summarize_recommendations(parts["recommendations"])),
        (SECTION_TITLES[6], follow),
    ]
    return QBRReport(qbr.facts["period"], sections, qbr.figures, limits, qbr.tables)
