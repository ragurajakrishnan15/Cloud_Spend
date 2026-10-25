"""Reproducible synthetic cloud-billing generator.

Grain: one row per resource per day. Budgets are emitted separately at
department x service x month grain so they can never be double-counted by
summing daily rows.

All data is synthetic. Run:
    python -m cloudspend.data_generation.generate_billing --profile demo --seed 42
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import DEFAULT_SEED, GENERATED_DIR

DEPARTMENTS = ["Engineering", "Data Science", "Marketing Tech", "Finance IT", "Support", "Platform"]
ENVIRONMENTS = ["production", "staging", "development"]
REGIONS = ["region-us-east", "region-us-west", "region-eu-central", "region-ap-south"]

# service -> (base daily units, unit_cost, noise sigma, annual growth, weekday-heavy)
SERVICES: dict[str, tuple[float, float, float, float, bool]] = {
    "Compute": (400.0, 0.12, 0.08, 0.25, True),
    "Object Storage": (900.0, 0.023, 0.03, 0.35, False),
    "Database": (150.0, 0.45, 0.06, 0.20, True),
    "Data Warehouse": (120.0, 0.60, 0.12, 0.30, True),
    "Networking": (500.0, 0.05, 0.10, 0.15, False),
    "Analytics": (80.0, 0.90, 0.10, 0.28, True),
    "Machine Learning": (60.0, 1.40, 0.15, 0.40, True),
    "Monitoring": (300.0, 0.03, 0.05, 0.10, False),
}
ENV_SCALE = {"production": 1.0, "staging": 0.35, "development": 0.2}

ANOMALY_TYPES = ("spike", "drift", "weekend_spend")

BILLING_COLUMNS = [
    "record_id", "usage_date", "department", "service_name", "environment", "region",
    "resource_id", "usage_units", "unit_cost", "total_cost",
    "is_injected_anomaly", "anomaly_type", "generated_at",
]
BUDGET_COLUMNS = ["budget_month", "department", "service_name", "budget_amount"]


@dataclass(frozen=True)
class Profile:
    start: date
    days: int
    n_resources: int
    n_spikes: int
    n_drifts: int
    n_weekend: int


PROFILES: dict[str, Profile] = {
    "dev": Profile(date(2025, 1, 1), 180, 24, 6, 2, 3),
    "demo": Profile(date(2024, 7, 1), 548, 72, 30, 8, 10),  # ~18 months
}

MIN_CLEAN_HISTORY_DAYS = 60  # no anomalies injected before this, so baselines have clean history


def _build_resources(rng: np.random.Generator, n: int) -> pd.DataFrame:
    """Create a fixed set of resources, each tied to one dept/service/env/region."""
    rows = []
    services = list(SERVICES)
    for i in range(n):
        rows.append(
            {
                "resource_id": f"res-{i:04d}",
                "department": DEPARTMENTS[i % len(DEPARTMENTS)],
                "service_name": services[int(rng.integers(len(services)))],
                "environment": rng.choice(ENVIRONMENTS, p=[0.55, 0.25, 0.20]),
                "region": rng.choice(REGIONS, p=[0.4, 0.25, 0.2, 0.15]),
                "size_factor": float(rng.lognormal(0.0, 0.5)),
            }
        )
    return pd.DataFrame(rows)


def _base_usage(rng: np.random.Generator, resources: pd.DataFrame, dates: pd.DatetimeIndex) -> np.ndarray:
    """Return usage matrix [n_resources, n_days] with trend, weekly and yearly seasonality."""
    t = np.arange(len(dates))
    dow = dates.dayofweek.to_numpy()
    doy = dates.dayofyear.to_numpy()
    out = np.empty((len(resources), len(dates)))
    for i, r in enumerate(resources.itertuples()):
        base, _, sigma, growth, weekday_heavy = SERVICES[r.service_name]
        trend = 1.0 + growth * t / 365.0
        weekly = np.where(dow >= 5, 0.7 if weekday_heavy else 0.95, 1.0)
        yearly = 1.0 + 0.05 * np.sin(2 * np.pi * doy / 365.25)
        noise = rng.lognormal(0.0, sigma, size=len(dates))
        out[i] = base * r.size_factor * ENV_SCALE[r.environment] * trend * weekly * yearly * noise
    return out


def _inject_anomalies(
    rng: np.random.Generator, resources: pd.DataFrame, dates: pd.DatetimeIndex,
    usage: np.ndarray, profile: Profile,
) -> tuple[np.ndarray, np.ndarray]:
    """Modify usage in place; return boolean label matrix and type matrix."""
    n_res, n_days = usage.shape
    labels = np.zeros((n_res, n_days), dtype=bool)
    types = np.full((n_res, n_days), "", dtype=object)
    lo = MIN_CLEAN_HISTORY_DAYS
    dow = dates.dayofweek.to_numpy()

    # Single-day spikes: usage x (3..6)
    for _ in range(profile.n_spikes):
        for _try in range(50):
            i, d = int(rng.integers(n_res)), int(rng.integers(lo, n_days))
            if not labels[i, d]:
                usage[i, d] *= rng.uniform(3.0, 6.0)
                labels[i, d], types[i, d] = True, "spike"
                break

    # Gradual drift: 14-day ramp up to x2.2, only the 2nd half is labelled as clearly abnormal
    for _ in range(profile.n_drifts):
        for _try in range(50):
            i, d0 = int(rng.integers(n_res)), int(rng.integers(lo, n_days - 14))
            if not labels[i, d0:d0 + 14].any():
                ramp = np.linspace(1.0, 2.2, 14)
                usage[i, d0:d0 + 14] *= ramp
                labels[i, d0 + 7:d0 + 14] = True
                types[i, d0 + 7:d0 + 14] = "drift"
                break

    # Unusual weekend spend on non-production resources: x3 on a weekend day
    nonprod = np.flatnonzero(resources["environment"].to_numpy() != "production")
    weekend_days = np.flatnonzero(dow >= 5)
    weekend_days = weekend_days[weekend_days >= lo]
    for _ in range(profile.n_weekend):
        if len(nonprod) == 0:
            break
        for _try in range(50):
            i, d = int(rng.choice(nonprod)), int(rng.choice(weekend_days))
            if not labels[i, d]:
                usage[i, d] *= 3.0
                labels[i, d], types[i, d] = True, "weekend_spend"
                break
    return labels, types


def generate_budgets(billing: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Monthly budget per department x service: expected spend x a planning factor.

    Budget = actual monthly spend x U(0.85, 1.10), so some groups run over budget.
    """
    df = billing.assign(budget_month=pd.to_datetime(billing["usage_date"]).dt.to_period("M").dt.to_timestamp())
    g = df.groupby(["budget_month", "department", "service_name"], as_index=False)["total_cost"].sum()
    g["budget_amount"] = (g["total_cost"] * rng.uniform(0.85, 1.10, size=len(g))).round(2)
    g["budget_month"] = g["budget_month"].dt.date
    return g[BUDGET_COLUMNS]


