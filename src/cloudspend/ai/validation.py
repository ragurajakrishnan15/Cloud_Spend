"""Parameter validation for analyst tools: dates, member names and result limits. Nothing here touches the database."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

import pandas as pd

from cloudspend.analytics.spend_metrics import Filters

MAX_TOP_N = 20
MAX_RANGE_DAYS = 800
MAX_TABLE_ROWS = 50


class ValidationError(ValueError):
    """A user-facing validation message (safe to show)."""


@dataclass(frozen=True)
class ToolParams:
    start: date
    end: date
    departments: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    top_n: int = 5
    scope: str = "total"   # forecast scope: 'total' or a department name

    def filters(self) -> Filters:
        return Filters(self.start, self.end, self.departments, self.services, self.environments, self.regions)


def canonicalize(values: tuple[str, ...], allowed: list[str], what: str) -> tuple[str, ...]:
    lookup = {a.lower(): a for a in allowed}
    out = []
    for v in values:
        key = str(v).strip().lower()
        if key not in lookup:
            raise ValidationError(f"Unknown {what} '{v}'. Valid values: {', '.join(sorted(allowed))}.")
        out.append(lookup[key])
    return tuple(dict.fromkeys(out))


def validate_params(p: ToolParams, bundle) -> tuple[ToolParams, list[str]]:
    """Return canonicalised params (dates clipped to the loaded data) and notes about any adjustment."""
    notes: list[str] = []
    if p.start > p.end:
        raise ValidationError("The start date is after the end date.")
    if (p.end - p.start).days + 1 > MAX_RANGE_DAYS:
        raise ValidationError(f"The period is longer than {MAX_RANGE_DAYS} days.")
    dates = pd.to_datetime(bundle.daily["usage_date"])
    dmin, dmax = dates.min().date(), dates.max().date()
    if p.end < dmin or p.start > dmax:
        raise ValidationError(f"The data covers {dmin} to {dmax}; the requested period {p.start} to {p.end} is outside it.")
    start, end = max(p.start, dmin), min(p.end, dmax)
    if (start, end) != (p.start, p.end):
        notes.append(f"The requested period {p.start} to {p.end} was clipped to the loaded data ({start} to {end}).")
    members = bundle.members()
    scope = p.scope
    if scope.lower() != "total":
        scope = canonicalize((scope,), members["departments"], "forecast scope")[0]
    else:
        scope = "total"
    return replace(
        p, start=start, end=end, scope=scope, top_n=max(1, min(int(p.top_n), MAX_TOP_N)),
        departments=canonicalize(p.departments, members["departments"], "department"),
        services=canonicalize(p.services, members["services"], "service"),
        environments=canonicalize(p.environments, members["environments"], "environment"),
        regions=canonicalize(p.regions, members["regions"], "region"),
    ), notes
