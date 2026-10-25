"""Evidence ledger: every number an answer may cite is registered here with its unit and source.

Deterministic narratives format numbers only through `Ledger.fmt*`, so they cannot print an unregistered number.
`ungrounded_numbers` checks free text (e.g. from an optional LLM) and returns numbers that match no ledger entry.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

UNITS = ("usd", "pct", "pctpts", "count", "days", "ratio")


@dataclass(frozen=True)
class Figure:
    id: str
    label: str
    value: float
    unit: str       # usd | pct (fraction) | pctpts (already percentage points) | count | days | ratio
    source: str     # tool name + formula / table the value came from


class Ledger:
    def __init__(self) -> None:
        self._figures: dict[str, Figure] = {}

    # ---------------------------------------------------------------- building
    def add(self, fig_id: str, label: str, value, unit: str, source: str) -> None:
        """Register a figure. None / NaN values are skipped (not available), never zero-filled."""
        if unit not in UNITS:
            raise ValueError(f"unknown unit {unit!r}")
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return
        self._figures[fig_id] = Figure(fig_id, label, float(value), unit, source)

    def merge(self, other: Ledger, prefix: str = "") -> None:
        for f in other.figures():
            self._figures[prefix + f.id] = Figure(prefix + f.id, f.label, f.value, f.unit, f.source)

    # ---------------------------------------------------------------- access
    def has(self, fig_id: str) -> bool:
        return fig_id in self._figures

    def get(self, fig_id: str) -> Figure:
        return self._figures[fig_id]

    def figures(self) -> list[Figure]:
        return list(self._figures.values())

    def __len__(self) -> int:
        return len(self._figures)

    # ---------------------------------------------------------------- formatting
    def fmt(self, fig_id: str, signed: bool = False) -> str:
        f = self._figures[fig_id]
        v = f.value
        sign = ("+" if v > 0 else "") if signed else ""
        if f.unit == "usd":
            body = f"${abs(v):,.0f}"
            return ("-" if v < 0 else sign) + body
        if f.unit == "pct":
            return f"{sign}{v * 100:.1f}%"
        if f.unit == "pctpts":
            return f"{sign}{v:.1f}%"
        if f.unit == "count":
            return f"{sign}{int(round(v)):,}"
        if f.unit == "days":
            return f"{int(round(v))} days"
        return f"{sign}{v:.2f}"

    def fmt_signed(self, fig_id: str) -> str:
        return self.fmt(fig_id, signed=True)

    # ---------------------------------------------------------------- grounding check
    def ungrounded_numbers(self, text: str) -> list[str]:
        """Numbers in `text` that match no ledger figure (within display-rounding tolerance)."""
        return [tok for tok, ok in ((t, self._matches(t)) for t in _numeric_tokens(text)) if not ok]

    def _matches(self, token: str) -> bool:
        parsed = _parse_token(token)
        if parsed is None:
            return True
        x, tol, is_pct, is_usd = parsed
        figs = self._figures.values()
        if is_pct:
            return any((f.unit == "pct" and abs(abs(f.value) * 100 - abs(x)) <= tol + 1e-9)
                       or (f.unit == "pctpts" and abs(abs(f.value) - abs(x)) <= tol + 1e-9) for f in figs)
        if is_usd:
            return any(f.unit == "usd" and abs(abs(f.value) - abs(x)) <= tol + 1e-9 for f in figs)
        if float(x).is_integer() and abs(x) <= 10:
            return True  # enumerations / small counts
        return any(abs(abs(f.value) - abs(x)) <= tol + 1e-9 for f in figs)


_NUM = re.compile(r"[-+]?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[KkMmBb]?%?")
_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9}


def _clean(text: str) -> str:
    text = re.sub(r"`[^`]*`", " ", text)                                  # code spans (ids)
    text = re.sub(r"\b[A-Za-z]+-\d+\b", " ", text)                        # resource-style ids, e.g. res-0070
    text = re.sub(r"\b\d{4}-\d{2}(?:-\d{2})?\b", " ", text)               # dates / year-months
    text = re.sub(r"\bQ[1-4]\b", " ", text)                               # quarters
    text = re.sub(r"\bv\d+\b", " ", text)                                 # versions
    text = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)                       # years
    text = re.sub(r"(?m)^\s*\d+[.)]\s", " ", text)                        # list numbering
    return text


def _numeric_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _NUM.finditer(_clean(text))]


def _parse_token(token: str) -> tuple[float, float, bool, bool] | None:
    t = token.strip()
    is_pct, is_usd = t.endswith("%"), "$" in t
    t = t.rstrip("%").replace("$", "").replace(",", "")
    mult = 1.0
    if t and t[-1] in "KkMmBb":
        mult, t = _SUFFIX[t[-1].lower()], t[:-1]
    try:
        x = float(t)
    except ValueError:
        return None
    decimals = len(t.split(".")[1]) if "." in t else 0
    tol = 0.5 * 10 ** (-decimals) * mult
    return x * mult, tol, is_pct, is_usd
