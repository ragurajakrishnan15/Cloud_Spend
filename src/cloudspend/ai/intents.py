"""Deterministic question -> intent routing and period / member extraction. No LLM involved.

Free-form SQL requests are classified as `blocked`; the analyst never builds or runs SQL from user text.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

SUPPORTED_QUESTIONS = [
    "How much did we spend in a period, and how did it change?",
    "Explain the month-over-month cost increase (what drove the change).",
    "Which departments are furthest over budget?",
    "Summarize the three highest-impact anomalies.",
    "Give me the current forecast and its limitations.",
    "What optimization actions should we review?",
    "Draft a QBR summary for the selected period.",
    "Investigate the cost increase in depth (multi-step analysis).",
]

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NUM_ALT = "|".join(["\\d+", *NUM_WORDS])
MONTH_NAMES = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTH_ABBR = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}

_BLOCKED = [
    re.compile(r"\b(select|insert|update|delete|drop|alter|truncate|grant|merge|create)\b[\s\S]*\b(from|into|table|database|schema|view)\b", re.I),
    re.compile(r"\b(run|execute|write|generate)\b[\s\S]{0,30}\b(sql|query|queries)\b", re.I),
    re.compile(r";\s*--|--\s*$|/\*"),
]
_RULES = [  # priority order
    ("qbr", re.compile(r"\bqbr\b|quarterly (business )?review|executive summary|business review", re.I)),
    ("investigate", re.compile(r"investigat|deep[- ]?dive|root[- ]?cause|dig (in|into)|walk me through|full (analysis|picture)|"
                               r"comprehensive|end[- ]to[- ]end analysis|what(?:'s| is) going on", re.I)),
    ("forecast", re.compile(r"forecast|predict|projection|projected|next month|end of (the )?month|expected (spend|cost)", re.I)),
    ("anomalies", re.compile(r"anomal|unusual|outlier|spike|flagged|irregular", re.I)),
    ("recommendations", re.compile(r"recommend|optimi[sz]|saving|reduce (our )?(cost|spend)|cut (cost|spend)|waste|opportunit", re.I)),
    ("budget_variance", re.compile(r"budget|overspen|over spen|variance", re.I)),
    ("cost_change", re.compile(r"month[- ]over[- ]month|\bmom\b|increase|decrease|chang|driver|contribut|why did|what drove|explain|"
                               r"higher|lower|\bgrew\b|growth|\brose\b|\bfell\b", re.I)),
    ("spend_summary", re.compile(r"spend|cost|total|how much|expens|\bbill", re.I)),
]


@dataclass
class Intent:
    name: str
    top_n: int | None = None
    period: tuple[date, date] | None = None
    period_label: str | None = None
    departments: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _latest_year_for_month(month: int, dmin: date, dmax: date) -> int | None:
    for year in range(dmax.year, dmin.year - 1, -1):
        s, e = _month_range(year, month)
        if s <= dmax and e >= dmin:
            return year
    return None


def parse_period(text: str, dmin: date, dmax: date, done_months: list[pd.Timestamp]) -> tuple[date, date, str] | None:
    t = text.lower()
    m = re.search(r"\bq([1-4])\s*(?:of\s*)?(\d{4})\b", t) or None
    q = (int(m.group(1)), int(m.group(2))) if m else None
    if not q:
        m = re.search(r"\b(\d{4})\s*q([1-4])\b", t)
        q = (int(m.group(2)), int(m.group(1))) if m else None
    if q:
        sm = (q[0] - 1) * 3 + 1
        return date(q[1], sm, 1), _month_range(q[1], sm + 2)[1], f"Q{q[0]} {q[1]}"
    m = re.search(r"\b(\d{4})-(0[1-9]|1[0-2])\b", t)
    if m:
        s, e = _month_range(int(m.group(1)), int(m.group(2)))
        return s, e, f"{m.group(1)}-{m.group(2)}"
    names = {**MONTH_NAMES, **{k: v for k, v in MONTH_ABBR.items() if k != "may"}}
    alt = "|".join(sorted(names, key=len, reverse=True))
    m = re.search(rf"\b({alt})\b\.?,?\s+(\d{{4}})\b", t)
    if m:
        s, e = _month_range(int(m.group(2)), names[m.group(1)])
        return s, e, f"{calendar.month_name[names[m.group(1)]]} {m.group(2)}"
    m = re.search(rf"\b({'|'.join(sorted(MONTH_NAMES, key=len, reverse=True))})\b", t)
    if m and not (m.group(1) == "may" and not re.search(r"\b(in|for|during|of|since)\s+may\b", t)):
        month = MONTH_NAMES[m.group(1)]
        year = _latest_year_for_month(month, dmin, dmax)
        if year:
            s, e = _month_range(year, month)
            return s, e, f"{calendar.month_name[month]} {year}"
    done = sorted(done_months)
    if re.search(r"\blast month\b|previous month", t) and done:
        s = done[-1].date()
        return s, _month_range(s.year, s.month)[1], f"{calendar.month_name[s.month]} {s.year} (last complete month)"
    if re.search(r"\blast quarter\b|previous quarter", t) and done:
        have = {(d.year, d.month) for d in done}
        for d in reversed(done):
            qs = (d.month - 1) // 3 * 3 + 1
            if all((d.year, qs + i) in have for i in range(3)):
                return date(d.year, qs, 1), _month_range(d.year, qs + 2)[1], f"Q{(qs - 1) // 3 + 1} {d.year} (last complete quarter)"
    m = re.search(rf"\blast ({_NUM_ALT}) months\b", t)
    if m and done:
        n = int(m.group(1)) if m.group(1).isdigit() else NUM_WORDS[m.group(1)]
        sel = done[-n:]
        return sel[0].date(), _month_range(sel[-1].year, sel[-1].month)[1], f"last {len(sel)} complete months"
    m = re.search(r"\blast (\d+) days\b", t)
    if m:
        n = min(int(m.group(1)), 800)
        return max(dmin, dmax - timedelta(days=n - 1)), dmax, f"last {n} days"
    if re.search(r"\b(this|current) month\b", t):
        return date(dmax.year, dmax.month, 1), dmax, "current (possibly incomplete) month"
    if re.search(r"\byear[- ]to[- ]date\b|\bytd\b", t):
        return date(dmax.year, 1, 1), dmax, "year to date"
    return None


def _mentions(text: str, names: list[str]) -> tuple[str, ...]:
    t = text.lower()
    return tuple(n for n in names if re.search(rf"(?<!\w){re.escape(n.lower())}(?!\w)", t))


def _top_n(text: str) -> int | None:
    t = text.lower()
    m = re.search(rf"\b(?:top|highest|largest|biggest|worst|first)(?:[\s-]*impact)?[\s-]*({_NUM_ALT})\b", t) or \
        re.search(rf"\b({_NUM_ALT})\s+(?:highest|largest|biggest|top|worst|most|furthest)", t)
    if not m:
        return None
    g = m.group(1)
    return int(g) if g.isdigit() else NUM_WORDS[g]


def classify(question: str, members: dict[str, list[str]], data_range: tuple[date, date],
             done_months: list[pd.Timestamp]) -> Intent:
    q = (question or "").strip()
    if not q:
        return Intent("unsupported", notes=["Empty question."])
    if any(p.search(q) for p in _BLOCKED):
        return Intent("blocked")
    name = next((n for n, rx in _RULES if rx.search(q)), "unsupported")
    intent = Intent(name, top_n=_top_n(q))
    intent.departments = _mentions(q, members["departments"])
    intent.services = _mentions(q, members["services"])
    intent.environments = _mentions(q, members["environments"])
    intent.regions = _mentions(q, members["regions"])
    p = parse_period(q, data_range[0], data_range[1], done_months)
    if p:
        intent.period, intent.period_label = (p[0], p[1]), p[2]
    return intent
