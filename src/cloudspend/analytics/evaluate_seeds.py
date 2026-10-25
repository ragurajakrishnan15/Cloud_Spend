"""Robustness check: repeat the evaluation on independently generated synthetic datasets (different seeds).

A single seed gives one number from ~40 holdout anomalies; this shows how much it moves.
    python -m cloudspend.analytics.evaluate_seeds --seeds 1 2 3 4 5 6 7 8 9 10
Writes data/generated/model_outputs/seed_robustness.csv. Local only (no Snowflake).
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from cloudspend.analytics import anomaly_detection as ad
from cloudspend.analytics import forecasting as fc
from cloudspend.analytics import model_store as store
from cloudspend.data_generation.generate_billing import generate

RECORD_COLS = ["record_id", "usage_date", "resource_id", "department_name", "service_name", "environment_name",
               "region_name", "usage_units", "total_cost"]


def evaluate_seed(seed: int, profile: str = "demo") -> list[dict]:
    billing, _ = generate(profile, seed)
    billing["usage_date"] = pd.to_datetime(billing["usage_date"])
    rec = billing.rename(columns={"department": "department_name", "environment": "environment_name",
                                  "region": "region_name"})[RECORD_COLS]
    an = ad.run_pipeline(rec, billing[["record_id", "is_injected_anomaly", "anomaly_type"]])
    rows = []
    for method, periods in an.metrics.items():
        h = periods["holdout"]
        row = {"seed": seed, "family": "anomaly", "model": method, "precision": h["precision"], "recall": h["recall"],
               "f1": h["f1"], "false_positives": h["fp"], "n_positive": h["n_positive"]}
        for t in ("spike", "drift", "weekend_spend"):
            row[f"recall_{t}"] = h["by_type"].get(t, {}).get("detection_rate")
        rows.append(row)
    total = rec.groupby("usage_date")["total_cost"].sum()
    bt = fc.backtest(total)
    for model, m in bt.items():
        rows.append({"seed": seed, "family": "forecast", "model": model, "mae": m["mae"], "wape": m["wape"],
                     "interval_coverage": m["interval_coverage"]})
    return rows


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    metrics = [c for c in df.columns if c not in ("seed", "family", "model")]
    g = df.groupby(["family", "model"])[metrics]
    out = g.mean(numeric_only=True).add_suffix("_mean").join(g.std(numeric_only=True).add_suffix("_sd"))
    return out.dropna(axis=1, how="all")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, nargs="+", default=list(range(1, 11)))
    args = p.parse_args(argv)
    rows = [r for s in args.seeds for r in evaluate_seed(s)]
    df = pd.DataFrame(rows)
    store.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(store.OUTPUT_DIR / "seed_robustness.csv", index=False)
    pd.set_option("display.width", 220)
    print(summarize(df).round(3).T.to_string())
    f = df[df.family == "forecast"].pivot(index="seed", columns="model", values="wape")
    print(f"\nETS beat seasonal-naive on WAPE in {int((f[fc.MODEL_ETS] < f[fc.MODEL_BASELINE]).sum())}/{len(f)} seeds")
    a = df[df.family == "anomaly"].pivot(index="seed", columns="model", values="f1")
    print(f"Stat method F1 > Isolation Forest F1 in {int((a[ad.METHOD_STAT] > a[ad.METHOD_IF]).sum())}/{len(a)} seeds")
    print("min/max F1:", {m: (round(float(np.nanmin(a[m])), 3), round(float(np.nanmax(a[m])), 3)) for m in a})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