def generate(profile_name: str = "demo", seed: int = DEFAULT_SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate (billing, budgets). Deterministic for a given (profile, seed)."""
    profile = PROFILES[profile_name]
    rng = np.random.default_rng(seed)
    dates = pd.date_range(profile.start, periods=profile.days, freq="D")
    resources = _build_resources(rng, profile.n_resources)
    usage = _base_usage(rng, resources, dates)
    labels, types = _inject_anomalies(rng, resources, dates, usage, profile)

    n_res, n_days = usage.shape
    unit_cost = np.array([SERVICES[s][1] for s in resources["service_name"]])
    unit_cost_m = np.repeat(unit_cost[:, None], n_days, axis=1)
    usage = np.round(usage, 2)
    total = np.round(usage * unit_cost_m, 2)

    # Fixed generation timestamp derived from seed-independent constant -> reproducible output.
    generated_at = datetime(2026, 1, 1, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    billing = pd.DataFrame(
        {
            "usage_date": np.tile(dates.date, n_res),
            "resource_id": np.repeat(resources["resource_id"].to_numpy(), n_days),
            "department": np.repeat(resources["department"].to_numpy(), n_days),
            "service_name": np.repeat(resources["service_name"].to_numpy(), n_days),
            "environment": np.repeat(resources["environment"].to_numpy(), n_days),
            "region": np.repeat(resources["region"].to_numpy(), n_days),
            "usage_units": usage.ravel(),
            "unit_cost": unit_cost_m.ravel(),
            "total_cost": total.ravel(),
            "is_injected_anomaly": labels.ravel(),
            "anomaly_type": np.where(labels.ravel(), types.ravel(), None),
            "generated_at": generated_at,
        }
    )
    billing = billing.sort_values(["usage_date", "resource_id"], kind="stable").reset_index(drop=True)
    billing.insert(0, "record_id", [f"{profile_name}-rec-{i:08d}" for i in range(len(billing))])
    billing = billing[BILLING_COLUMNS]
    budgets = generate_budgets(billing, rng)
    return billing, budgets


def write_outputs(billing: pd.DataFrame, budgets: pd.DataFrame, out_dir: Path, profile: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    b_path = out_dir / f"cloud_billing_{profile}.csv"
    g_path = out_dir / f"budgets_{profile}.csv"
    billing.to_csv(b_path, index=False)
    budgets.to_csv(g_path, index=False)
    return b_path, g_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate synthetic cloud billing data (SYNTHETIC ONLY).")
    p.add_argument("--profile", choices=sorted(PROFILES), default="demo")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--out-dir", type=Path, default=GENERATED_DIR)
    args = p.parse_args(argv)

    billing, budgets = generate(args.profile, args.seed)
    b_path, g_path = write_outputs(billing, budgets, args.out_dir, args.profile)
    print(f"[synthetic data] profile={args.profile} seed={args.seed}")
    print(f"  billing: {len(billing):,} rows -> {b_path}")
    print(f"  budgets: {len(budgets):,} rows -> {g_path}")
    print(f"  injected anomalies: {int(billing['is_injected_anomaly'].sum())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
